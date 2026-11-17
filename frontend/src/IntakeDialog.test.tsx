import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { IntakeDialog } from './IntakeDialog'
import { api } from './lib/api'
import type { ChangeSet, Course } from './types'

vi.mock('./lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./lib/api')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      intakePaste: vi.fn(),
      intakePropose: vi.fn(),
      intakeResolve: vi.fn(),
      intakeReject: vi.fn(),
      approveChangeSet: vi.fn(),
      executeChangeSet: vi.fn(),
      cancelChangeSet: vi.fn(),
    },
  }
})

const course: Course = {
  id: 'POL 2103 - Politics',
  code: 'POL 2103',
  name: 'POL 2103 - Politics',
  path: '/workspace/Fall 2026/POL 2103 - Politics',
  inbox_count: 0,
  material_count: 0,
  review_required: false,
}

function pasted() {
  return {
    intake: {
      id: 'intake:one', semester: 'Fall 2026', course_id: course.id, source_kind: 'student_report',
      text_sha256: 'abc', source_path: 'Fall 2026/POL 2103 - Politics/00_INBOX/Announcement - 2026-11-16 - moved.md',
      text: 'My professor moved the Second Essay deadline to November 20.', status: 'candidates_found',
      candidate_ids: ['candidate:one'], warnings: [], created_at: '', created_by: 'user', updated_at: '', dedupe_key: 'key',
    },
    candidates: [{
      id: 'candidate:one', intake_id: 'intake:one', semester: 'Fall 2026', course_id: course.id,
      entity_type: 'assessment', entity_title: 'Second Essay', field: 'due_date', value: '2026-11-20', value_type: 'date',
      source_path: 'Fall 2026/POL 2103 - Politics/00_INBOX/Announcement - 2026-11-16 - moved.md',
      source_locator: 'pasted text', source_excerpt: 'My professor moved the Second Essay deadline to November 20.',
      source_kind: 'student_report', confidence: 'likely', specificity: 'exact', status: 'resolved',
      resolution: { course_id: course.id, assessment_id: 'assessment:history:one', assessment_title: 'Second Essay', current_due_date: '2026-11-12' },
      proposed_change_id: null, warnings: [], created_at: '', created_by: 'user', updated_at: '',
    }],
    available_assessments: [{ id: 'assessment:history:one', title: 'Second Essay', due_date: '2026-11-12' }],
    warnings: [],
  }
}

function changeset(): ChangeSet {
  return {
    id: 'changeset:intake', version: 1, title: 'Move Second Essay deadline to 2026-11-20',
    course_id: course.id, semester: 'Fall 2026', origin: 'student_request', status: 'proposed',
    created_at: '', updated_at: '', created_by: 'user', summary: 'Update the assessment deadline from 2026-11-12 to 2026-11-20.',
    evidence_ids: ['evidence:one'], operations: [{
      id: 'op:assessment', type: 'assessment.set_deadline', target: {}, before: '2026-11-12', after: '2026-11-20',
      depends_on: [], required: true, default_selected: true, reversible: true, evidence_ids: ['evidence:one'],
      status: 'proposed', attempts: 0, label: 'Assessment deadline', target_title: 'Second Essay',
    }], conflicts: [{ id: 'conflict:one', why: 'The canonical record says 2026-11-12, and this student report says 2026-11-20.' }],
    warnings: [], impact: { required_operations: ['op:assessment'], optional_operations: [], irreversible_operations: [], affected_entities: [], summary: '1 assessment' },
    approval: { status: 'pending' }, execution: {}, result: { state: 'not_started', operation_results: [] }, reversal: { status: 'not_requested' },
    evidence: [{ id: 'evidence:one', source: 'Pasted academic announcement', source_kind: 'student_report', verification: 'unverified' }],
  }
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('IntakeDialog', () => {
  it('preserves a paste, shows the resolved candidate, and opens the Phase 1 review', async () => {
    vi.mocked(api.intakePaste).mockResolvedValue(pasted())
    vi.mocked(api.intakePropose).mockResolvedValue(changeset())
    const onChanged = vi.fn().mockResolvedValue(undefined)
    render(<IntakeDialog course={course} semester="Fall 2026" onClose={vi.fn()} onChanged={onChanged} />)

    fireEvent.change(screen.getByLabelText('Announcement text'), { target: { value: 'My professor moved the Second Essay deadline to November 20.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Find deadline changes' }))

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Second Essay' })).toBeInTheDocument())
    expect(screen.getByText('Ready to review')).toBeInTheDocument()
    expect(screen.getByText(/currently due Nov 12, 2026/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Prepare change review' }))

    await waitFor(() => expect(api.intakePropose).toHaveBeenCalledWith('candidate:one', 'Fall 2026'))
    await waitFor(() => expect(screen.getByText('Review before applying')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Approve selected and apply' })).toBeInTheDocument()
  })
})
