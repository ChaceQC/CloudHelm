import { useState } from 'react'
import { formatApiError, formatDateTime } from '../../shared/api/formatters'
import type { ApprovalRequest, DecisionRequest } from '../../shared/types/api'

interface ApprovalPanelProps {
  approvals: ApprovalRequest[]
  onDecideApproval: (
    approvalId: string,
    action: 'approve' | 'reject',
    payload: DecisionRequest,
  ) => Promise<ApprovalRequest>
}

/**
 * Approval Panel。
 *
 * 用于 M3 基础审批交互，调用真实 approve/reject API。L3/L4 拦截和
 * Tool Gateway 恢复执行属于后续 M5/M9。
 */
export function ApprovalPanel({ approvals, onDecideApproval }: ApprovalPanelProps) {
  const [comment, setComment] = useState('')
  const [message, setMessage] = useState<string | null>(null)

  const decide = async (approvalId: string, action: 'approve' | 'reject') => {
    setMessage(null)
    try {
      await onDecideApproval(approvalId, action, {
        actor_id: 'control-console',
        reason: comment.trim() === '' ? null : comment.trim(),
      })
      setComment('')
      setMessage(action === 'approve' ? '审批已通过。' : '审批已拒绝。')
    } catch (error) {
      setMessage(formatApiError(error))
    }
  }

  return (
    <section className="sub-panel" aria-labelledby="approval-title">
      <h3 id="approval-title">Approval Panel</h3>
      <label className="decision-comment">
        审批意见
        <textarea value={comment} onChange={(event) => setComment(event.target.value)} rows={2} />
      </label>
      {message !== null ? <p className="operation-message">{message}</p> : null}
      {approvals.length === 0 ? <p className="empty-state">暂无当前任务的真实审批请求。</p> : null}

      <div className="record-list">
        {approvals.map((approval) => (
          <article className="record-card" key={approval.id}>
            <div className="card-toolbar">
              <strong>{approval.action}</strong>
              <span className="risk-chip">{approval.risk_level}</span>
              <span className={`review-status status-${approval.status}`}>{approval.status}</span>
            </div>
            <p>{approval.reason}</p>
            <small>
              创建：{formatDateTime(approval.created_at)} · 决策人：{approval.decided_by ?? '未决策'}
            </small>
            <div className="action-row">
              <button
                type="button"
                onClick={() => void decide(approval.id, 'approve')}
                disabled={approval.status !== 'pending'}
              >
                Approve
              </button>
              <button
                type="button"
                className="danger"
                onClick={() => void decide(approval.id, 'reject')}
                disabled={approval.status !== 'pending'}
              >
                Reject
              </button>
            </div>
          </article>
        ))}
      </div>
    </section>
  )
}
