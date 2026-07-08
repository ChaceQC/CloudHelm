import { useState } from 'react'
import type { FormEvent } from 'react'
import { formatApiError } from '../../shared/api/formatters'
import type { RiskLevel, Task, TaskCreateInput } from '../../shared/types/api'

interface TaskCreateFormProps {
  disabled: boolean
  onCreate: (payload: Omit<TaskCreateInput, 'project_id'>) => Promise<Task>
  onCreated: (task: Task) => void
}

const riskLevels: RiskLevel[] = ['L0', 'L1', 'L2', 'L3', 'L4']

/**
 * 需求输入表单。
 *
 * 当前表单只调用 `POST /api/tasks` 创建任务记录；Requirement Agent 自动
 * 规格化需要用户在 M4 编排区显式启动和推进。
 */
export function TaskCreateForm({ disabled, onCreate, onCreated }: TaskCreateFormProps) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [sourceRef, setSourceRef] = useState('')
  const [riskLevel, setRiskLevel] = useState<RiskLevel>('L0')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSubmitting(true)
    setError(null)

    try {
      const task = await onCreate({
        title: title.trim(),
        description: description.trim(),
        source_type: 'manual',
        source_ref: sourceRef.trim() === '' ? null : sourceRef.trim(),
        risk_level: riskLevel,
        created_by: 'control-console',
      })
      setTitle('')
      setDescription('')
      setSourceRef('')
      setRiskLevel('L0')
      onCreated(task)
    } catch (submitError) {
      setError(formatApiError(submitError))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form className="stacked-form task-create-form" onSubmit={handleSubmit}>
      <label>
        需求标题
        <input value={title} onChange={(event) => setTitle(event.target.value)} disabled={disabled} required />
      </label>
      <label>
        自然语言需求
        <textarea
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          disabled={disabled}
          required
          rows={4}
        />
      </label>
      <div className="form-row">
        <label>
          来源引用
          <input
            value={sourceRef}
            onChange={(event) => setSourceRef(event.target.value)}
            disabled={disabled}
            placeholder="Issue URL / 草稿链接，可为空"
          />
        </label>
        <label>
          初始风险
          <select value={riskLevel} onChange={(event) => setRiskLevel(event.target.value as RiskLevel)} disabled={disabled}>
            {riskLevels.map((level) => (
              <option key={level} value={level}>
                {level}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error !== null ? <p className="form-error">{error}</p> : null}
      <button type="submit" disabled={disabled || submitting}>
        {submitting ? '提交中...' : '创建任务'}
      </button>
      <p className="form-hint">创建真实 Task 后，可在详情页 M4 编排区启动 Requirement / Architect / Planner。</p>
    </form>
  )
}
