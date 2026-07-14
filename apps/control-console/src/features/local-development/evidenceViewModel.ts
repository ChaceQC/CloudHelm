import type {
  ArtifactDetailRead,
  ArtifactRead,
  JsonValue,
  LocalDevelopmentStateRead,
  PullRequestRecordRead,
} from '../../shared/types/api'

export interface EvidenceArtifactIds {
  diff: string | null
  test: string | null
  review: string | null
  security: string | null
}

export type EvidenceTone = 'positive' | 'warning' | 'negative' | 'neutral'
export type JsonRecord = Record<string, JsonValue>

/**
 * 解析当前闭环应展示的四类门禁 Artifact。
 *
 * 已形成 PR record 时始终使用 record 固化的引用，避免把重试后的新 diff 与
 * 旧测试、Review 或安全报告错误拼接。闭环进行中才回退到状态摘要或最新产物。
 */
export function resolveEvidenceArtifactIds(
  state: LocalDevelopmentStateRead | null,
  records: PullRequestRecordRead[],
  artifacts: ArtifactRead[],
): EvidenceArtifactIds {
  const record = selectLatestPullRequestRecord(records)
  if (record !== null) {
    return {
      diff: record.diff_artifact_id,
      test: record.test_artifact_id,
      review: record.review_artifact_id,
      security: record.security_artifact_id,
    }
  }

  return {
    diff:
      state?.latest_artifact_ids.diff_patch
      ?? state?.latest_artifact_ids.format_patch
      ?? latestArtifactId(artifacts, ['diff_patch', 'format_patch']),
    test:
      state?.latest_artifact_ids.test_report
      ?? latestArtifactId(artifacts, ['test_report']),
    review:
      state?.latest_artifact_ids.review_report
      ?? latestArtifactId(artifacts, ['review_report']),
    security:
      state?.latest_artifact_ids.security_report
      ?? latestArtifactId(artifacts, ['security_report']),
  }
}

export function selectLatestPullRequestRecord(
  records: PullRequestRecordRead[],
): PullRequestRecordRead | null {
  if (records.length === 0) {
    return null
  }
  return [...records].sort(
    (left, right) => Date.parse(right.created_at) - Date.parse(left.created_at),
  )[0]
}

export function artifactDetailById(
  details: Record<string, ArtifactDetailRead>,
  id: string | null,
): ArtifactDetailRead | null {
  return id === null ? null : details[id] ?? null
}

export function artifactJsonRecord(
  artifact: ArtifactDetailRead | null,
): JsonRecord | null {
  if (artifact?.preview?.kind !== 'json') {
    return null
  }
  return asJsonRecord(artifact.preview.json_value)
}

export function artifactPreviewText(
  artifact: ArtifactDetailRead | null,
): string | null {
  if (artifact?.preview === null || artifact?.preview === undefined) {
    return null
  }
  if (artifact.preview.kind === 'text') {
    return artifact.preview.text
  }
  try {
    return JSON.stringify(artifact.preview.json_value, null, 2)
  } catch {
    return String(artifact.preview.json_value)
  }
}

export function asJsonRecord(value: JsonValue | undefined): JsonRecord | null {
  return value !== null && value !== undefined && typeof value === 'object' && !Array.isArray(value)
    ? value as JsonRecord
    : null
}

export function readString(record: JsonRecord | null, key: string): string | null {
  const value = record?.[key]
  return typeof value === 'string' ? value : null
}

export function readNumber(record: JsonRecord | null, key: string): number | null {
  const value = record?.[key]
  return typeof value === 'number' ? value : null
}

export function readBoolean(record: JsonRecord | null, key: string): boolean | null {
  const value = record?.[key]
  return typeof value === 'boolean' ? value : null
}

export function readStringArray(record: JsonRecord | null, key: string): string[] {
  const value = record?.[key]
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string')
    : []
}

export function readRecordArray(record: JsonRecord | null, key: string): JsonRecord[] {
  const value = record?.[key]
  return Array.isArray(value)
    ? value.map((item) => asJsonRecord(item)).filter((item): item is JsonRecord => item !== null)
    : []
}

export function statusTone(status: string | null): EvidenceTone {
  if (status === null) {
    return 'neutral'
  }
  if (['passed', 'approved', 'satisfied', 'completed', 'succeeded', 'available', 'open'].includes(status)) {
    return 'positive'
  }
  if (['partial', 'missing', 'changes_requested', 'waiting_approval', 'superseded'].includes(status)) {
    return 'warning'
  }
  if (['failed', 'blocked', 'critical', 'high', 'invalidated', 'closed'].includes(status)) {
    return 'negative'
  }
  return 'neutral'
}

export function formatArtifactSize(sizeBytes: number): string {
  if (sizeBytes < 1024) {
    return `${sizeBytes} B`
  }
  if (sizeBytes < 1024 * 1024) {
    return `${(sizeBytes / 1024).toFixed(1)} KB`
  }
  return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`
}

export function formatDuration(durationMs: number | null): string {
  if (durationMs === null) {
    return '未记录'
  }
  return durationMs < 1000
    ? `${durationMs} ms`
    : `${(durationMs / 1000).toFixed(2)} s`
}

export function shortSha(value: string): string {
  return value.length <= 12 ? value : value.slice(0, 12)
}

export function safeExternalUrl(value: string | null): string | null {
  if (value === null) {
    return null
  }
  try {
    const url = new URL(value)
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.toString() : null
  } catch {
    return null
  }
}

function latestArtifactId(
  artifacts: ArtifactRead[],
  artifactTypes: string[],
): string | null {
  const types = new Set(artifactTypes)
  const matching = artifacts.filter(
    (artifact) => artifact.status === 'available' && types.has(artifact.artifact_type),
  )
  if (matching.length === 0) {
    return null
  }
  return [...matching].sort(
    (left, right) => Date.parse(right.created_at) - Date.parse(left.created_at),
  )[0].id
}
