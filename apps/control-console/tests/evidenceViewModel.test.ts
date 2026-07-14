import assert from 'node:assert/strict'
import test from 'node:test'

import {
  artifactJsonRecord,
  formatArtifactSize,
  resolveEvidenceArtifactIds,
  safeExternalUrl,
  statusTone,
} from '../src/features/local-development/evidenceViewModel.ts'
import type {
  ArtifactDetailRead,
  ArtifactRead,
  LocalDevelopmentStateRead,
  PullRequestRecordRead,
} from '../src/shared/types/api.ts'

const baseArtifact = {
  task_id: 'task-1',
  agent_run_id: 'run-1',
  tool_call_id: null,
  producer_type: 'agent',
  status: 'available',
  display_name: 'report.json',
  media_type: 'application/json',
  uri: 'artifact://artifact',
  sha256: `sha256:${'a'.repeat(64)}`,
  size_bytes: 128,
  summary: '真实证据',
  metadata_json: {},
  updated_at: '2026-07-14T10:00:00Z',
} satisfies Omit<ArtifactRead, 'id' | 'artifact_type' | 'created_at'>

function artifact(id: string, artifactType: string, createdAt: string): ArtifactRead {
  return {
    ...baseArtifact,
    id,
    artifact_type: artifactType,
    created_at: createdAt,
  }
}

const workflowState: LocalDevelopmentStateRead = {
  task_id: 'task-1',
  current_phase: 'Testing',
  next_action: 'run_tester',
  development_plan_id: 'plan-1',
  active_agent_run_id: null,
  latest_artifact_ids: {
    diff_patch: 'state-diff',
    test_report: 'state-test',
  },
  latest_pull_request_record_id: null,
}

const pullRequestRecord: PullRequestRecordRead = {
  id: 'pr-1',
  task_id: 'task-1',
  project_id: 'project-1',
  development_plan_id: 'plan-1',
  created_by_agent_run_id: 'run-1',
  branch_tool_call_id: 'tool-branch',
  commit_tool_call_id: 'tool-commit',
  provider: 'local',
  status: 'open',
  title: '本地 PR',
  summary: '门禁通过',
  base_branch: 'main',
  head_branch: 'codex/task-1',
  base_commit_sha: 'a'.repeat(40),
  commit_sha: 'b'.repeat(40),
  changed_files_json: [{ path: 'src/main.py' }],
  diff_stat_json: { files_changed: 1 },
  diff_artifact_id: 'pr-diff',
  test_artifact_id: 'pr-test',
  review_artifact_id: 'pr-review',
  security_artifact_id: 'pr-security',
  url: null,
  created_at: '2026-07-14T12:00:00Z',
  updated_at: '2026-07-14T12:00:00Z',
}

test('PR record 固化引用优先于状态摘要和最新类型回退', () => {
  const resolved = resolveEvidenceArtifactIds(
    workflowState,
    [pullRequestRecord],
    [artifact('newer-test', 'test_report', '2026-07-14T13:00:00Z')],
  )
  assert.deepEqual(resolved, {
    diff: 'pr-diff',
    test: 'pr-test',
    review: 'pr-review',
    security: 'pr-security',
  })
})

test('闭环进行中按 state 引用并对缺失类型选择最新 Artifact', () => {
  const resolved = resolveEvidenceArtifactIds(
    workflowState,
    [],
    [
      artifact('old-review', 'review_report', '2026-07-14T09:00:00Z'),
      artifact('new-review', 'review_report', '2026-07-14T11:00:00Z'),
      artifact('security', 'security_report', '2026-07-14T10:30:00Z'),
    ],
  )
  assert.deepEqual(resolved, {
    diff: 'state-diff',
    test: 'state-test',
    review: 'new-review',
    security: 'security',
  })
})

test('Artifact JSON 预览和展示辅助函数保持稳定', () => {
  const detail = {
    ...artifact('test', 'test_report', '2026-07-14T10:00:00Z'),
    preview: {
      kind: 'json',
      text: null,
      json_value: { status: 'passed', passed_count: 3 },
      truncated: false,
      bytes_returned: 42,
    },
  } satisfies ArtifactDetailRead

  assert.deepEqual(artifactJsonRecord(detail), { status: 'passed', passed_count: 3 })
  assert.equal(statusTone('passed'), 'positive')
  assert.equal(statusTone('partial'), 'warning')
  assert.equal(statusTone('blocked'), 'negative')
  assert.equal(formatArtifactSize(1536), '1.5 KB')
  assert.equal(safeExternalUrl('https://example.com/pr/1'), 'https://example.com/pr/1')
  assert.equal(safeExternalUrl('file:///tmp/pr'), null)
})
