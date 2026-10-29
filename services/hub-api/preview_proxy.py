"""Controlled, fail-closed HTTP/SSE entrance on the existing Hub ASGI app."""

import asyncio
import time
from datetime import datetime, timezone
from urllib.parse import parse_qsl, quote

import httpx
from pydantic import SecretStr

from modules.identity.errors import IdentityError
from modules.workspaces.operations import WorkspaceError
from .preview_headers import COOKIE, cookie_and_headers, origin, platform_headers, request_allowed, response_headers, values


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

    def __init__(self, app):
        self.app = app
        self.lock = asyncio.Lock()
        self.start_lock = asyncio.Lock()
        self.access = None
        self.identity = None
        self.sealed = {}
        self.connections = {}
        self.closures = {}
        self.reported = set()
        self.monitor = None
        self.reporter = None
        self.control_at = None

    def _control_current(self):
        if self.control_at is None or not hasattr(time, "CLOCK_BOOTTIME"):
            return False
        return 0 <= time.clock_gettime(time.CLOCK_BOOTTIME) - self.control_at < 3

    async def _start(self, access):
        async with self.start_lock:
            if self.access is access:
                return
            if access.proxy_identity is None or self.connections or not hasattr(time, "CLOCK_BOOTTIME"):
                raise _Rejected(503)
            pending = await _call(access.pending_revocations, access.proxy_identity)
            self.access, self.identity = access, access.proxy_identity
            self.control_at = time.clock_gettime(time.CLOCK_BOOTTIME)
            self.sealed = {record.binding.authorization_id: datetime.now(timezone.utc) for record in pending}
            self.closures, self.reported = {}, set()
            for record in pending:
                if self.identity in record.revocation.required_proxies:
                    await self._report_closed(access, record)
            self.monitor = asyncio.create_task(self._monitor(access))

    async def _seal(self, authorization_id):
        async with self.lock:
            if authorization_id in self.sealed:
                return
            self.sealed[authorization_id] = datetime.now(timezone.utc)
            for task in tuple(self.connections.get(authorization_id, ())):
                task.cancel()

    async def _seal_all(self):
        for authorization_id in tuple(self.connections):
            await self._seal(authorization_id)

    async def _report_closed(self, access, record):
        authorization_id = record.binding.authorization_id
        async with self.lock:
            denied_at = self.sealed.get(authorization_id)
            if (denied_at is None or self.connections.get(authorization_id) or authorization_id in self.reported
                    or self.identity not in record.revocation.required_proxies):
                return
            fact = self.closures.setdefault(authorization_id, (denied_at, datetime.now(timezone.utc)))
        try:
            await _call(access.record_local_proxy_closure, authorization_id, self.identity, *fact, 0, 0)
            self.reported.add(authorization_id)
        except Exception:
            # An unreported or unobservable closure remains pending in the authority.
            pass

    async def _monitor(self, access):
        while True:
            await asyncio.sleep(1)
            try:
                # Leave time after the one-second polling interval to close before the three-second limit.
                pending = await _call(access.pending_revocations, self.identity, timeout=1.5)
            except Exception:
                self.control_at = None
                await self._seal_all()
                continue
            self.control_at = time.clock_gettime(time.CLOCK_BOOTTIME)
            for record in pending:
                await self._seal(record.binding.authorization_id)
                authorization_id = record.binding.authorization_id
                if (self.identity in record.revocation.required_proxies and authorization_id not in self.reported
                        and not self.connections.get(authorization_id)
                        and (self.reporter is None or self.reporter.done())):
                    self.reporter = asyncio.create_task(self._report_closed(access, record))

    async def _shutdown(self):
        self.control_at = None
        if self.monitor is not None:
            self.monitor.cancel()
            await asyncio.gather(self.monitor, return_exceptions=True)
            self.monitor = None
        if self.reporter is not None:
            self.reporter.cancel()
            await asyncio.gather(self.reporter, return_exceptions=True)
            self.reporter = None
        tasks = {task for group in self.connections.values() for task in group}
        await self._seal_all()
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
                if not self._control_current():
                    await self._seal_all()
                    return
                try:
                    current = await _call(access.authenticate, cookie, authenticated.environment.environment_id)
                    if (current.authorization.binding != authenticated.authorization.binding
                            or current.environment != authenticated.environment):
                        raise _Rejected()
                except (WorkspaceError, IdentityError, _Rejected):
                    await self._seal(authorization_id)
                    return
                except Exception:
                    await self._seal_all()
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
        try:
            result = await _call(access.redeem, environment.management_origin, target, SecretStr(form[0][1]))
        except (WorkspaceError, IdentityError):
            raise _Rejected() from None
        async with self.lock:
            if not self._control_current() or result.authorization.binding.authorization_id in self.sealed:
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
        if (authenticated.environment != environment or self.identity not in environment.required_proxies):
            raise _Rejected()
        authorization_id = authenticated.authorization.binding.authorization_id
        task = asyncio.current_task()
        async with self.lock:
            if not self._control_current() or authorization_id in self.sealed:
                raise _Rejected()
            self.connections.setdefault(authorization_id, set()).add(task)
        watcher = None
        started, complete = False, False

        async def tracked_send(message):
            nonlocal started, complete
            if message["type"] == "http.response.start":
                started = True
            elif message["type"] == "http.response.body" and not message.get("more_body", False):
                complete = True
            await send(message)

        try:
            body_read = asyncio.Event()
            watcher = asyncio.create_task(self._watch(access, cookie, authenticated, receive, task, body_read))
            body = await _body(scope, receive, _BODY_LIMIT)
            body_read.set()
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
                async with client.stream(scope["method"], url, headers=headers, content=body) as response:
                    safe_headers = response_headers(response.headers.raw, target)
                    await tracked_send({"type": "http.response.start", "status": response.status_code,
                                        "headers": safe_headers})
                    async for chunk in response.aiter_raw():
                        await tracked_send({"type": "http.response.body", "body": chunk, "more_body": True})
            await tracked_send({"type": "http.response.body", "body": b"", "more_body": False})
        except asyncio.CancelledError:
            if not started:
                await _answer(scope, tracked_send, 403)
        except OSError:
            return
        except _Rejected as error:
            if not started:
                await _answer(scope, tracked_send, error.status)
        except Exception:
            if not started:
                await _answer(scope, tracked_send, 502)
        finally:
            if watcher is not None:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
            if started and not complete:
                try:
                    await tracked_send({"type": "http.response.body", "body": b"", "more_body": False})
                except OSError:
                    pass
            async with self.lock:
                self.connections[authorization_id].discard(task)
                if not self.connections[authorization_id]:
                    del self.connections[authorization_id]

    async def __call__(self, scope, receive, send):
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
            if target is None:
                environment = None
            else:
                runtime = getattr(scope["app"].state, "runtime", None)
                access = getattr(runtime, "previews", None)
                if access is None:
                    raise _Rejected(503)
                try:
                    environment = await _call(access.environment_for_origin, target)
                except WorkspaceError as error:
                    if error.code != "preview_environment_not_found" or error.status_code != 404:
                        raise
                    environment = None
        except _Rejected as error:
            await _answer(scope, send, error.status)
            return
        except (ValueError, UnicodeError):
            await _answer(scope, send, 400)
            return
        except Exception:
            await self._seal_all()
            await _answer(scope, send, 503)
            return
        if environment is None:
            await self.app(scope, receive, send)
            return
        try:
            await self._start(access)
            if (scope["type"] != "http" or scope.get("scheme") != "https"
                    or not self._control_current()
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
            await self._seal_all()
            await _answer(scope, send, 503)
