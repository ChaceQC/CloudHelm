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
 * M4 根组件只负责组合 Project Sidebar、Task Board、Task Detail 和
 * 健康检查；真实数据加载、表单提交和审批操作拆分到 feature hooks，
 * 避免页面层堆积业务逻辑。
 */
export function App() {
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null)
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [detailRefreshKey, setDetailRefreshKey] = useState(0)
  const projects = useProjects()
  const tasks = useTasks(selectedProjectId)

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
    <main className="app-shell">
      <section className="hero">
        <p className="eyebrow">CloudHelm M4</p>
        <h1>云舵控制台 Agent 编排闭环</h1>
        <p className="hero-copy">
          当前阶段接入真实 Platform API，可创建项目和任务、查看任务详情、
          启动/推进 Requirement、Architect、Planner 编排，并展示 Timeline、
          Tool Calls 与审批记录。真实工具执行、PR、部署和监控仍按后续 M5-M8
          里程碑推进。
        </p>
      </section>

      <div className="console-layout">
        <ProjectSidebar
          projects={projects.items}
          status={projects.status}
          error={projects.error}
          selectedProjectId={selectedProjectId}
          onSelectProject={setSelectedProjectId}
          onCreateProject={projects.createProject}
          onProjectCreated={handleProjectCreated}
          onRetry={projects.refresh}
        />
        <div className="workspace-area">
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
          <TaskDetail taskId={selectedTaskId} refreshKey={detailRefreshKey} onTaskChanged={tasks.refresh} />
        </div>
      </div>

      <HealthPanel />
    </main>
  )
}
