import type { ReviewStatus } from '../../shared/types/api'

/**
 * 只有当前最新版 draft 产物可以执行批准。
 */
export function canApproveReview(status: ReviewStatus, isCurrent: boolean): boolean {
  return isCurrent && status === 'draft'
}

/**
 * 当前最新版 draft/approved 产物可以要求修改，历史或已返工版本不可重复决策。
 */
export function canRequestReviewChanges(status: ReviewStatus, isCurrent: boolean): boolean {
  return isCurrent && (status === 'draft' || status === 'approved')
}
