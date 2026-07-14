import { DiffViewer } from '../diff-viewer/DiffViewer'
import { PullRequestRecordPanel } from '../pull-requests/PullRequestRecordPanel'
import { ReviewReportPanel } from '../review-reports/ReviewReportPanel'
import { SecurityReportPanel } from '../security-reports/SecurityReportPanel'
import { TestReportPanel } from '../test-reports/TestReportPanel'
import type { LocalDevelopmentEvidenceData } from './useLocalDevelopmentEvidence'
import {
  artifactDetailById,
  resolveEvidenceArtifactIds,
  selectLatestPullRequestRecord,
} from './evidenceViewModel'

interface LocalDevelopmentEvidenceProps {
  enabled: boolean
  status: 'idle' | 'loading' | 'ready' | 'error'
  data: LocalDevelopmentEvidenceData | null
  error: string | null
  warning: string | null
  onRetry: () => void
}

/**
 * M6 diff、测试、Review、安全和 PR record 的统一阅读流。
 */
export function LocalDevelopmentEvidence({
  enabled,
  status,
  data,
  error,
  warning,
  onRetry,
}: LocalDevelopmentEvidenceProps) {
  if (!enabled) {
    return (
      <section className="sub-panel evidence-workspace" aria-labelledby="development-evidence-title">
        <EvidenceWorkspaceHeading status="等待计划审批" />
        <p className="empty-state">
          最新 DevelopmentPlan 审批通过后，可在此启动 M6 并查看真实开发证据。
        </p>
      </section>
    )
  }

  if (status === 'loading' && data === null) {
    return (
      <section className="sub-panel evidence-workspace" aria-labelledby="development-evidence-title">
        <EvidenceWorkspaceHeading status="读取中" />
        <p className="status-line">正在读取本地开发状态、Artifact 和 PR record...</p>
      </section>
    )
  }

  if (status === 'error' && data === null) {
    return (
      <section className="sub-panel evidence-workspace" aria-labelledby="development-evidence-title">
        <EvidenceWorkspaceHeading status="读取失败" />
        <div className="status-error" role="alert">
          <strong>M6 开发证据加载失败</strong>
          <p>{error}</p>
          <button type="button" onClick={onRetry}>重新加载</button>
        </div>
      </section>
    )
  }

  if (data === null) {
    return null
  }

  const record = selectLatestPullRequestRecord(data.pullRequestRecords)
  const artifactIds = resolveEvidenceArtifactIds(
    data.workflowState,
    data.pullRequestRecords,
    data.artifacts,
  )
  const diffArtifact = artifactDetailById(data.artifactDetails, artifactIds.diff)
  const testArtifact = artifactDetailById(data.artifactDetails, artifactIds.test)
  const reviewArtifact = artifactDetailById(data.artifactDetails, artifactIds.review)
  const securityArtifact = artifactDetailById(data.artifactDetails, artifactIds.security)

  return (
    <section className="sub-panel evidence-workspace" aria-labelledby="development-evidence-title">
      <EvidenceWorkspaceHeading
        status={status === 'loading' ? '同步中' : data.workflowState.current_phase}
      />
      <p className="muted">
        以下内容来自 Platform API 持久化的真实 Artifact 与本地 Git record；重试后的门禁证据按同一 PR record 引用配对。
      </p>
      {warning === null ? null : <p className="evidence-warning" role="status">{warning}</p>}

      <div className="evidence-grid">
        <PullRequestRecordPanel record={record} />
        <DiffViewer artifact={diffArtifact} pullRequestRecord={record} />
        <TestReportPanel artifact={testArtifact} />
        <ReviewReportPanel artifact={reviewArtifact} />
        <SecurityReportPanel artifact={securityArtifact} />
      </div>
    </section>
  )
}

function EvidenceWorkspaceHeading({ status }: { status: string }) {
  return (
    <div className="inline-heading evidence-workspace-heading">
      <div>
        <p className="eyebrow">可审计交付物</p>
        <h3 id="development-evidence-title">Development Evidence</h3>
      </div>
      <span className="stream-chip">{status}</span>
    </div>
  )
}
