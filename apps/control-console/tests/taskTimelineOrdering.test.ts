import assert from 'node:assert/strict'
import test from 'node:test'

import { orderAgentRunsForTimeline } from '../src/features/tasks/taskTimelineOrdering.ts'
import type { AgentRun } from '../src/shared/types/api.ts'

function run(
  id: string,
  startedAt: string,
  conversationTurn: number | null,
): AgentRun {
  return {
    id,
    started_at: startedAt,
    conversation_turn: conversationTurn,
  } as AgentRun
}

test('无 conversation turn 的失败运行仍按真实开始时间插入时间线', () => {
  const firstTurn = run('turn-1', '2026-07-14T01:00:00Z', 1)
  const failedRun = run('failed', '2026-07-14T01:01:00Z', null)
  const secondTurn = run('turn-2', '2026-07-14T01:02:00Z', 2)
  const source = [secondTurn, firstTurn, failedRun]

  const ordered = orderAgentRunsForTimeline(source)

  assert.deepEqual(
    ordered.map((item) => item.id),
    ['turn-1', 'failed', 'turn-2'],
  )
  assert.deepEqual(
    source.map((item) => item.id),
    ['turn-2', 'turn-1', 'failed'],
  )
})

test('开始时间相同时使用 conversation turn 和 ID 保持稳定顺序', () => {
  const startedAt = '2026-07-14T02:00:00Z'
  const ordered = orderAgentRunsForTimeline([
    run('no-turn', startedAt, null),
    run('turn-2', startedAt, 2),
    run('turn-1-b', startedAt, 1),
    run('turn-1-a', startedAt, 1),
  ])

  assert.deepEqual(
    ordered.map((item) => item.id),
    ['turn-1-a', 'turn-1-b', 'turn-2', 'no-turn'],
  )
})
