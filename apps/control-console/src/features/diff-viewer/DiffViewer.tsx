import { formatJson } from '../../shared/api/formatters'
import type {
  ArtifactDetailRead,
  PullRequestChangedFile,
  PullRequestRecordRead,
} from '../../shared/types/api'
import { ArtifactEvidenceMeta } from '../local-development/ArtifactEvidenceMeta'
import {
  artifactPreviewText,
  readRecordArray,
  readString,
} from '../local-development/evidenceViewModel'

interface DiffViewerProps {
  artifact: ArtifactDetailRead | null
  pullRequestRecord: PullRequestRecordRead | null
}

/**
 * 统一 patch Diff Viewer。
 *
 * changed files 优先使用 PR record 固化列表；PR 形成前回退到 diff Artifact
 * metadata。patch 以纯文本渲染，避免源码内容被解释为 HTML。
 */
export function DiffViewer({ artifact, pullRequestRecord }: DiffViewerProps) {
  if (artifact === null) {
    return (
      <section className="evidence-card evidence-card-wide" aria-labelledby="diff-viewer-title">
        <div className="evidence-card-heading">
          <div>
            <p className="eyebrow">代码证据</p>
            <h3 id="diff-viewer-title">Diff Viewer</h3>
          </div>
          <span className="evidence-status tone-neutral">等待 diff</span>
        </div>
        <p className="empty-state">Coder 尚未生成可读取的真实 patch Artifact。</p>
      </section>
    )
  }

  const preview = artifactPreviewText(artifact)
  const changedFiles = pullRequestRecord?.changed_files_json
    ?? metadataChangedFiles(artifact)

  return (
    <section className="evidence-card evidence-card-wide diff-viewer" aria-labelledby="diff-viewer-title">
      <div className="evidence-card-heading">
        <div>
          <p className="eyebrow">代码证据</p>
          <h3 id="diff-viewer-title">Diff Viewer</h3>
        </div>
        <span className={`evidence-status tone-${artifact.status === 'available' ? 'positive' : 'warning'}`}>
          {artifact.status}
        </span>
      </div>
      <p className="evidence-summary">{artifact.summary}</p>

      <details className="evidence-disclosure" open>
        <summary>
          <span>Changed files</span>
          <span>{changedFiles.length}</span>
        </summary>
        {changedFiles.length === 0 ? (
          <p className="empty-state">Artifact 未记录 changed files 摘要。</p>
        ) : (
          <ul className="changed-file-list">
            {changedFiles.map((file, index) => (
              <li key={`${file.path}-${index}`}>
                <code>{file.path}</code>
                <span>{typeof file.operation === 'string' ? file.operation : 'changed'}</span>
              </li>
            ))}
          </ul>
        )}
      </details>

      {pullRequestRecord === null ? null : (
        <details className="evidence-disclosure">
          <summary>
            <span>Diff stat</span>
            <span>{Object.keys(pullRequestRecord.diff_stat_json).length} 项</span>
          </summary>
          <pre>{formatJson(pullRequestRecord.diff_stat_json)}</pre>
        </details>
      )}

      <details className="evidence-disclosure diff-disclosure" open>
        <summary>
          <span>Unified patch</span>
          <span>{artifact.preview?.truncated === true ? '预览已截断' : artifact.media_type}</span>
        </summary>
        {preview === null ? (
          <p className="empty-state">该 Artifact 没有可展示的文本预览。</p>
        ) : (
          <pre className="diff-scroll">{preview}</pre>
        )}
      </details>
      {artifact.preview?.truncated === true ? (
        <p className="evidence-warning">
          当前仅展示服务端允许的前 {artifact.preview.bytes_returned.toLocaleString('zh-CN')} 字节。
        </p>
      ) : null}
      <ArtifactEvidenceMeta artifact={artifact} />
    </section>
  )
}

function metadataChangedFiles(artifact: ArtifactDetailRead): PullRequestChangedFile[] {
  return readRecordArray(artifact.metadata_json, 'changed_files').reduce<PullRequestChangedFile[]>(
    (files, item) => {
      const path = readString(item, 'path')
      if (path === null) {
        return files
      }
      const file: PullRequestChangedFile = { path }
      const operation = readString(item, 'operation')
      const intent = readString(item, 'intent')
      if (operation !== null) {
        file.operation = operation
      }
      if (intent !== null) {
        file.intent = intent
      }
      files.push(file)
      return files
    },
    [],
  )
}
