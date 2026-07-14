import type { ArtifactDetailRead } from '../../shared/types/api'
import { ArtifactEvidenceMeta } from '../local-development/ArtifactEvidenceMeta'
import { CommandEvidenceList } from '../local-development/CommandEvidenceList'
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
 * Security Agent 的真实扫描结果与 PR 阻断结论。
 */
export function SecurityReportPanel({ artifact }: { artifact: ArtifactDetailRead | null }) {
  if (artifact === null) {
    return (
      <section className="evidence-card" aria-labelledby="security-report-title">
        <EvidenceHeading verdict={null} blocking={null} />
        <p className="empty-state">Security Agent 尚未生成 SecurityReport Artifact。</p>
      </section>
    )
  }

  const report = artifactJsonRecord(artifact)
  const verdict = readString(report, 'verdict')
  const blocking = readBoolean(report, 'blocking')
  const scanners = readRecordArray(report, 'scanners')
  const findings = readRecordArray(report, 'findings')
  const remainingRisks = readStringArray(report, 'remaining_risks')

  return (
    <section className="evidence-card" aria-labelledby="security-report-title">
      <EvidenceHeading verdict={verdict} blocking={blocking} />
      <p className="evidence-summary">{readString(report, 'summary') ?? artifact.summary}</p>
      <dl className="report-metric-grid">
        <div>
          <dt>扫描器</dt>
          <dd>{scanners.length}</dd>
        </div>
        <div>
          <dt>发现项</dt>
          <dd>{findings.length}</dd>
        </div>
        <div>
          <dt>剩余风险</dt>
          <dd>{remainingRisks.length}</dd>
        </div>
        <div>
          <dt>PR 阻断</dt>
          <dd>{blocking === null ? '—' : blocking ? '是' : '否'}</dd>
        </div>
      </dl>

      <CommandEvidenceList commands={scanners} emptyText="报告未记录扫描器命令证据。" />

      {report === null ? null : findings.length === 0 ? (
        <p className="evidence-callout tone-positive">当前报告没有安全发现项。</p>
      ) : (
        <details className="evidence-disclosure" open>
          <summary><span>Security findings</span><span>{findings.length}</span></summary>
          <div className="finding-list">
            {findings.map((finding, index) => {
              const severity = readString(finding, 'severity')
              const path = readString(finding, 'path')
              const line = readNumber(finding, 'line')
              return (
                <article key={`${readString(finding, 'id') ?? 'finding'}-${index}`}>
                  <div>
                    <strong>{readString(finding, 'rule_id') ?? `FINDING-${index + 1}`}</strong>
                    <span className={`evidence-status tone-${statusTone(severity)}`}>
                      {severity ?? 'unknown'}
                    </span>
                  </div>
                  <p>{readString(finding, 'message') ?? '未记录发现项说明。'}</p>
                  <small>
                    {readString(finding, 'scanner') ?? 'unknown scanner'} ·{' '}
                    {path === null ? '未关联文件或依赖' : `${path}${line === null ? '' : `:${line}`}`}
                  </small>
                </article>
              )
            })}
          </div>
        </details>
      )}

      {remainingRisks.length === 0 ? null : (
        <div className="evidence-callout tone-warning">
          <strong>剩余风险</strong>
          <ul>
            {remainingRisks.map((risk, index) => <li key={`${risk}-${index}`}>{risk}</li>)}
          </ul>
        </div>
      )}

      {report === null ? <RawPreview artifact={artifact} /> : null}
      {artifact.preview?.truncated === true ? (
        <p className="evidence-warning">安全报告预览已由服务端截断。</p>
      ) : null}
      <ArtifactEvidenceMeta artifact={artifact} />
    </section>
  )
}

function EvidenceHeading({
  verdict,
  blocking,
}: {
  verdict: string | null
  blocking: boolean | null
}) {
  const label = verdict === null
    ? '等待扫描'
    : blocking === true
      ? `${verdict} · blocking`
      : verdict
  return (
    <div className="evidence-card-heading">
      <div>
        <p className="eyebrow">安全门禁</p>
        <h3 id="security-report-title">Security Report</h3>
      </div>
      <span className={`evidence-status tone-${statusTone(blocking === true ? 'blocked' : verdict)}`}>
        {label}
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
