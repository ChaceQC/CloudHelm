import { useState } from 'react'
import type { FormEvent } from 'react'
import { formatApiError } from '../../shared/api/formatters'
import type { Project, ProjectCreateInput } from '../../shared/types/api'

interface ProjectCreateFormProps {
  onCreate: (payload: ProjectCreateInput) => Promise<Project>
  onCreated: (project: Project) => void
}

/**
 * 项目创建表单。
 *
 * 表单字段直接对应 `ProjectCreate` DTO；提交失败时展示后端真实错误，
 * 不在前端生成临时项目。
 */
export function ProjectCreateForm({ onCreate, onCreated }: ProjectCreateFormProps) {
  const [name, setName] = useState('')
  const [repoUrl, setRepoUrl] = useState('')
  const [defaultBranch, setDefaultBranch] = useState('main')
  const [provider, setProvider] = useState('git')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSubmitting(true)
    setError(null)

    try {
      const project = await onCreate({
        name: name.trim(),
        repo_url: repoUrl.trim(),
        default_branch: defaultBranch.trim() || 'main',
        provider: provider.trim() || 'git',
      })
      setName('')
      setRepoUrl('')
      setDefaultBranch('main')
      setProvider('git')
      onCreated(project)
    } catch (submitError) {
      setError(formatApiError(submitError))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form className="stacked-form compact-form" onSubmit={handleSubmit}>
      <label>
        项目名称
        <input value={name} onChange={(event) => setName(event.target.value)} required maxLength={120} />
      </label>
      <label>
        仓库地址或路径
        <input value={repoUrl} onChange={(event) => setRepoUrl(event.target.value)} required />
      </label>
      <div className="form-row">
        <label>
          默认分支
          <input value={defaultBranch} onChange={(event) => setDefaultBranch(event.target.value)} required />
        </label>
        <label>
          Provider
          <input value={provider} onChange={(event) => setProvider(event.target.value)} required />
        </label>
      </div>
      {error !== null ? <p className="form-error">{error}</p> : null}
      <button type="submit" disabled={submitting}>
        {submitting ? '创建中...' : '创建项目'}
      </button>
    </form>
  )
}
