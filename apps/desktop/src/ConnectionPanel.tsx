import { useState } from "react";
import type { Hub } from "./useHub";
import { Facts, Status } from "./ui";

export function ConnectionPanel({ hub }: { hub: Hub }) {
  const [base, setBase] = useState("http://127.0.0.1:19080");
  const [dev, setDev] = useState(false);
  const [importCredential, setImport] = useState(true);
  return <section className="connection-grid"><form className="card" onSubmit={e => {
    e.preventDefault(); void hub.connect(base, importCredential, dev);
  }}><div className="section-title"><h2>连接 Hub</h2><Status value={hub.connection}/></div>
    <label>Hub 地址<input type="url" value={base} onChange={e => setBase(e.target.value)} required spellCheck={false}/></label>
    <label className="check"><input type="checkbox" checked={importCredential} onChange={e => setImport(e.target.checked)}/>从本机文件导入会话凭据</label>
    <label className="check"><input type="checkbox" checked={dev} onChange={e => setDev(e.target.checked)}/>允许本机 HTTP 开发接口</label>
    <div className="actions"><button className="primary" disabled={hub.connection === "connecting"}>连接</button>
      <button type="button" onClick={() => { void hub.disconnect(); }}>断开</button>
      <button type="button" onClick={() => { void hub.disconnect(true); }}>断开并删除已保存凭据</button></div>
    <p className="muted">凭据由系统文件选择器读取并保存到 Windows 凭据存储。</p>
  </form><section className="card"><h2>当前会话</h2>{hub.identity ? <Facts values={{ "用户": hub.identity.display_name,
    "用户 ID": hub.identity.user_id, "会话": hub.identity.session_id, "有效期": hub.identity.expires_at }}/>
    : <p className="muted">连接后显示身份与会话期限。</p>}
    {hub.snapshot && <Facts values={{ "同步流": hub.snapshot.stream_id, "快照游标": hub.snapshot.cursor,
      "快照时间": hub.snapshot.captured_at, "权限修订": hub.snapshot.project.permission_revision }}/>}</section></section>;
}
