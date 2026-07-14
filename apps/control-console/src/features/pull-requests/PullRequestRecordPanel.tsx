import { formatDateTime, formatJson } from '../../shared/api/formatters'
import type { PullRequestRecordRead } from '../../shared/types/api'
import {
  safeExternalUrl,
  shortSha,
  statusTone,
} from '../local-development/evidenceViewModel'

/**
 * 本地等价 PR record 展示。
 *
 * M6 的 provider=local 且 url=null；页面明确展示等价记录边界，不构造远端
 * 链接。未来接入真实 Git provider 时，仅渲染经过协议校验的 HTTP(S) URL。
 */
export function PullRequestRecordPanel({
  record,
}: {
  record: PullRequestRecordRead | null
}) {
  if (record === null) {
    return (
      <section className="evidence-card evidence-card-wide" aria-labelledby="pull-request-record-title">
        <div className="evidence-card-heading">
          <div>
            <p className="eyebrow">Git 交付</p>
            <h3 id="pull-request-record-title">Pull Request Record</h3>
          </div>
          <span className="evidence-status tone-neutral">等待门禁完成</span>
        </div>
        <p className="empty-state">测试、Review 和安全门禁通过后生成真实本地 branch、commit 与等价 PR record。</p>
      </section>
    )
  }

  const safeUrl = safeExternalUrl(record.url)

  return (
    <section className="evidence-card evidence-card-wide pull-request-record" aria-labelledby="pull-request-record-title">
      <div className="evidence-card-heading">
        <div>
          <p className="eyebrow">Git 交付</p>
          <h3 id="pull-request-record-title">{record.title}</h3>
        </div>
        <span className={`evidence-status tone-${statusTone(record.status)}`}>{record.status}</span>
      </div>

      <div className="local-pr-boundary">
        <span className="evidence-status tone-positive">{record.provider}</span>
        {record.provider === 'local' && record.url === null ? (
          <strong>本地等价 PR 记录 · 无远端链接</strong>
        ) : safeUrl === null ? (
          <strong>远端链接未通过协议校验</strong>
        ) : (
          <a href={safeUrl} target="_blank" rel="noreferrer">打开远端 PR</a>
        )}
      </div>

      <p className="evidence-summary">{record.summary}</p>
      <div className="branch-flow" aria-label="本地分支流向">
        <code>{record.base_branch}</code>
        <span aria-hidden="true">←</span>
        <code>{record.head_branch}</code>
      </div>

      <dl className="artifact-meta-grid">
        <div>
          <dt>Commit</dt>
          <dd title={record.commit_sha}>{shortSha(record.commit_sha)}</dd>
        </div>
        <div>
          <dt>Base commit</dt>
          <dd title={record.base_commit_sha}>{shortSha(record.base_commit_sha)}</dd>
        </div>
        <div>
          <dt>Changed files</dt>
          <dd>{record.changed_files_json.length}</dd>
        </div>
        <div>
          <dt>创建时间</dt>
          <dd>{formatDateTime(record.created_at)}</dd>
        </div>
        <div className="wide">
          <dt>Record ID</dt>
          <dd>{record.id}</dd>
        </div>
      </dl>

      <details className="evidence-disclosure" open>
        <summary><span>Changed files</span><span>{record.changed_files_json.length}</span></summary>
        <ul className="changed-file-list">
          {record.changed_files_json.map((file, index) => (
            <li key={`${file.path}-${index}`}>
              <code>{file.path}</code>
              <span>{typeof file.operation === 'string' ? file.operation : 'changed'}</span>
            </li>
          ))}
        </ul>
      </details>

      <details className="evidence-disclosure">
        <summary><span>Diff stat</span><span>{Object.keys(record.diff_stat_json).length} 项</span></summary>
        <pre>{formatJson(record.diff_stat_json)}</pre>
      </details>
    </section>
  )
}
