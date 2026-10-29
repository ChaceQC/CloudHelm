"""The fixed HTTP subset and credential boundary for preview traffic."""

import re
from urllib.parse import urlsplit


COOKIE = b"__Host-cloudhelm-preview"
_HOP = {b"connection", b"keep-alive", b"proxy-authenticate", b"proxy-authorization",
        b"te", b"trailer", b"transfer-encoding", b"upgrade", b"proxy-connection"}
_PRIVATE = {b"authorization", b"authentication-info", b"proxy-authentication-info"}
_PLATFORM = (
    (b"cache-control", b"no-store"), (b"referrer-policy", b"no-referrer"),
    (b"x-content-type-options", b"nosniff"), (b"x-frame-options", b"DENY"),
    (b"content-security-policy", b"default-src 'self'; object-src 'none'; "
     b"worker-src 'none'; child-src 'none'; frame-ancestors 'none'; "
     b"base-uri 'none'; form-action 'self'"),
    (b"connection", b"close"),
)
_FINISH_CSP = (b"content-security-policy", b"default-src 'none'; base-uri 'none'; "
               b"form-action 'none'; frame-ancestors 'none'")


def values(scope, name):
    return [value for key, value in scope.get("headers", ()) if key.lower() == name]


def origin(scope):
    hosts = values(scope, b"host")
    if len(hosts) != 1:
        raise ValueError("invalid_host")
    raw = hosts[0].decode("ascii").lower()
    parsed = urlsplit("https://" + raw)
    if (not parsed.hostname or parsed.username is not None or parsed.password is not None
            or parsed.path or parsed.query or parsed.fragment):
        raise ValueError("invalid_host")
    _ = parsed.port
    host = parsed.hostname.removesuffix(".")
    if ":" in host:
        return None
    if not re.fullmatch(r"(?=.{1,253}$)[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host):
        raise ValueError("invalid_host")
    return "https://" + host


def cookie_and_headers(scope):
    connections = b",".join(values(scope, b"connection")).lower().split(b",")
    blocked = _HOP | _PRIVATE | {part.strip() for part in connections} | {b"host", b"content-length"}
    selected, cookies, credentials = [], [], []
    for name, value in scope.get("headers", ()):
        key = name.lower()
        if key == b"cookie":
            for part in value.split(b";"):
                part = part.strip()
                if not part:
                    continue
                cookie_name, separator, cookie_value = part.partition(b"=")
                if separator and cookie_name.strip().lower() == COOKIE.lower():
                    credentials.append(cookie_value)
                else:
                    cookies.append(part)
        elif (key not in blocked and not key.startswith((b"x-cloudhelm-", b"x-internal-", b"x-forwarded-"))
              and key != b"forwarded"):
            selected.append((name, value))
    if len(credentials) != 1 or not re.fullmatch(rb"[A-Za-z0-9_-]{1,256}", credentials[0]):
        raise ValueError("preview_cookie_required")
    if cookies:
        selected.append((b"cookie", b"; ".join(cookies)))
    return credentials[0].decode("ascii"), selected


def request_allowed(scope, target_origin):
    if scope.get("method") not in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}:
        return False
    if values(scope, b"upgrade") or values(scope, b"service-worker"):
        return False
    if any(value.lower() in {b"worker", b"sharedworker", b"serviceworker"}
           for value in values(scope, b"sec-fetch-dest")):
        return False
    origins = values(scope, b"origin")
    if origins and origins != [target_origin.encode("ascii")]:
        return False
    path = scope.get("path", "")
    if any(part in {".", ".."} for part in path.split("/")) or "\\" in path:
        return False
    return not path.startswith(("/@vite/", "/@react-refresh", "/__vite_ping"))


def response_headers(headers, target_origin):
    connections = b",".join(value for name, value in headers if name.lower() == b"connection").lower().split(b",")
    blocked = _HOP | _PRIVATE | {part.strip() for part in connections} | {
        b"cache-control", b"pragma", b"expires", b"content-length", b"service-worker-allowed",
        b"clear-site-data", b"refresh",
    }
    selected = []
    for name, value in headers:
        key = name.lower()
        if (key in blocked or key.startswith((b"x-cloudhelm-", b"x-internal-", b"x-forwarded-"))
                or key == b"forwarded"):
            continue
        if key == b"set-cookie":
            cookie_name = value.split(b"=", 1)[0].strip().lower()
            if cookie_name == COOKIE.lower() or re.search(rb"(?:^|;)\s*domain\s*=", value, re.I):
                continue
        if key == b"location":
            location = value.decode("latin-1")
            if "\\" in location or any(ord(char) < 32 for char in location):
                raise ValueError("preview_redirect_denied")
            parsed = urlsplit(location)
            if parsed.scheme or parsed.netloc:
                if f"{parsed.scheme}://{parsed.netloc}" != target_origin:
                    raise ValueError("preview_redirect_denied")
            elif location.startswith("//"):
                raise ValueError("preview_redirect_denied")
        selected.append((name, value))
    return [*selected, *_PLATFORM]


def platform_headers(*, finish=False):
    if not finish:
        return list(_PLATFORM)
    return [header for header in _PLATFORM if header[0] != b"content-security-policy"] + [_FINISH_CSP]
