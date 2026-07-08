import type { DecisionRequest, RequirementSpec, TechnicalDesign } from '../../shared/types/api'
import { RequirementPanel } from './RequirementPanel'
import { TechnicalDesignPanel } from './TechnicalDesignPanel'

interface DesignReviewPanelProps {
  requirements: RequirementSpec[]
  designs: TechnicalDesign[]
  onDecideRequirement: (
    requirementId: string,
    action: 'approve' | 'request-changes',
    payload: DecisionRequest,
  ) => Promise<RequirementSpec>
  onDecideDesign: (
    designId: string,
    action: 'approve' | 'request-changes',
    payload: DecisionRequest,
  ) => Promise<TechnicalDesign>
}

/**
 * 设计审查主面板。
 *
 * 将 Requirement 与 Technical Design 分开展示，避免在 Task Detail 中
 * 堆积评审业务逻辑。
 */
export function DesignReviewPanel({
  requirements,
  designs,
  onDecideRequirement,
  onDecideDesign,
}: DesignReviewPanelProps) {
  return (
    <div className="detail-section">
      <RequirementPanel requirements={requirements} onDecideRequirement={onDecideRequirement} />
      <TechnicalDesignPanel designs={designs} onDecideDesign={onDecideDesign} />
    </div>
  )
}
