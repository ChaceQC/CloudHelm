"""A trusted management document hands a ticket directly to the platform POST endpoint."""

import html
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from packages.contracts.p0.decision_common import Identifier
from .auth import get_runtime
from .errors import ApiRequestError

router = APIRouter()


@router.get("/preview/start/{environment_id}", response_class=HTMLResponse, include_in_schema=False)
def start_page(request: Request, environment_id: Identifier):
    descriptor = get_runtime(request).preview_environments.installation
    if descriptor is None:
        raise ApiRequestError("preview_route_unavailable", 409)
    if str(request.base_url).rstrip("/") != descriptor.management_origin:
        raise ApiRequestError("preview_origin_invalid", 403)
    identifier = html.escape(environment_id, quote=True)
    page = """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>CloudHelm 预览访问</title>
<style>body{font:16px system-ui;max-width:680px;margin:4rem auto;padding:1rem;color:#18202c}
label,input,button{display:block;margin:1rem 0}input{width:95%;padding:.7rem}button{padding:.65rem 1.3rem}
pre{white-space:pre-wrap}small{color:#59677a}</style>
<h1>进入固定环境预览</h1><p>请用当前管理会话验证身份。访问仅适用于本环境；人测结论仍在 Task 页明确提交。</p>
<small>会话凭据仅在本页内存中用于当前请求，不保存到浏览器存储。环境回收后未提交的页面内容可能丢失。</small>
<form id="access"><label>管理会话凭据<input id="credential" type="password" required autocomplete="off"></label>
<button>核验并进入预览</button></form><button id="revoke" hidden>撤销本次访问</button><pre id="status"></pre>
<script>
const environmentId = document.body.dataset.environment;
const status = document.getElementById('status'); let authorizationId = null;
async function call(path, credential, init = {}) {
  const response = await fetch(path, {...init, cache:'no-store', redirect:'error',
    headers:{'Authorization':'Bearer ' + credential, ...init.headers}});
  const body = await response.json(); if (!response.ok) throw Error(body.code || 'request_failed'); return body;
}
document.getElementById('access').onsubmit = async event => {
  event.preventDefault(); let credential = document.getElementById('credential').value;
  const button = event.target.querySelector('button'); button.disabled = true;
  try {
    const base = '/api/preview-environments/' + encodeURIComponent(environmentId);
    const guard = await call(base + '/access-request', credential);
    const result = await call(base + '/access', credential, {method:'POST',
      headers:{'Content-Type':'application/json','Idempotency-Key':crypto.randomUUID()},body:JSON.stringify(guard)});
    authorizationId = result.authorization.binding.authorization_id;
    document.getElementById('revoke').hidden = false;
    if (!result.ticket) throw Error('票据已交付，请先撤销原访问并等待确认后重新申请。');
    const form = document.createElement('form'); form.method = 'POST';
    form.action = 'https://' + environmentId + '.' + document.body.dataset.domain + '/__cloudhelm/redeem';
    const input = document.createElement('input'); input.type = 'hidden'; input.name = 'ticket'; input.value = result.ticket;
    form.append(input); document.body.append(form); result.ticket = null; form.submit(); input.value = ''; form.remove();
  } catch (error) { status.textContent = error.message + '\n响应不明时请查询或撤销原授权，不要将重试当成新授权。'; }
  finally { credential = null; document.getElementById('credential').value = ''; button.disabled = false; }
};
document.getElementById('revoke').onclick = async () => {
  let credential = document.getElementById('credential').value;
  if (!credential || !authorizationId) { status.textContent = '请填写当前管理会话凭据后撤销。'; return; }
  try { await call('/api/preview-authorizations/' + encodeURIComponent(authorizationId) + '/revoke', credential,
    {method:'POST',headers:{'Idempotency-Key':crypto.randomUUID()}});
    status.textContent = '撤销已请求；须等待全部入口关闭确认。';
  } catch (error) { status.textContent = error.message; }
  finally { credential = null; document.getElementById('credential').value = ''; }
};
</script></html>"""
    page = page.replace("<h1>", '<body data-environment="' + identifier + '" data-domain="' +
                        html.escape(descriptor.preview_domain, quote=True) + '"><h1>', 1)
    return HTMLResponse(page, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                                   "connect-src 'self'; form-action https://*." + descriptor.preview_domain +
                                   "; base-uri 'none'; frame-ancestors 'none'"})


class ManagementHostBoundary:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        runtime = getattr(scope.get("app", object()).state, "runtime", None) if scope.get("app") else None
        descriptor = runtime.preview_environments.installation if runtime else None
        if descriptor is not None and scope["type"] in {"http", "websocket"}:
            hosts = [value.decode("latin-1") for key, value in scope.get("headers", ()) if key.lower() == b"host"]
            if hosts != [urlsplit(descriptor.management_origin).netloc]:
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                else:
                    await HTMLResponse("入口不可用", status_code=404)(scope, receive, send)
                return
        await self.app(scope, receive, send)
