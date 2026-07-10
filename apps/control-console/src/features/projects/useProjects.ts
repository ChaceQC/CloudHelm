import { useCallback, useEffect, useRef, useState } from 'react'
import { createProject, listProjects } from '../../shared/api/cloudhelmApi'
import { formatApiError } from '../../shared/api/formatters'
import { LatestRequestGate } from '../../shared/api/latestRequest'
import type { Project, ProjectCreateInput } from '../../shared/types/api'

interface ProjectsState {
  status: 'loading' | 'ready' | 'error'
  items: Project[]
  error: string | null
}

/**
 * Project 列表 Hook。
 *
 * 只通过真实 `GET /api/projects` 和 `POST /api/projects` 同步数据；
 * 创建成功后刷新列表，保证 Sidebar 不展示本地临时项目。
 */
export function useProjects() {
  const requestGate = useRef(new LatestRequestGate())
  const [state, setState] = useState<ProjectsState>({
    status: 'loading',
    items: [],
    error: null,
  })

  const refresh = useCallback(async () => {
    const token = requestGate.current.begin()
    setState((current) => ({ ...current, status: 'loading', error: null }))
    try {
      const response = await listProjects()
      if (!requestGate.current.isCurrent(token)) {
        return
      }
      setState({ status: 'ready', items: response.items, error: null })
    } catch (error) {
      if (requestGate.current.isCurrent(token)) {
        setState({ status: 'error', items: [], error: formatApiError(error) })
      }
    }
  }, [])

  const create = useCallback(
    async (payload: ProjectCreateInput) => {
      const project = await createProject(payload)
      await refresh()
      return project
    },
    [refresh],
  )

  useEffect(() => {
    void refresh()
    return () => requestGate.current.invalidate()
  }, [refresh])

  return {
    ...state,
    createProject: create,
    refresh,
  }
}
