"""Controlled, fail-closed HTTP/SSE entrance on the existing Hub ASGI app."""

import asyncio
from datetime import datetime
from urllib.parse import parse_qsl, quote

import httpx
from pydantic import SecretStr

from modules.identity.errors import IdentityError
from modules.workspaces.operations import WorkspaceError
from modules.workspaces.preview_timing import PreviewClock
from packages.contracts.p0.preview_contracts import CONNECTION_CLEANUP_MS, CONTROL_MAX_GAP_MS
from .preview_headers import COOKIE, cookie_and_headers, origin, platform_headers, request_allowed, response_headers, values
from .preview_transport import EXTENSION, PreviewConnection, PreviewTransport, clock_mark, observed_at


_BODY_LIMIT = 1024 * 1024
_REDEEM_LIMIT = 4096
_FINISH = (b"<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
           b"<title>CloudHelm</title></head><body><a href=\"/\">Enter preview</a></body></html>")


class _Rejected(Exception):
    def __init__(self, status=403):
        self.status = status


async def _call(method, *args, timeout=2):
    return await asyncio.wait_for(asyncio.to_thread(method, *args), timeout=timeout)


async def _answer(scope, send, status, body=b"", headers=()):
    if scope["type"] == "websocket":
        await send({"type": "websocket.close", "code": 1008})
        return
    await send({"type": "http.response.start", "status": status, "headers": [
        *platform_headers(finish=status == 200), (b"content-type", b"text/html; charset=utf-8"),
        (b"content-length", str(len(body)).encode("ascii")), *headers,
    ]})
    await send({"type": "http.response.body", "body": body, "more_body": False})


async def _body(scope, receive, limit):
    lengths = values(scope, b"content-length")
    if len(lengths) > 1 or any(not value.isdigit() or len(value) > 10 for value in lengths):
        raise _Rejected(400)
    if lengths and int(lengths[0]) > limit:
        raise _Rejected(413)
    if values(scope, b"content-encoding") not in ([], [b"identity"]):
        raise _Rejected(415)
    deadline = asyncio.get_running_loop().time() + 10
    body = bytearray()
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise _Rejected(408)
        try:
            message = await asyncio.wait_for(receive(), timeout=remaining)
        except TimeoutError:
            raise _Rejected(408) from None
        if message["type"] != "http.request":
            raise _Rejected(400)
        body.extend(message.get("body", b""))
        if len(body) > limit:
            raise _Rejected(413)
        if not message.get("more_body", False):
            return bytes(body)


class PreviewProxy:
    """Middleware: project hosts are never passed through to management routes."""

    def __init__(self, app, clock: PreviewClock | None = None):
        self.app = app
        self.clock = clock if clock is not None else PreviewClock()
        self.start_lock = asyncio.Lock()
        self.access = None
        self.identity = None
        self.sealed = {}
        self.connections = {}
        self.transports = {}
        self.transport_owner = None
        self.closing = {}
        self.receipts = {}
        self.reported = set()
        self.monitor = None
        self.reporter = None
        self.control_at = None
        self.control_failure = None

    def _upper_ms(self, start, end):
        if (start is None or end is None or start["epoch"] != end["epoch"]
                or end["epoch"] != self.clock.epoch or start["evidence_digest"] != end["evidence_digest"]):
            return None
        return self.clock.upper_ms(start["boottime_ns"], end["boottime_ns"])

    def _control_remaining_ms(self, now=None):
        """Return the remaining open budget, sealing existing flows on expiry or loss."""
        if self.control_at is None or self.control_failure is not None:
            return None
        now = clock_mark(self.clock) if now is None else now
        age = self._upper_ms(self.control_at, now)
        if age is None or age >= CONTROL_MAX_GAP_MS:
            self._fail_control("clock_untrusted" if age is None else "control_gap", now)
            return None
        return CONTROL_MAX_GAP_MS - age

    async def _start(self, access):
        async with self.start_lock:
            if self.access is access:
                return
            if access.proxy_identity is None or self.connections:
                raise _Rejected(503)
            pending = await _call(access.pending_revocations, access.proxy_identity)
            self.access, self.identity = access, access.proxy_identity
            self.sealed, self.closing, self.receipts, self.reported = {}, {}, {}, set()
            self.control_at = self.control_failure = None
            self._apply_control(pending)
            self.monitor = asyncio.create_task(self._monitor(access))
            if pending:
                self.reporter = asyncio.create_task(self._report_pending(access, pending))

    def _apply_control(self, pending):
        # Only a fully applied snapshot may renew the gate. A late reply cannot save old flows.
        observed = clock_mark(self.clock)
        self._control_remaining_ms(observed)
        for record in pending:
            self._seal(record.binding.authorization_id, ("authorization_closed", observed))
        now = clock_mark(self.clock)
        if self.control_at is not None and self.control_failure is None and not self._control_remaining_ms(now):
            now = clock_mark(self.clock)
        if now is None:
            self._fail_control("clock_untrusted", None)
        else:
            self.control_at, self.control_failure = now, None

    def _fail_control(self, reason, first_failure):
        if self.control_failure is not None:
            return
        self.control_failure = (reason, first_failure)
        if self.connections:
            denied = observed_at(self.clock)
            for authorization_id in self.connections:
                self._seal(authorization_id, self.control_failure, denied)

    def _seal(self, authorization_id, failure, denied=None):
        # Gate transitions and connection registration do not yield on the listener loop.
        if authorization_id in self.sealed:
            return
        reason, first_failure = failure
        denied = denied if denied is not None else observed_at(self.clock)
        self.sealed[authorization_id] = denied
        connections = tuple(self.transports[task] for task in self.connections.get(authorization_id, ()))
        self.closing[authorization_id] = (connections, {
            "trigger": reason, "last_verified": self.control_at, "first_failure": first_failure,
            "control_age_at_denial_upper_ms": self._upper_ms(self.control_at, denied["clock"]),
        })
        for connection in connections:
            connection.abort()
        if not connections:
            self._finish_close(authorization_id)

    def _finish_close(self, authorization_id):
        connections, timing = self.closing.pop(authorization_id)
        denied = self.sealed[authorization_id]
        connections = [connection.receipt() for connection in connections]
        stamps = [denied]
        for connection in connections:
            stamps.append(connection["downstream"]["connection_lost"])
            if connection["upstream"] is not None:
                stamps.append(connection["upstream"]["descriptor_closed"])
        closed = max(stamps, key=lambda stamp: stamp["boottime_ns"])
        denial_age = timing["control_age_at_denial_upper_ms"]
        control_age = self._upper_ms(timing["last_verified"], closed["clock"])
        failure_age = self._upper_ms(timing["first_failure"], closed["clock"])
        self.receipts[authorization_id] = {
            "denied": denied, "closed": closed, "connections": connections,
            "client_connections": 0, "upstream_connections": 0,
            "proxy_timing": {
                **timing, "control_age_at_closure_upper_ms": control_age, "failure_age_at_closure_upper_ms": failure_age,
                "denial_within_gap": None if denial_age is None else denial_age <= CONTROL_MAX_GAP_MS,
                "closure_within_cleanup": None if failure_age is None else failure_age <= CONNECTION_CLEANUP_MS,
                "closure_within_hard_cap": None if control_age is None else control_age <= CONTROL_MAX_GAP_MS + CONNECTION_CLEANUP_MS,
            },
        }

    async def _report_closed(self, access, record):
        authorization_id = record.binding.authorization_id
        receipt = self.receipts.get(authorization_id)
        owner = self.transport_owner
        if (receipt is None or authorization_id in self.reported or owner is None or owner.started is None
                or self.identity not in record.revocation.required_proxies):
            return
        receipt = {"transport_owner": owner.receipt(), **receipt}
        fact = (datetime.fromisoformat(receipt["denied"]["utc"]), datetime.fromisoformat(receipt["closed"]["utc"]))
        try:
            await _call(access.record_local_proxy_closure, authorization_id, self.identity, *fact, 0, 0)
            await _call(access.record_proxy_transport_closure, authorization_id, self.identity, receipt)
            self.reported.add(authorization_id)
        except Exception:
            # An unreported or unobservable closure remains pending in the authority.
            pass

    async def _report_pending(self, access, pending):
        # Visit the whole snapshot before retrying a failed receipt.
        for record in pending:
            await self._report_closed(access, record)

    async def _monitor(self, access):
        while True:
            await asyncio.sleep(1)
            remaining_ms = self._control_remaining_ms()
            timeout = 1.5 if remaining_ms is None else min(1.5, remaining_ms / 1000)
            try:
                pending = await _call(access.pending_revocations, self.identity, timeout=timeout)
            except Exception:
                self._fail_control("control_unavailable", clock_mark(self.clock))
                continue
            self._apply_control(pending)
            if pending and (self.reporter is None or self.reporter.done()):
                self.reporter = asyncio.create_task(self._report_pending(access, pending))

    async def _shutdown(self):
        self._fail_control("shutdown", clock_mark(self.clock))
        if self.monitor is not None:
            self.monitor.cancel()
            await asyncio.gather(self.monitor, return_exceptions=True)
            self.monitor = None
        if self.reporter is not None:
            self.reporter.cancel()
            await asyncio.gather(self.reporter, return_exceptions=True)
            self.reporter = None
        tasks = {task for group in self.connections.values() for task in group}
        if tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=2)
            except TimeoutError:
                pass

    async def _watch(self, access, cookie, authenticated, receive, task, body_read):
        async def disconnected():
            await body_read.wait()
            while (await receive())["type"] != "http.disconnect":
                pass

        disconnect = asyncio.create_task(disconnected())
        authorization_id = authenticated.authorization.binding.authorization_id
        try:
            while True:
                done, _ = await asyncio.wait({disconnect}, timeout=1)
                if done:
                    task.cancel()
                    return
                if not self._control_remaining_ms():
                    return
                try:
                    current = await _call(access.authenticate, cookie, authenticated.environment.environment_id)
                    if (current.authorization.binding != authenticated.authorization.binding
                            or current.environment != authenticated.environment):
                        raise _Rejected()
                except (WorkspaceError, IdentityError, _Rejected):
                    observed = clock_mark(self.clock)
                    if self._control_remaining_ms(observed):
                        self._seal(authorization_id, ("authorization_closed", observed))
                    return
                except Exception:
                    self._fail_control("control_unavailable", clock_mark(self.clock))
                    return
                if not self._control_remaining_ms():
                    return
        finally:
            disconnect.cancel()
            await asyncio.gather(disconnect, return_exceptions=True)

    async def _redeem(self, scope, receive, send, access, environment, target):
        if (scope["method"] != "POST" or scope.get("raw_path", b"") != b"/__cloudhelm/redeem"
                or scope.get("query_string", b"") or values(scope, b"origin") != [environment.management_origin.encode("ascii")]):
            raise _Rejected()
        content_type = values(scope, b"content-type")
        if len(content_type) != 1:
            raise _Rejected(415)
        pieces = [part.strip().lower() for part in content_type[0].split(b";")]
        if pieces[0] != b"application/x-www-form-urlencoded" or any(
            item not in {b"charset=utf-8", b'charset="utf-8"'} for item in pieces[1:]
        ):
            raise _Rejected(415)
        try:
            form = parse_qsl((await _body(scope, receive, _REDEEM_LIMIT)).decode("utf-8"),
                             strict_parsing=True, max_num_fields=1, encoding="utf-8", errors="strict")
        except (ValueError, UnicodeError):
            raise _Rejected(400) from None
        if len(form) != 1 or form[0][0] != "ticket" or not form[0][1]:
            raise _Rejected(400)
        if not self._control_remaining_ms():
            raise _Rejected()
        try:
            result = await _call(access.redeem, environment.management_origin, target, SecretStr(form[0][1]))
        except (WorkspaceError, IdentityError):
            raise _Rejected() from None
        except Exception:
            self._fail_control("control_unavailable", clock_mark(self.clock))
            raise _Rejected(503) from None
        if not self._control_remaining_ms() or result.authorization.binding.authorization_id in self.sealed:
            raise _Rejected()
        cookie = result.cookie.get_secret_value().encode("ascii")
        if not cookie or any(char not in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for char in cookie):
            raise _Rejected(503)
        await _answer(scope, send, 200, _FINISH, [(b"set-cookie", COOKIE + b"=" + cookie
            + b"; Path=/; Secure; HttpOnly; SameSite=Strict")])

    async def _forward(self, scope, receive, send, access, environment, target):
        if not request_allowed(scope, target):
            raise _Rejected()
        try:
            token, headers = cookie_and_headers(scope)
        except ValueError:
            raise _Rejected() from None
        cookie = SecretStr(token)
        try:
            authenticated = await _call(access.authenticate, cookie, environment.environment_id)
        except (WorkspaceError, IdentityError):
            raise _Rejected() from None
        except Exception:
            self._fail_control("control_unavailable", clock_mark(self.clock))
            raise _Rejected(503) from None
        if (authenticated.environment != environment or self.identity not in environment.required_proxies):
            raise _Rejected()
        authorization_id = authenticated.authorization.binding.authorization_id
        downstream = scope.get("extensions", {}).get(EXTENSION)
        if (not isinstance(downstream, PreviewTransport) or downstream.owner is not self.transport_owner
                or self.transport_owner.started is None):
            raise _Rejected(503)
        task = asyncio.current_task()
        if not self._control_remaining_ms() or authorization_id in self.sealed:
            raise _Rejected()
        connection = PreviewConnection(task, downstream, self.clock)
        self.connections.setdefault(authorization_id, set()).add(task)
        self.transports[task] = connection
        watcher = None
        started, complete = False, False

        async def tracked_send(message):
            nonlocal started, complete
            if not self._control_remaining_ms() or authorization_id in self.sealed:
                raise _Rejected()
            await send(message)
            if message["type"] == "http.response.start":
                started = True
            elif message["type"] == "http.response.body" and not message.get("more_body", False):
                complete = True

        try:
            body_read = asyncio.Event()
            watcher = asyncio.create_task(self._watch(access, cookie, authenticated, receive, task, body_read))
            body = await _body(scope, receive, _BODY_LIMIT)
            body_read.set()
            if not self._control_remaining_ms() or authorization_id in self.sealed:
                raise _Rejected()
            available = {item.service: item for item in environment.upstreams}
            upstream = available.get("frontend") or available.get("backend")
            if upstream is None:
                raise _Rejected(503)
            raw_path = scope.get("raw_path") or quote(scope["path"], safe="/").encode("ascii")
            if not raw_path.startswith(b"/") or b"?" in raw_path or b"#" in raw_path:
                raise _Rejected(400)
            query = scope.get("query_string", b"")
            url = httpx.URL(scheme=upstream.scheme, host=upstream.host, port=upstream.port,
                            raw_path=raw_path + (b"?" + query if query else b""))
            timeout = httpx.Timeout(connect=5, read=None, write=10, pool=5)
            async with httpx.AsyncClient(timeout=timeout, trust_env=False, follow_redirects=False) as client:
                async with client.stream(scope["method"], url, headers=headers, content=body,
                                         extensions={"trace": connection.trace}) as response:
                    safe_headers = [*response_headers(response.headers.raw, target), (b"connection", b"close")]
                    await tracked_send({"type": "http.response.start", "status": response.status_code,
                                        "headers": safe_headers})
                    async for chunk in response.aiter_raw():
                        await tracked_send({"type": "http.response.body", "body": chunk, "more_body": True})
            await tracked_send({"type": "http.response.body", "body": b"", "more_body": False})
        except asyncio.CancelledError:
            downstream.abort()
        except OSError:
            downstream.abort()
        except _Rejected as error:
            if not started and authorization_id not in self.sealed:
                await _answer(scope, send, error.status, headers=[(b"connection", b"close")])
        except Exception:
            if not started and authorization_id not in self.sealed:
                await _answer(scope, send, 502, headers=[(b"connection", b"close")])
        finally:
            connection.finishing = True
            if watcher is not None:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
            if started and not complete:
                downstream.abort()
            await connection.wait_closed()
            del self.transports[task]
            self.connections[authorization_id].discard(task)
            if not self.connections[authorization_id]:
                del self.connections[authorization_id]
                if authorization_id in self.sealed:
                    self._finish_close(authorization_id)

    async def __call__(self, scope, receive, send):
        if self.transport_owner is None and "app" in scope:
            self.transport_owner = getattr(scope["app"].state, "preview_transport_owner", None)
        if scope["type"] == "lifespan":
            async def lifespan_receive():
                message = await receive()
                if message["type"] == "lifespan.shutdown":
                    await self._shutdown()
                return message

            async def lifespan_send(message):
                if message["type"] == "lifespan.startup.complete":
                    runtime = getattr(scope["app"].state, "runtime", None)
                    access = getattr(runtime, "previews", None)
                    if access is not None and access.proxy_identity is not None:
                        try:
                            await self._start(access)
                        except Exception:
                            pass
                await send(message)

            await self.app(scope, lifespan_receive, lifespan_send)
            return
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        try:
            target = origin(scope)
            environment = None
            if target is not None:
                runtime = getattr(scope["app"].state, "runtime", None)
                descriptor = runtime.preview_environments.installation if runtime is not None else None
                if (descriptor is None or (target != descriptor.management_origin
                        and target.endswith("." + descriptor.preview_domain))):
                    access = getattr(runtime, "previews", None)
                    if access is None:
                        raise _Rejected(503)
                    try:
                        environment = await _call(access.environment_for_origin, target)
                    except WorkspaceError as error:
                        if error.code != "preview_environment_not_found" or error.status_code != 404:
                            raise
        except _Rejected as error:
            await _answer(scope, send, error.status)
            return
        except (ValueError, UnicodeError):
            await _answer(scope, send, 400)
            return
        except Exception:
            self._fail_control("control_unavailable", clock_mark(self.clock))
            await _answer(scope, send, 503)
            return
        if environment is None:
            await self.app(scope, receive, send)
            return
        try:
            await self._start(access)
            if (scope["type"] != "http" or scope.get("scheme") != "https"
                    or not self._control_remaining_ms()
                    or values(scope, b"host")[0].lower() not in {
                        target[8:].encode("ascii"), (target[8:] + ":443").encode("ascii")}
                    or self.identity not in environment.required_proxies):
                raise _Rejected()
            path = scope.get("path", "")
            if path.startswith("/__cloudhelm"):
                if path != "/__cloudhelm/redeem":
                    raise _Rejected(404)
                await self._redeem(scope, receive, send, access, environment, target)
            else:
                await self._forward(scope, receive, send, access, environment, target)
        except OSError:
            return
        except _Rejected as error:
            await _answer(scope, send, error.status)
        except (ValueError, UnicodeError):
            await _answer(scope, send, 400)
        except Exception:
            self._fail_control("control_unavailable", clock_mark(self.clock))
            await _answer(scope, send, 503)
