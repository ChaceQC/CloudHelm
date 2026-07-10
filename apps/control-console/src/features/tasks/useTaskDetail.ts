import { useCallback, useEffect, useRef, useState } from 'react'
import {
  approveApproval,
  approveRequirement,
  approveTechnicalDesign,
  getTask,
  getTimeline,
  getOrchestrationState,
  listAgentRuns,
  listApprovals,
  listDevelopmentPlans,
  listRequirements,
  listTechnicalDesigns,
  listToolCalls,
  openTaskEventStream,
  rejectApproval,
  requestRequirementChanges,
  requestTechnicalDesignChanges,
  runNextTaskOrchestration,
  startTaskOrchestration,
} from '../../shared/api/cloudhelmApi'
import { formatApiError } from '../../shared/api/formatters'
import type {
  AgentRun,
  ApprovalRequest,
  DevelopmentPlan,
  DecisionRequest,
  EventLog,
  OrchestrationState,
  OrchestrationStepResult,
  RequirementSpec,
  Task,
  TechnicalDesign,
  ToolCall,
} from '../../shared/types/api'

interface TaskDetailData {
  task: Task
  requirements: RequirementSpec[]
  designs: TechnicalDesign[]
  developmentPlans: DevelopmentPlan[]
  agentRuns: AgentRun[]
  toolCalls: ToolCall[]
  approvals: ApprovalRequest[]
  timeline: EventLog[]
  orchestration: OrchestrationState | null
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
 * 详情页需要读取多个互不依赖的 M2-M4 真实接口；使用 `Promise.all` 并发
 * 请求，避免串行瀑布。审批和评审动作完成后重新读取详情，保证界面与
 * 数据库状态一致。
 */
export function useTaskDetail(
  taskId: string | null,
  refreshKey = 0,
  onTaskChanged?: () => void | Promise<void>,
) {
  const [state, setState] = useState<TaskDetailState>({
    status: 'idle',
    data: null,
    error: null,
    streamStatus: 'idle',
  })
  const requestSequence = useRef(0)
  const streamRefreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const refresh = useCallback(async () => {
    const sequence = requestSequence.current + 1
    requestSequence.current = sequence
    if (taskId === null) {
      setState({ status: 'idle', data: null, error: null, streamStatus: 'idle' })
      return
    }

    setState((current) => ({ ...current, status: 'loading', data: null, error: null }))
    try {
      const [task, requirements, designs, developmentPlans, agentRuns, toolCalls, approvals, timeline, orchestration] =
        await Promise.all([
          getTask(taskId),
          listRequirements(taskId),
          listTechnicalDesigns(taskId),
          listDevelopmentPlans(taskId),
          listAgentRuns(taskId),
          listToolCalls(taskId),
          listApprovals(taskId),
          getTimeline(taskId),
          getOrchestrationState(taskId),
        ])
      if (requestSequence.current !== sequence) {
        return
      }
      setState((current) => ({
        ...current,
        status: 'ready',
        data: {
          task,
          requirements: requirements.items,
          designs: designs.items,
          developmentPlans: developmentPlans.items,
          agentRuns: agentRuns.items,
          toolCalls: toolCalls.items,
          approvals: approvals.items,
          timeline: timeline.items,
          orchestration,
        },
        error: null,
      }))
    } catch (error) {
      if (requestSequence.current === sequence) {
        setState((current) => ({ ...current, status: 'error', data: null, error: formatApiError(error) }))
      }
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

  const startOrchestration = useCallback(async (): Promise<OrchestrationStepResult> => {
    if (taskId === null) {
      throw new Error('未选择任务，无法启动编排。')
    }
    const result = await startTaskOrchestration(taskId, {
      actor_id: 'control-console',
      reason: '用户在控制台启动 M4 编排',
    })
    await refresh()
    return result
  }, [refresh, taskId])

  const runNextOrchestration = useCallback(async (): Promise<OrchestrationStepResult> => {
    if (taskId === null) {
      throw new Error('未选择任务，无法推进编排。')
    }
    const result = await runNextTaskOrchestration(taskId, {
      actor_id: 'control-console',
      reason: '用户在控制台推进 M4 编排',
    })
    await refresh()
    return result
  }, [refresh, taskId])

  useEffect(() => {
    void refresh()
  }, [refresh, refreshKey])

  useEffect(() => {
    if (taskId === null) {
      return undefined
    }

    const scheduleRefresh = () => {
      if (streamRefreshTimer.current !== null) {
        clearTimeout(streamRefreshTimer.current)
      }
      streamRefreshTimer.current = setTimeout(() => {
        streamRefreshTimer.current = null
        void refresh()
        if (onTaskChanged !== undefined) {
          void onTaskChanged()
        }
      }, 150)
    }
    const closeStream = openTaskEventStream(taskId, {
      onEvent: scheduleRefresh,
      onStatus: (streamStatus) => {
        setState((current) => ({ ...current, streamStatus }))
      },
    })
    return () => {
      closeStream()
      if (streamRefreshTimer.current !== null) {
        clearTimeout(streamRefreshTimer.current)
        streamRefreshTimer.current = null
      }
    }
  }, [onTaskChanged, refresh, taskId])

  return {
    ...state,
    refresh,
    decideRequirement,
    decideDesign,
    decideApproval,
    startOrchestration,
    runNextOrchestration,
  }
}
