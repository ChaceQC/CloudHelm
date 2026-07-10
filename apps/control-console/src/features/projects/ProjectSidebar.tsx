import { ProjectCreateForm } from './ProjectCreateForm'
import type { Project, ProjectCreateInput } from '../../shared/types/api'

interface ProjectSidebarProps {
  projects: Project[]
  status: 'loading' | 'ready' | 'error'
  error: string | null
  selectedProjectId: string | null
  onSelectProject: (projectId: string) => void
  onCreateProject: (payload: ProjectCreateInput) => Promise<Project>
  onProjectCreated: (project: Project) => void
  onRetry: () => void
}

/**
 * Project Sidebar。
 *
 * 负责展示真实项目列表、错误态、空状态和创建入口；当前运行任务数等
 * 聚合指标留到后续后端提供统计接口后接入，避免前端伪造。
 */
export function ProjectSidebar({
  projects,
  status,
  error,
  selectedProjectId,
  onSelectProject,
  onCreateProject,
  onProjectCreated,
  onRetry,
}: ProjectSidebarProps) {
  return (
    <section className="project-sidebar" aria-label="项目空间">
      <div className="section-heading">
        <div>
          <p className="eyebrow">工作空间</p>
          <h2>项目空间</h2>
        </div>
        <button type="button" className="icon-button" onClick={onRetry} aria-label="刷新项目列表">
          ↻
        </button>
      </div>

      {status === 'loading' ? <p className="status-line">正在加载真实项目列表...</p> : null}
      {status === 'error' ? (
        <div className="status-error" role="alert">
          <strong>项目加载失败</strong>
          <p>{error}</p>
        </div>
      ) : null}
      {status === 'ready' && projects.length === 0 ? (
        <p className="empty-state">暂无项目。请创建项目后再提交任务。</p>
      ) : null}

      <div className="project-list">
        {projects.map((project) => {
          const selected = project.id === selectedProjectId
          return (
            <button
              key={project.id}
              type="button"
              className={`project-item${selected ? ' selected' : ''}`}
              onClick={() => onSelectProject(project.id)}
              aria-pressed={selected}
            >
              <span className="project-item-title">
                <span className="project-dot" aria-hidden="true" />
                <strong>{project.name}</strong>
              </span>
              <span>{project.provider} · {project.default_branch}</span>
              <small title={project.repo_url}>{project.repo_url}</small>
            </button>
          )
        })}
      </div>

      <details className="create-disclosure">
        <summary><span aria-hidden="true">＋</span> 新建项目</summary>
        <ProjectCreateForm onCreate={onCreateProject} onCreated={onProjectCreated} />
      </details>
    </section>
  )
}
