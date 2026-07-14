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
import { LatestRequestGate } from '../../shared/api/latestRequest'
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
import { buildOrchestrationActionRequest } from './taskActionPolicy'
import {
  canCommitTaskDetailRequest,
  createEmptyTaskDetailState,
  visibleTaskDetailState,
} from './taskDetailRequestPolicy'

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

/**
 * Task Detail 聚合 Hook。
 *
 * 详情页需要读取多个互不依赖的 M2-M6 真实接口；使用 `Promise.all` 并发
 * 请求，避免串行瀑布。审批和评审动作完成后重新读取详情，保证界面与
 * 数据库状态一致。
 */
export function useTaskDetail(
  taskId: string | null,
  refreshKey = 0,
  onTaskChanged?: () => void | Promise<void>,
) {
  const [state, setState] = useState(() =>
    createEmptyTaskDetailState<TaskDetailData>(taskId),
  )
  const requestGate = useRef(new LatestRequestGate())
  const currentTaskId = useRef(taskId)
  currentTaskId.current = taskId
  const streamRefreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [streamEventRevision, setStreamEventRevision] = useState(0)
  const currentPhase =
    state.taskId === taskId
      ? state.data?.task.current_phase ?? null
      : null

  const refresh = useCallback(async () => {
    if (currentTaskId.current !== taskId) {
      return
    }
    const request = {
      taskId,
      token: requestGate.current.begin(),
    }
    if (taskId === null) {
      setState(createEmptyTaskDetailState<TaskDetailData>(null))
      return
    }

    setState((current) =>
      current.taskId === taskId
        ? { ...current, status: 'loading', error: null }
        : createEmptyTaskDetailState<TaskDetailData>(taskId),
    )
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
      if (
        !canCommitTaskDetailRequest(
          request,
          currentTaskId.current,
          requestGate.current,
        )
      ) {
        return
      }
      setState((current) => ({
        ...current,
        taskId,
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
      if (
        canCommitTaskDetailRequest(
          request,
          currentTaskId.current,
          requestGate.current,
        )
      ) {
        setState((current) => ({
          ...current,
          taskId,
          status: 'error',
          data: null,
          error: formatApiError(error),
        }))
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
    if (currentPhase === null) {
      throw new Error('任务阶段尚未加载，请刷新后再启动编排。')
    }
    const result = await startTaskOrchestration(
      taskId,
      buildOrchestrationActionRequest(
        currentPhase,
        '用户在控制台启动 M4 编排',
      ),
    )
    await refresh()
    return result
  }, [currentPhase, refresh, taskId])

  const runNextOrchestration = useCallback(async (): Promise<OrchestrationStepResult> => {
    if (taskId === null) {
      throw new Error('未选择任务，无法推进编排。')
    }
    if (currentPhase === null) {
      throw new Error('任务阶段尚未加载，请刷新后再推进编排。')
    }
    const result = await runNextTaskOrchestration(
      taskId,
      buildOrchestrationActionRequest(
        currentPhase,
        '用户在控制台推进 M4 编排',
      ),
    )
    await refresh()
    return result
  }, [currentPhase, refresh, taskId])

  useEffect(() => {
    void refresh()
    return () => requestGate.current.invalidate()
  }, [refresh, refreshKey])

  useEffect(() => {
    setStreamEventRevision(0)
  }, [taskId])

  useEffect(() => {
    if (taskId === null) {
      return undefined
    }

    const scheduleRefresh = () => {
      if (currentTaskId.current !== taskId) {
        return
      }
      if (streamRefreshTimer.current !== null) {
        clearTimeout(streamRefreshTimer.current)
      }
      streamRefreshTimer.current = setTimeout(() => {
        streamRefreshTimer.current = null
        if (currentTaskId.current !== taskId) {
          return
        }
        void refresh()
        if (onTaskChanged !== undefined) {
          void onTaskChanged()
        }
      }, 150)
    }
    const closeStream = openTaskEventStream(taskId, {
      onEvent: () => {
        if (currentTaskId.current !== taskId) {
          return
        }
        setStreamEventRevision((current) => current + 1)
        scheduleRefresh()
      },
      onStatus: (streamStatus) => {
        if (currentTaskId.current !== taskId) {
          return
        }
        setState((current) =>
          current.taskId === taskId
            ? { ...current, streamStatus }
            : current,
        )
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

  const visibleState = visibleTaskDetailState(state, taskId)

  return {
    ...visibleState,
    refresh,
    decideRequirement,
    decideDesign,
    decideApproval,
    startOrchestration,
    runNextOrchestration,
    streamEventRevision:
      visibleState.taskId === state.taskId ? streamEventRevision : 0,
  }
}
