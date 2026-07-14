import assert from 'node:assert/strict'
import test from 'node:test'

import {
  canCommitTaskDetailRequest,
  visibleTaskDetailState,
} from '../src/features/tasks/taskDetailRequestPolicy.ts'
import { LatestRequestGate } from '../src/shared/api/latestRequest.ts'

interface Deferred<T> {
  promise: Promise<T>
  resolve: (value: T) => void
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((promiseResolve) => {
    resolve = promiseResolve
  })
  return { promise, resolve }
}

test('切换 Task 立即隐藏旧详情且迟到响应不能覆盖当前 Task', async () => {
  const gate = new LatestRequestGate()
  let currentTaskId: string | null = 'task-a'
  const oldState = {
    taskId: 'task-a',
    status: 'ready' as const,
    data: { id: 'task-a', approvalId: 'approval-a' },
    error: null,
    streamStatus: 'open' as const,
  }
  const oldRequest = {
    taskId: 'task-a',
    token: gate.begin(),
  }
  const oldResponse = deferred<{ id: string }>()

  currentTaskId = 'task-b'
  const visibleAfterSwitch = visibleTaskDetailState(
    oldState,
    currentTaskId,
  )
  assert.equal(visibleAfterSwitch.status, 'loading')
  assert.equal(visibleAfterSwitch.data, null)
  assert.equal(visibleAfterSwitch.streamStatus, 'idle')

  const currentRequest = {
    taskId: currentTaskId,
    token: gate.begin(),
  }
  const currentResponse = deferred<{ id: string }>()
  let committed: { id: string } | null = null

  const oldCompletion = oldResponse.promise.then((value) => {
    if (
      canCommitTaskDetailRequest(
        oldRequest,
        currentTaskId,
        gate,
      )
    ) {
      committed = value
    }
  })
  const currentCompletion = currentResponse.promise.then((value) => {
    if (
      canCommitTaskDetailRequest(
        currentRequest,
        currentTaskId,
        gate,
      )
    ) {
      committed = value
    }
  })

  oldResponse.resolve({ id: 'task-a' })
  await oldCompletion
  assert.equal(committed, null)

  currentResponse.resolve({ id: 'task-b' })
  await currentCompletion
  assert.deepEqual(committed, { id: 'task-b' })
})
