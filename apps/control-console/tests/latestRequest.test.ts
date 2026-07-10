import assert from 'node:assert/strict'
import test from 'node:test'

import { LatestRequestGate } from '../src/shared/api/latestRequest.ts'

test('只允许最后开始的请求更新状态', () => {
  const gate = new LatestRequestGate()
  const oldRequest = gate.begin()
  const currentRequest = gate.begin()

  assert.equal(gate.isCurrent(oldRequest), false)
  assert.equal(gate.isCurrent(currentRequest), true)
  gate.invalidate()
  assert.equal(gate.isCurrent(currentRequest), false)
})
