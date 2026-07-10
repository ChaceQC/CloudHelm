import assert from 'node:assert/strict'
import test from 'node:test'

import { canApproveReview, canRequestReviewChanges } from '../src/features/design-review/reviewActionPolicy.ts'

test('评审操作只允许作用于当前可决策版本', () => {
  assert.equal(canApproveReview('draft', true), true)
  assert.equal(canApproveReview('approved', true), false)
  assert.equal(canApproveReview('draft', false), false)

  assert.equal(canRequestReviewChanges('draft', true), true)
  assert.equal(canRequestReviewChanges('approved', true), true)
  assert.equal(canRequestReviewChanges('changes_requested', true), false)
  assert.equal(canRequestReviewChanges('approved', false), false)
})
