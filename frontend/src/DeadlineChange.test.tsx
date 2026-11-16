import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { DeadlineChangeDialog } from './DeadlineChange'
import { api } from './lib/api'
import type { ChangeSet, Course, CourseworkHistoryRecord } from './types'

vi.mock('./lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./lib/api')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      tasks: vi.fn(),
      knowledgeLinks: vi.fn(),
      linkTaskToAssessment: vi.fn(),
      proposeDeadlineChange: vi.fn(),
      approveChangeSet: vi.fn(),
      executeChangeSet: vi.fn(),
      retryChangeSet: vi.fn(),
      reverseChangeSet: vi.fn(),
      cancelChangeSet: vi.fn(),
      pauseTaskLink: vi.fn(),
      resumeTaskLink: vi.fn(),
    },
  }
})

const course: Course = {
  id: 'POL 2103 - Politics',
  code: 'POL 2103',
  name: 'POL 2103 - Politics',
  path: '/workspace/Fall 2026/POL 2103 - Politics',
  inbox_count: 0,
  material_count: 2,
  review_required: false,
}

const record: CourseworkHistoryRecord = {
  id: 'history-one',
  kind: 'essay',
  title: 'Second Essay',
  status: 'planned',
  due_date: '2026-11-12',
  record_basis: 'user-confirmed',
  status_history: [],
  artifact_paths: [],
  created_at: '2026-11-01T00:00:00Z',
  updated_at: '2026-11-01T00:00:00Z',
  actor: 'user',
}

function changeset(overrides: Partial<ChangeSet> = {}): ChangeSet {
  return {
    id: 'changeset:one',
    version: 1,
    title: 'Move Second Essay deadline to November 20',
    course_id: course.id,
    semester: 'Fall 2026',
    origin: 'student_request',
    status: 'proposed',
    created_at: '2026-11-16T12:00:00Z',
    updated_at: '2026-11-16T12:00:00Z',
    created_by: 'user',
    summary: 'Update the assessment deadline from 2026-11-12 to 2026-11-20.',
    evidence_ids: ['evidence:one'],
    operations: [
      {
        id: 'op:assessment', type: 'assessment.set_deadline', target: {}, before: '2026-11-12', after: '2026-11-20',
        depends_on: [], required: true, default_selected: true, reversible: true, evidence_ids: ['evidence:one'],
        status: 'proposed', attempts: 0, label: 'Assessment deadline', target_title: 'Second Essay',
      },
      {
        id: 'op:task', type: 'task.set_due', target: {}, before: '2026-11-12', after: '2026-11-20',
        depends_on: ['op:assessment'], required: false, default_selected: true, reversible: true, skip_effect: 'pause_link',
        evidence_ids: ['evidence:one'], status: 'proposed', attempts: 0, label: 'Task deadline', target_title: 'Finish Second Essay',
      },
    ],
    conflicts: [{ id: 'conflict:one', why: 'The canonical record says 2026-11-12, and this student report says 2026-11-20.' }],
    warnings: [],
    impact: { required_operations: ['op:assessment'], optional_operations: ['op:task'], irreversible_operations: [], affected_entities: [], summary: '1 assessment and 1 mirrored task' },
    approval: { status: 'pending' },
    execution: {},
    result: { state: 'not_started', operation_results: [] },
    reversal: { status: 'not_requested' },
    evidence: [{ id: 'evidence:one', source: 'Student report', source_kind: 'student_report', verification: 'unverified' }],
    ...overrides,
  }
}

function setup() {
  vi.mocked(api.tasks).mockResolvedValue({
    semester: 'Fall 2026', path: 'Fall 2026/SEMESTER_TASKS.md', task_state_error: null,
    tasks: [{
      id: 'task:one', task_id: 'one', title: 'Finish Second Essay', completed: false, course: course.id,
      source: 'Fall 2026/SEMESTER_TASKS.md', confidence: 'user-confirmed', user_task: true, due_date: '2026-11-12', status: 'open',
    }],
  })
  vi.mocked(api.knowledgeLinks).mockResolvedValue({ links: [] })
  vi.mocked(api.linkTaskToAssessment).mockResolvedValue({
    id: 'link:one', course_id: course.id, assessment_id: 'assessment:history:history-one', task_id: 'one',
    mode: 'mirror_deadline', status: 'active', task_title: 'Finish Second Essay',
  })
  vi.mocked(api.proposeDeadlineChange).mockResolvedValue(changeset())
  vi.mocked(api.approveChangeSet).mockResolvedValue(changeset({ status: 'approved' }))
  vi.mocked(api.executeChangeSet).mockResolvedValue(changeset({
    status: 'verified',
    result: {
      state: 'verified',
      operation_results: [
        { operation_id: 'op:assessment', type: 'assessment.set_deadline', target: {}, label: 'Assessment deadline', target_title: 'Second Essay', status: 'verified', before: '2026-11-12', after: '2026-11-20', attempts: 1 },
        { operation_id: 'op:task', type: 'task.set_due', target: { link_id: 'link:one' }, label: 'Task deadline', target_title: 'Finish Second Essay', status: 'skipped', before: '2026-11-12', after: '2026-11-20', attempts: 0, skip_effect_applied: true },
      ],
    },
  }))
  vi.mocked(api.reverseChangeSet).mockResolvedValue(changeset({ status: 'reverted', result: { state: 'reverted', operation_results: [] } }))
  vi.mocked(api.cancelChangeSet).mockResolvedValue(changeset({ status: 'cancelled' }))
  vi.mocked(api.pauseTaskLink).mockResolvedValue({} as never)
  vi.mocked(api.resumeTaskLink).mockResolvedValue({} as never)
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('DeadlineChangeDialog', () => {
  it('links an explicitly selected task, previews impact, and approves a subset', async () => {
    setup()
    const onChanged = vi.fn().mockResolvedValue(undefined)
    render(<DeadlineChangeDialog course={course} semester="Fall 2026" record={record} onClose={vi.fn()} onChanged={onChanged} />)

    fireEvent.change(screen.getByLabelText('New deadline'), { target: { value: '2026-11-20' } })
    await waitFor(() => expect(screen.getByText('Finish Second Essay')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: 'Preview change' }))

    await waitFor(() => expect(api.linkTaskToAssessment).toHaveBeenCalledWith({ courseId: course.id, semester: 'Fall 2026', assessmentId: 'assessment:history:history-one', taskId: 'one', mode: 'mirror_deadline' }))
    await waitFor(() => expect(screen.getByText('Review before applying')).toBeInTheDocument())
    expect(screen.getByText(/The canonical record says 2026-11-12/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: 'Approve selected and apply' }))

    await waitFor(() => expect(api.approveChangeSet).toHaveBeenCalledWith('changeset:one', 'Fall 2026', ['op:assessment']))
    await waitFor(() => expect(api.executeChangeSet).toHaveBeenCalledWith('changeset:one', 'Fall 2026'))
    await waitFor(() => expect(screen.getByText('Change applied and verified')).toBeInTheDocument())
    expect(onChanged).toHaveBeenCalled()
    expect(screen.getByText(/Deadline link paused/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Undo this change' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(api.pauseTaskLink).not.toHaveBeenCalled()
  })

  it('offers retry for a partial failure and undo only when reversible', async () => {
    setup()
    vi.mocked(api.executeChangeSet).mockResolvedValue(changeset({
      status: 'partially_applied',
      result: {
        state: 'partially_applied',
        operation_results: [
          { operation_id: 'op:assessment', type: 'assessment.set_deadline', target: {}, label: 'Assessment deadline', target_title: 'Second Essay', status: 'verified', before: '2026-11-12', after: '2026-11-20', attempts: 1 },
          { operation_id: 'op:task', type: 'task.set_due', target: {}, label: 'Task deadline', target_title: 'Finish Second Essay', status: 'failed', before: '2026-11-12', after: '2026-11-20', attempts: 1, error: 'readback did not match' },
        ],
      },
    }))
    render(<DeadlineChangeDialog course={course} semester="Fall 2026" record={record} onClose={vi.fn()} onChanged={vi.fn().mockResolvedValue(undefined)} />)
    fireEvent.change(screen.getByLabelText('New deadline'), { target: { value: '2026-11-20' } })
    fireEvent.click(screen.getByRole('button', { name: 'Preview change' }))
    await waitFor(() => expect(screen.getByText('Review before applying')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Approve selected and apply' }))
    await waitFor(() => expect(screen.getByText('Part of the change needs attention')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Retry failed operations' })).toBeInTheDocument()
  })
})
