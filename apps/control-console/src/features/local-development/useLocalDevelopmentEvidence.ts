import { useCallback, useEffect, useRef, useState } from 'react'
import {
  getArtifactDetail,
  getLocalDevelopmentState,
  listArtifacts,
  listPullRequestRecords,
  runNextLocalDevelopment,
  startLocalDevelopment,
} from '../../shared/api/cloudhelmApi'
import { formatApiError } from '../../shared/api/formatters'
import { LatestRequestGate } from '../../shared/api/latestRequest'
import type {
  ArtifactDetailRead,
  ArtifactRead,
  LocalDevelopmentStateRead,
  LocalDevelopmentStepRead,
  PullRequestRecordRead,
} from '../../shared/types/api'
import { resolveEvidenceArtifactIds } from './evidenceViewModel'

export interface LocalDevelopmentEvidenceData {
  workflowState: LocalDevelopmentStateRead
  artifacts: ArtifactRead[]
  pullRequestRecords: PullRequestRecordRead[]
  artifactDetails: Record<string, ArtifactDetailRead>
}

interface LocalDevelopmentEvidenceState {
  taskId: string | null
  status: 'idle' | 'loading' | 'ready' | 'error'
  data: LocalDevelopmentEvidenceData | null
  error: string | null
  warning: string | null
}

/**
 * M6 本地开发状态与证据聚合 Hook。
 *
 * 基础列表并发读取；确定 PR record 或进行中状态引用后，再并发读取四类
 * Artifact 安全详情。失败的单个预览只形成 warning，其余真实证据仍可展示。
 */
export function useLocalDevelopmentEvidence(
  taskId: string | null,
  enabled: boolean,
  refreshKey: number,
  streamEventRevision: number,
  onWorkflowChanged?: () => void | Promise<void>,
) {
  const requestGate = useRef(new LatestRequestGate())
  const currentTaskId = useRef(taskId)
  currentTaskId.current = taskId
  const [state, setState] = useState<LocalDevelopmentEvidenceState>({
    taskId: null,
    status: 'idle',
    data: null,
    error: null,
    warning: null,
  })

  const refresh = useCallback(async () => {
    const token = requestGate.current.begin()
    if (taskId === null || !enabled) {
      setState({
        taskId,
        status: 'idle',
        data: null,
        error: null,
        warning: null,
      })
      return
    }

    setState((current) => ({
      taskId,
      status: 'loading',
      data: current.taskId === taskId ? current.data : null,
      error: null,
      warning: null,
    }))

    try {
      const [workflowState, artifactPage, pullRequestPage] = await Promise.all([
        getLocalDevelopmentState(taskId),
        listArtifacts(taskId),
        listPullRequestRecords(taskId),
      ])
      if (!requestGate.current.isCurrent(token) || currentTaskId.current !== taskId) {
        return
      }

      const artifactIds = resolveEvidenceArtifactIds(
        workflowState,
        pullRequestPage.items,
        artifactPage.items,
      )
      const uniqueArtifactIds = [...new Set(Object.values(artifactIds).filter(
        (id): id is string => id !== null,
      ))]
      const detailResults = await Promise.allSettled(
        uniqueArtifactIds.map(async (artifactId) => ({
          artifactId,
          detail: await getArtifactDetail(artifactId),
        })),
      )
      if (!requestGate.current.isCurrent(token) || currentTaskId.current !== taskId) {
        return
      }

      const artifactDetails: Record<string, ArtifactDetailRead> = {}
      const detailErrors: string[] = []
      detailResults.forEach((result) => {
        if (result.status === 'fulfilled') {
          artifactDetails[result.value.artifactId] = result.value.detail
        } else {
          detailErrors.push(formatApiError(result.reason))
        }
      })

      setState({
        taskId,
        status: 'ready',
        data: {
          workflowState,
          artifacts: artifactPage.items,
          pullRequestRecords: pullRequestPage.items,
          artifactDetails,
        },
        error: null,
        warning:
          detailErrors.length === 0
            ? null
            : `有 ${detailErrors.length} 个 Artifact 预览读取失败：${detailErrors.join('；')}`,
      })
    } catch (error) {
      if (requestGate.current.isCurrent(token) && currentTaskId.current === taskId) {
        setState({
          taskId,
          status: 'error',
          data: null,
          error: formatApiError(error),
          warning: null,
        })
      }
    }
  }, [enabled, taskId])

  const notifyAndRefresh = useCallback(async () => {
    const callbacks: Promise<unknown>[] = [refresh()]
    if (onWorkflowChanged !== undefined) {
      callbacks.push(Promise.resolve(onWorkflowChanged()))
    }
    await Promise.all(callbacks)
  }, [onWorkflowChanged, refresh])

  const start = useCallback(async (): Promise<LocalDevelopmentStepRead> => {
    if (taskId === null) {
      throw new Error('请先选择任务。')
    }
    const result = await startLocalDevelopment(taskId, {
      actor_id: 'control-console',
      reason: '用户在控制台启动 M6 本地开发闭环',
    })
    await notifyAndRefresh()
    return result
  }, [notifyAndRefresh, taskId])

  const runNext = useCallback(async (): Promise<LocalDevelopmentStepRead> => {
    if (taskId === null) {
      throw new Error('请先选择任务。')
    }
    const result = await runNextLocalDevelopment(taskId, {
      actor_id: 'control-console',
      reason: '用户在控制台推进一个 M6 本地开发步骤',
    })
    await notifyAndRefresh()
    return result
  }, [notifyAndRefresh, taskId])

  useEffect(() => {
    void refresh()
    return () => requestGate.current.invalidate()
  }, [refresh, refreshKey, streamEventRevision])

  return {
    ...state,
    refresh,
    start,
    runNext,
  }
}
