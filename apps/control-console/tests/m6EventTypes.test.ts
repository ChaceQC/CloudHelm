import assert from 'node:assert/strict'
import test from 'node:test'

import { TASK_EVENT_TYPES } from '../src/shared/types/events.ts'

const M6_EVENT_TYPES = [
  'LocalDevelopmentStarted',
  'ScaffoldCompleted',
  'CodePatchGenerated',
  'TestRunStarted',
  'TestRunPassed',
  'TestRunFailed',
  'ReviewCompleted',
  'SecurityScanCompleted',
  'SecurityScanBlocked',
  'ArtifactCreated',
  'BranchCreated',
  'CommitCreated',
  'PullRequestRecordCreated',
] as const

const M7_CANDIDATE_EVENT_TYPES = [
  'WorkflowJobQueued',
  'WorkflowJobStarted',
  'WorkflowJobSucceeded',
  'WorkflowJobFailed',
  'WorkflowJobRetryScheduled',
  'WorkflowJobCancelRequested',
  'WorkflowJobCancelled',
  'WorkflowJobRecoveryRequired',
  'WorkflowJobDispatchDeferred',
  'WorkflowJobExecutionDeferred',
  'ReleaseCandidateApprovalRequested',
  'ReleaseCandidateApproved',
  'ReleaseCandidateRejected',
  'ReleaseCandidateCancelled',
] as const

test('EventSource 显式监听全部 M6/M7 Workflow/Candidate 事件且列表无重复', () => {
  ;[...M6_EVENT_TYPES, ...M7_CANDIDATE_EVENT_TYPES].forEach((eventType) => {
    assert.equal(TASK_EVENT_TYPES.includes(eventType), true)
  })
  assert.equal(new Set(TASK_EVENT_TYPES).size, TASK_EVENT_TYPES.length)
})
