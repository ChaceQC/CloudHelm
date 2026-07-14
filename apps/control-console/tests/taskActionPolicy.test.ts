import assert from 'node:assert/strict'
import test from 'node:test'

import {
  canCancelTask,
  canPauseTask,
  canResumeTask,
  canRunNextOrchestration,
  canStartOrchestration,
  buildOrchestrationActionRequest,
} from '../src/features/tasks/taskActionPolicy.ts'

test('任务状态操作只在后端允许的状态启用', () => {
  assert.equal(canPauseTask('created'), true)
  assert.equal(canPauseTask('running'), true)
  assert.equal(canPauseTask('waiting_approval'), true)
  assert.equal(canPauseTask('paused'), false)

  assert.equal(canResumeTask('paused'), true)
  assert.equal(canResumeTask('running'), false)

  assert.equal(canCancelTask('failed'), false)
  assert.equal(canCancelTask('done'), false)
  assert.equal(canCancelTask('cancelled'), false)
  assert.equal(canCancelTask('running'), true)
})

test('编排按钮同时受任务状态和 next_action 约束', () => {
  assert.equal(canStartOrchestration('created', 'start'), true)
  assert.equal(canStartOrchestration('paused', 'start'), false)
  assert.equal(canStartOrchestration('running', 'run_requirement'), false)

  assert.equal(canRunNextOrchestration('running', 'run_requirement'), true)
  assert.equal(canRunNextOrchestration('running', 'resume_planning'), true)
  assert.equal(canRunNextOrchestration('running', 'wait_for_design_approval'), false)
  assert.equal(canRunNextOrchestration('running', 'unexpected_action'), false)
  assert.equal(canRunNextOrchestration('paused', 'run_requirement'), false)
  assert.equal(canRunNextOrchestration('failed', 'run_requirement'), false)
})

test('编排写请求携带当前 Task 阶段作为并发前置条件', () => {
  assert.deepEqual(
    buildOrchestrationActionRequest(
      'RequirementClarifying',
      '用户推进编排',
    ),
    {
      actor_id: 'control-console',
      reason: '用户推进编排',
      expected_phase: 'RequirementClarifying',
    },
  )
})
