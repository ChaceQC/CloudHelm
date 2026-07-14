import type { AgentRun } from '../../shared/types/api'

/**
 * 按真实开始时间排列 AgentRun。
 *
 * 失败或取消的运行不会提交 conversation turn；若仅按 turn 排序，它们会被
 * 推到所有成功轮次之后，从而破坏审计时间顺序。开始时间相同时再使用 turn
 * 和 ID 提供稳定排序。
 */
export function orderAgentRunsForTimeline(agentRuns: AgentRun[]): AgentRun[] {
  return [...agentRuns].sort((left, right) => {
    const startedAtDifference = sortableTime(left.started_at) - sortableTime(right.started_at)
    if (startedAtDifference !== 0) {
      return startedAtDifference
    }

    const leftTurn = left.conversation_turn ?? Number.MAX_SAFE_INTEGER
    const rightTurn = right.conversation_turn ?? Number.MAX_SAFE_INTEGER
    const turnDifference = leftTurn - rightTurn
    if (turnDifference !== 0) {
      return turnDifference
    }
    return left.id.localeCompare(right.id)
  })
}

function sortableTime(value: string): number {
  /** 无效时间属于异常数据，稳定放到已知时间之后而不是打乱现有证据。 */

  const timestamp = Date.parse(value)
  return Number.isNaN(timestamp) ? Number.MAX_SAFE_INTEGER : timestamp
}
