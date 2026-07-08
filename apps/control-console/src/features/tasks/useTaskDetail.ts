import { useCallback, useEffect, useState } from 'react'
import {
  approveApproval,
  approveRequirement,
  approveTechnicalDesign,
  getTask,
  getTimeline,
  listAgentRuns,
  listApprovals,
  listRequirements,
  listTechnicalDesigns,
  listToolCalls,
  openTaskEventStream,
  rejectApproval,
  requestRequirementChanges,
  requestTechnicalDesignChanges,
} from '../../shared/api/cloudhelmApi'
import { formatApiError } from '../../shared/api/formatters'
import type {
  AgentRun,
  ApprovalRequest,
  DecisionRequest,
  EventLog,
  RequirementSpec,
  Task,
  TechnicalDesign,
  ToolCall,
} from '../../shared/types/api'

interface TaskDetailData {
  task: Task
  requirements: RequirementSpec[]
  designs: TechnicalDesign[]
  agentRuns: AgentRun[]
  toolCalls: ToolCall[]
  approvals: ApprovalRequest[]
  timeline: EventLog[]
}

interface TaskDetailState {
  status: 'idle' | 'loading' | 'ready' | 'error'
  data: TaskDetailData | null
  error: string | null
  streamStatus: 'idle' | 'connecting' | 'open' | 'closed' | 'error'
}

/**
 * Task Detail 聚合 Hook。
 *
 * 详情页需要读取多个互不依赖的 M2 真实接口；使用 `Promise.all` 并发
 * 请求，避免串行瀑布。审批和评审动作完成后重新读取详情，保证界面与
 * 数据库状态一致。
 */
export function useTaskDetail(taskId: string | null, refreshKey = 0) {
  const [state, setState] = useState<TaskDetailState>({
    status: 'idle',
    data: null,
    error: null,
    streamStatus: 'idle',
  })

  const refresh = useCallback(async () => {
    if (taskId === null) {
      setState({ status: 'idle', data: null, error: null, streamStatus: 'idle' })
      return
    }

    setState((current) => ({ ...current, status: 'loading', error: null }))
    try {
      const [task, requirements, designs, agentRuns, toolCalls, approvals, timeline] = await Promise.all([
        getTask(taskId),
        listRequirements(taskId),
        listTechnicalDesigns(taskId),
        listAgentRuns(taskId),
        listToolCalls(taskId),
        listApprovals(),
        getTimeline(taskId),
      ])
      setState((current) => ({
        ...current,
        status: 'ready',
        data: {
          task,
          requirements: requirements.items,
          designs: designs.items,
          agentRuns: agentRuns.items,
          toolCalls: toolCalls.items,
          approvals: approvals.items.filter((approval) => approval.task_id === taskId),
          timeline: timeline.items,
        },
        error: null,
      }))
    } catch (error) {
      setState((current) => ({ ...current, status: 'error', data: null, error: formatApiError(error) }))
    }
  }, [taskId])

  const decideRequirement = useCallback(
    async (requirementId: string, action: 'approve' | 'request-changes', payload: DecisionRequest) => {
      const result =
        action === 'approve'
          ? await approveRequirement(requirementId, payload)
          : await requestRequirementChanges(requirementId, payload)
      await refresh()
      return result
    },
    [refresh],
  )

  const decideDesign = useCallback(
    async (designId: string, action: 'approve' | 'request-changes', payload: DecisionRequest) => {
      const result =
        action === 'approve'
          ? await approveTechnicalDesign(designId, payload)
          : await requestTechnicalDesignChanges(designId, payload)
      await refresh()
      return result
    },
    [refresh],
  )

  const decideApproval = useCallback(
    async (approvalId: string, action: 'approve' | 'reject', payload: DecisionRequest) => {
      const result = action === 'approve' ? await approveApproval(approvalId, payload) : await rejectApproval(approvalId, payload)
      await refresh()
      return result
    },
    [refresh],
  )

  useEffect(() => {
    void refresh()
  }, [refresh, refreshKey])

  useEffect(() => {
    if (taskId === null) {
      return undefined
    }

    return openTaskEventStream(taskId, {
      onEvent: () => {
        void refresh()
      },
      onStatus: (streamStatus) => {
        setState((current) => ({ ...current, streamStatus }))
      },
    })
  }, [refresh, taskId])

  return {
    ...state,
    refresh,
    decideRequirement,
    decideDesign,
    decideApproval,
  }
}
