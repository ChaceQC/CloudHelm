import type { ArtifactDetailRead } from '../../shared/types/api'
import { ArtifactEvidenceMeta } from '../local-development/ArtifactEvidenceMeta'
import {
  artifactJsonRecord,
  artifactPreviewText,
  readBoolean,
  readNumber,
  readRecordArray,
  readString,
  readStringArray,
  statusTone,
} from '../local-development/evidenceViewModel'

/**
 * Reviewer Agent 的 AC 映射与代码审查结论。
 */
export function ReviewReportPanel({ artifact }: { artifact: ArtifactDetailRead | null }) {
  if (artifact === null) {
    return (
      <section className="evidence-card" aria-labelledby="review-report-title">
        <EvidenceHeading verdict={null} />
        <p className="empty-state">Reviewer 尚未生成 ReviewReport Artifact。</p>
      </section>
    )
  }

  const report = artifactJsonRecord(artifact)
  const verdict = readString(report, 'verdict')
  const acceptanceResults = readRecordArray(report, 'acceptance_results')
  const issues = readRecordArray(report, 'issues')
  const changedFiles = readRecordArray(report, 'changed_files')
  const proceeds = readBoolean(report, 'proceed_to_security')

  return (
    <section className="evidence-card" aria-labelledby="review-report-title">
      <EvidenceHeading verdict={verdict} />
      <p className="evidence-summary">{readString(report, 'summary') ?? artifact.summary}</p>
      <dl className="report-metric-grid">
        <div>
          <dt>AC</dt>
          <dd>{acceptanceResults.length}</dd>
        </div>
        <div>
          <dt>问题</dt>
          <dd>{issues.length}</dd>
        </div>
        <div>
          <dt>变更文件</dt>
          <dd>{changedFiles.length}</dd>
        </div>
        <div>
          <dt>进入安全检查</dt>
          <dd>{proceeds === null ? '—' : proceeds ? '是' : '否'}</dd>
        </div>
      </dl>

      <details className="evidence-disclosure" open>
        <summary>
          <span>Acceptance Criteria</span>
          <span>{acceptanceResults.length}</span>
        </summary>
        {acceptanceResults.length === 0 ? (
          <p className="empty-state">报告未记录 AC 映射。</p>
        ) : (
          <div className="acceptance-result-list">
            {acceptanceResults.map((result, index) => {
              const status = readString(result, 'status')
              const criterionId = readString(result, 'criterion_id') ?? `AC-${index + 1}`
              return (
                <article key={`${criterionId}-${index}`}>
                  <div>
                    <strong>{criterionId}</strong>
                    <span className={`evidence-status tone-${statusTone(status)}`}>
                      {status ?? 'unknown'}
                    </span>
                  </div>
                  <p>{readString(result, 'notes') ?? '未记录评审说明。'}</p>
                  <small>
                    Evidence：{readStringArray(result, 'evidence_refs').join('、') || '无引用'}
                  </small>
                </article>
              )
            })}
          </div>
        )}
      </details>

      {issues.length === 0 ? null : (
        <details className="evidence-disclosure" open>
          <summary><span>Review issues</span><span>{issues.length}</span></summary>
          <div className="finding-list">
            {issues.map((issue, index) => {
              const severity = readString(issue, 'severity')
              const path = readString(issue, 'path')
              const line = readNumber(issue, 'line')
              return (
                <article key={`${readString(issue, 'id') ?? 'issue'}-${index}`}>
                  <div>
                    <strong>{readString(issue, 'id') ?? `ISSUE-${index + 1}`}</strong>
                    <span className={`evidence-status tone-${statusTone(severity)}`}>
                      {severity ?? 'unknown'}
                    </span>
                  </div>
                  <p>{readString(issue, 'message') ?? '未记录问题说明。'}</p>
                  <small>{path === null ? '未关联文件' : `${path}${line === null ? '' : `:${line}`}`}</small>
                  <p className="evidence-recommendation">
                    建议：{readString(issue, 'recommendation') ?? '未记录'}
                  </p>
                </article>
              )
            })}
          </div>
        </details>
      )}

      {report === null ? <RawPreview artifact={artifact} /> : null}
      <ArtifactEvidenceMeta artifact={artifact} />
    </section>
  )
}

function EvidenceHeading({ verdict }: { verdict: string | null }) {
  return (
    <div className="evidence-card-heading">
      <div>
        <p className="eyebrow">审查门禁</p>
        <h3 id="review-report-title">Review Report</h3>
      </div>
      <span className={`evidence-status tone-${statusTone(verdict)}`}>
        {verdict ?? '等待审查'}
      </span>
    </div>
  )
}

function RawPreview({ artifact }: { artifact: ArtifactDetailRead }) {
  const raw = artifactPreviewText(artifact)
  return raw === null ? null : (
    <details className="evidence-disclosure">
      <summary><span>原始报告预览</span><span>{artifact.media_type}</span></summary>
      <pre>{raw}</pre>
    </details>
  )
}
