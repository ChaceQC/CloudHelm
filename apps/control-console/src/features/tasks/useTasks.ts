import { useCallback, useEffect, useRef, useState } from 'react'
import { cancelTask, createTask, listTasks, pauseTask, resumeTask } from '../../shared/api/cloudhelmApi'
import { formatApiError } from '../../shared/api/formatters'
import { LatestRequestGate } from '../../shared/api/latestRequest'
import type { DecisionRequest, Task, TaskCreateInput } from '../../shared/types/api'

interface TasksState {
  projectId: string | null
  status: 'idle' | 'loading' | 'ready' | 'error'
  items: Task[]
  error: string | null
}

type TaskAction = 'pause' | 'resume' | 'cancel'

/**
 * Task Board 数据 Hook。
 *
 * Hook 仅按当前 Project 调用真实 Task API；项目为空时进入 idle，避免
 * 展示与当前项目无关的任务数据。
 */
export function useTasks(projectId: string | null) {
  const requestGate = useRef(new LatestRequestGate())
  const currentProjectId = useRef(projectId)
  currentProjectId.current = projectId
  const [state, setState] = useState<TasksState>({
    projectId: null,
    status: 'idle',
    items: [],
    error: null,
  })

  const refresh = useCallback(async () => {
    if (currentProjectId.current !== projectId) {
      return
    }
    const token = requestGate.current.begin()
    if (projectId === null) {
      setState({ projectId: null, status: 'idle', items: [], error: null })
      return
    }

    setState((current) => ({
      projectId,
      status: 'loading',
      items: current.projectId === projectId ? current.items : [],
      error: null,
    }))
    try {
      const response = await listTasks(projectId)
      if (!requestGate.current.isCurrent(token) || currentProjectId.current !== projectId) {
        return
      }
      setState({ projectId, status: 'ready', items: response.items, error: null })
    } catch (error) {
      if (requestGate.current.isCurrent(token) && currentProjectId.current === projectId) {
        setState({ projectId, status: 'error', items: [], error: formatApiError(error) })
      }
    }
  }, [projectId])

  const create = useCallback(
    async (payload: Omit<TaskCreateInput, 'project_id'>) => {
      if (projectId === null) {
        throw new Error('请先选择项目。')
      }

      const task = await createTask({ ...payload, project_id: projectId })
      await refresh()
      return task
    },
    [projectId, refresh],
  )

  const runAction = useCallback(
    async (taskId: string, action: TaskAction, payload: DecisionRequest) => {
      const actionMap = {
        pause: pauseTask,
        resume: resumeTask,
        cancel: cancelTask,
      }
      const task = await actionMap[action](taskId, payload)
      await refresh()
      return task
    },
    [refresh],
  )

  useEffect(() => {
    void refresh()
    return () => requestGate.current.invalidate()
  }, [refresh])

  const visibleState =
    state.projectId === projectId
      ? state
      : {
          projectId,
          status: projectId === null ? ('idle' as const) : ('loading' as const),
          items: [],
          error: null,
        }

  return {
    status: visibleState.status,
    items: visibleState.items,
    error: visibleState.error,
    createTask: create,
    runTaskAction: runAction,
    refresh,
  }
}
