import { HealthPanel } from './features/health/HealthPanel'
import { ProjectSidebar } from './features/projects/ProjectSidebar'
import { useProjects } from './features/projects/useProjects'
import { TaskBoard } from './features/tasks/TaskBoard'
import { TaskDetail } from './features/tasks/TaskDetail'
import { useTasks } from './features/tasks/useTasks'
import type { Project, Task } from './shared/types/api'
import { useEffect, useState } from 'react'

/**
 * 控制台应用根组件。
 *
 * M5 根组件只负责组合 Project Sidebar、Task Board、Task Detail 和
 * 健康检查；真实数据加载、表单提交和审批操作拆分到 feature hooks，
 * 避免页面层堆积业务逻辑。
 */
export function App() {
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null)
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [detailRefreshKey, setDetailRefreshKey] = useState(0)
  const projects = useProjects()
  const tasks = useTasks(selectedProjectId)
  const selectedProject = projects.items.find((project) => project.id === selectedProjectId) ?? null
  const selectedTask = tasks.items.find((task) => task.id === selectedTaskId) ?? null

  useEffect(() => {
    setSelectedProjectId((currentProjectId) => {
      if (currentProjectId !== null && projects.items.some((project) => project.id === currentProjectId)) {
        return currentProjectId
      }

      return projects.items[0]?.id ?? null
    })
  }, [projects.items])

  useEffect(() => {
    setSelectedTaskId((currentTaskId) => {
      if (currentTaskId !== null && tasks.items.some((task) => task.id === currentTaskId)) {
        return currentTaskId
      }

      return tasks.items[0]?.id ?? null
    })
  }, [tasks.items])

  const handleProjectCreated = (project: Project) => {
    setSelectedProjectId(project.id)
    setSelectedTaskId(null)
  }

  const handleSelectProject = (projectId: string) => {
    setSelectedTaskId(null)
    setSelectedProjectId(projectId)
  }

  const handleTaskCreated = (task: Task) => {
    setSelectedTaskId(task.id)
    setDetailRefreshKey((current) => current + 1)
  }

  const handleRunTaskAction: typeof tasks.runTaskAction = async (taskId, action, payload) => {
    const task = await tasks.runTaskAction(taskId, action, payload)
    setSelectedTaskId(task.id)
    setDetailRefreshKey((current) => current + 1)
    return task
  }

  return (
    <div className="app-shell">
      <aside className="app-sidebar" aria-label="项目与任务导航">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true">✦</span>
          <div>
            <strong>CloudHelm</strong>
            <span>智能研发控制台</span>
          </div>
        </div>
        <ProjectSidebar
          projects={projects.items}
          status={projects.status}
          error={projects.error}
          selectedProjectId={selectedProjectId}
          onSelectProject={handleSelectProject}
          onCreateProject={projects.createProject}
          onProjectCreated={handleProjectCreated}
          onRetry={projects.refresh}
        />
        <div className="sidebar-task-area">
          <TaskBoard
            projectSelected={selectedProjectId !== null}
            tasks={tasks.items}
            status={tasks.status}
            error={tasks.error}
            selectedTaskId={selectedTaskId}
            onSelectTask={setSelectedTaskId}
            onCreateTask={tasks.createTask}
            onTaskCreated={handleTaskCreated}
            onRunTaskAction={handleRunTaskAction}
            onRefresh={tasks.refresh}
          />
        </div>
      </aside>

      <main className="app-main">
        <header className="app-topbar">
          <div className="workspace-context">
            <span>{selectedProject?.name ?? '选择项目'}</span>
            <strong>{selectedTask?.title ?? 'CloudHelm 工作台'}</strong>
          </div>
          <HealthPanel />
        </header>
        <div className="workspace-area">
          <TaskDetail taskId={selectedTaskId} refreshKey={detailRefreshKey} onTaskChanged={tasks.refresh} />
        </div>
      </main>
    </div>
  )
}
