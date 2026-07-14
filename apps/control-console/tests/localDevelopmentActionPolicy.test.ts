import assert from 'node:assert/strict'
import test from 'node:test'

import {
  canRunNextLocalDevelopment,
  canStartLocalDevelopment,
} from '../src/features/local-development/localDevelopmentActionPolicy.ts'

test('M6 启动操作同时受任务状态、next_action 和 active AgentRun 约束', () => {
  assert.equal(canStartLocalDevelopment('running', 'start_local_development', null), true)
  assert.equal(canStartLocalDevelopment('paused', 'start_local_development', null), false)
  assert.equal(canStartLocalDevelopment('running', 'run_coder', null), false)
  assert.equal(canStartLocalDevelopment('running', 'start_local_development', 'run-1'), false)
})

test('M6 run-next 只允许已声明的单步动作', () => {
  assert.equal(canRunNextLocalDevelopment('running', 'run_scaffold', null), true)
  assert.equal(canRunNextLocalDevelopment('running', 'run_coder', null), true)
  assert.equal(canRunNextLocalDevelopment('running', 'run_tester', null), true)
  assert.equal(canRunNextLocalDevelopment('running', 'run_reviewer', null), true)
  assert.equal(canRunNextLocalDevelopment('running', 'run_security', null), true)
  assert.equal(canRunNextLocalDevelopment('running', 'finalize_local_pull_request', null), true)
  assert.equal(canRunNextLocalDevelopment('running', 'stop', null), false)
  assert.equal(canRunNextLocalDevelopment('cancelled', 'run_coder', null), false)
  assert.equal(canRunNextLocalDevelopment('running', 'run_coder', 'run-1'), false)
})
