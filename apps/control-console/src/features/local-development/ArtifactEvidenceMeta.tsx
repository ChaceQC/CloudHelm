import { formatDateTime } from '../../shared/api/formatters'
import type { ArtifactDetailRead } from '../../shared/types/api'
import { formatArtifactSize, shortSha } from './evidenceViewModel'

/**
 * Artifact 的统一审计摘要。
 */
export function ArtifactEvidenceMeta({ artifact }: { artifact: ArtifactDetailRead }) {
  return (
    <dl className="artifact-meta-grid">
      <div>
        <dt>Artifact</dt>
        <dd>{artifact.display_name}</dd>
      </div>
      <div>
        <dt>类型</dt>
        <dd>{artifact.artifact_type}</dd>
      </div>
      <div>
        <dt>生产者</dt>
        <dd>{artifact.producer_type}</dd>
      </div>
      <div>
        <dt>大小</dt>
        <dd>{formatArtifactSize(artifact.size_bytes)}</dd>
      </div>
      <div>
        <dt>SHA-256</dt>
        <dd title={artifact.sha256}>{shortSha(artifact.sha256.replace(/^sha256:/, ''))}</dd>
      </div>
      <div>
        <dt>创建时间</dt>
        <dd>{formatDateTime(artifact.created_at)}</dd>
      </div>
      <div className="wide">
        <dt>受控引用</dt>
        <dd>{artifact.uri}</dd>
      </div>
    </dl>
  )
}
