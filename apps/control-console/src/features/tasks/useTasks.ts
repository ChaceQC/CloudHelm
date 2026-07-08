import { useCallback, useEffect, useState } from 'react'
import { cancelTask, createTask, listTasks, pauseTask, resumeTask } from '../../shared/api/cloudhelmApi'
import { formatApiError } from '../../shared/api/formatters'
import type { DecisionRequest, Task, TaskCreateInput } from '../../shared/types/api'

interface TasksState {
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
  const [state, setState] = useState<TasksState>({
    status: 'idle',
    items: [],
    error: null,
  })

  const refresh = useCallback(async () => {
    if (projectId === null) {
      setState({ status: 'idle', items: [], error: null })
      return
    }

    setState((current) => ({ ...current, status: 'loading', error: null }))
    try {
      const response = await listTasks(projectId)
      setState({ status: 'ready', items: response.items, error: null })
    } catch (error) {
      setState({ status: 'error', items: [], error: formatApiError(error) })
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
  }, [refresh])

  return {
    ...state,
    createTask: create,
    runTaskAction: runAction,
    refresh,
  }
}
