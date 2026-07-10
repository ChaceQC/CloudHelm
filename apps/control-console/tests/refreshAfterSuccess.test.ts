import assert from 'node:assert/strict'
import test from 'node:test'

import { refreshAfterSuccess } from '../src/features/tasks/refreshAfterSuccess.ts'

test('异步决策成功后返回原结果并刷新任务列表', async () => {
  let refreshCount = 0
  const result = await refreshAfterSuccess(
    async (value: number) => ({ value }),
    () => {
      refreshCount += 1
    },
    42,
  )

  assert.deepEqual(result, { value: 42 })
  assert.equal(refreshCount, 1)
})

test('异步决策失败时不触发任务列表刷新', async () => {
  let refreshCount = 0
  const expected = new Error('decision failed')

  await assert.rejects(
    refreshAfterSuccess(
      async () => {
        throw expected
      },
      () => {
        refreshCount += 1
      },
    ),
    expected,
  )
  assert.equal(refreshCount, 0)
})
