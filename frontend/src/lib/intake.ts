import type { IntakeCandidate } from '../types'

/**
 * Candidate states that still need a student decision or a new proposal.
 * Applied, reverted, and cancelled candidates are historical.
 */
export const pendingIntakeStatuses = new Set([
  'candidate',
  'conflict',
  'resolved',
  'needs_entity',
  'needs_course',
  'needs_confirmation',
  'proposed',
  'needs_attention',
])

export function isPendingIntakeCandidate(candidate: IntakeCandidate) {
  return pendingIntakeStatuses.has(candidate.display_status || candidate.status)
}
