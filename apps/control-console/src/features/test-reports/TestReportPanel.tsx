import type { ArtifactDetailRead } from '../../shared/types/api'
import { ArtifactEvidenceMeta } from '../local-development/ArtifactEvidenceMeta'
import { CommandEvidenceList } from '../local-development/CommandEvidenceList'
import {
  artifactJsonRecord,
  artifactPreviewText,
  readNumber,
  readRecordArray,
  readString,
  readStringArray,
  statusTone,
} from '../local-development/evidenceViewModel'

/**
 * Tester Agent 真实测试报告。
 */
export function TestReportPanel({ artifact }: { artifact: ArtifactDetailRead | null }) {
  if (artifact === null) {
    return (
      <section className="evidence-card" aria-labelledby="test-report-title">
        <EvidenceHeading status={null} />
        <p className="empty-state">Tester 尚未生成 TestReport Artifact。</p>
      </section>
    )
  }

  const report = artifactJsonRecord(artifact)
  const status = readString(report, 'status')
  const commands = readRecordArray(report, 'commands')
  const failureReasons = readStringArray(report, 'failure_reasons')

  return (
    <section className="evidence-card" aria-labelledby="test-report-title">
      <EvidenceHeading status={status} />
      <p className="evidence-summary">{readString(report, 'summary') ?? artifact.summary}</p>
      <dl className="report-metric-grid">
        <div>
          <dt>通过</dt>
          <dd>{readNumber(report, 'passed_count') ?? '—'}</dd>
        </div>
        <div>
          <dt>失败</dt>
          <dd>{readNumber(report, 'failed_count') ?? '—'}</dd>
        </div>
        <div>
          <dt>跳过</dt>
          <dd>{readNumber(report, 'skipped_count') ?? '—'}</dd>
        </div>
        <div>
          <dt>命令</dt>
          <dd>{commands.length}</dd>
        </div>
      </dl>

      <CommandEvidenceList commands={commands} emptyText="报告未记录命令证据。" />

      {failureReasons.length === 0 ? null : (
        <div className="evidence-callout tone-negative">
          <strong>失败原因</strong>
          <ul>
            {failureReasons.map((reason, index) => <li key={`${reason}-${index}`}>{reason}</li>)}
          </ul>
        </div>
      )}

      {report === null ? <RawPreview artifact={artifact} /> : null}
      {artifact.preview?.truncated === true ? (
        <p className="evidence-warning">测试报告预览已由服务端截断。</p>
      ) : null}
      <ArtifactEvidenceMeta artifact={artifact} />
    </section>
  )
}

function EvidenceHeading({ status }: { status: string | null }) {
  return (
    <div className="evidence-card-heading">
      <div>
        <p className="eyebrow">测试门禁</p>
        <h3 id="test-report-title">Test Report</h3>
      </div>
      <span className={`evidence-status tone-${statusTone(status)}`}>
        {status ?? '等待测试'}
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
