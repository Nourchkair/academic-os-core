import { describe, expect, it } from 'vitest'
import { isPendingIntakeCandidate } from './intake'
import type { IntakeCandidate } from '../types'

function candidate(status: string, displayStatus?: string): IntakeCandidate {
  return {
    id: `candidate-${status}`,
    intake_id: 'intake-1',
    semester: 'Fall 2026',
    course_id: 'POL 2103 - Politics',
    entity_type: 'assessment',
    entity_title: 'Second Essay',
    field: 'due_date',
    value: '2026-11-24',
    value_type: 'date',
    source_path: 'Fall 2026/POL 2103 - Politics/00_INBOX/announcement.md',
    source_locator: 'line 1',
    source_excerpt: 'The professor moved the Second Essay deadline.',
    source_kind: 'imported_document',
    confidence: 'likely',
    specificity: 'exact',
    status,
    display_status: displayStatus,
    resolution: {},
    warnings: [],
    created_at: '',
    created_by: 'user',
    updated_at: '',
  }
}

describe('isPendingIntakeCandidate', () => {
  it('treats unresolved and proposed candidates as pending, and applied history as settled', () => {
    expect(isPendingIntakeCandidate(candidate('resolved'))).toBe(true)
    expect(isPendingIntakeCandidate(candidate('conflict'))).toBe(true)
    expect(isPendingIntakeCandidate(candidate('proposed', 'applied'))).toBe(false)
    expect(isPendingIntakeCandidate(candidate('proposed', 'needs_attention'))).toBe(true)
    expect(isPendingIntakeCandidate(candidate('no_change'))).toBe(false)
    expect(isPendingIntakeCandidate(candidate('cancelled'))).toBe(false)
  })
})
