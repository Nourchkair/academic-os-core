import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ReviewCard } from './ReviewCard'
import { api } from './lib/api'
import type { Course, ReviewItem } from './types'

vi.mock('./lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./lib/api')>()
  return { ...actual, api: { ...actual.api, reviewAdvice: vi.fn() } }
})

const item: ReviewItem = {
  id: 'review-1',
  kind: 'deadline_conflict',
  title: 'Research Essay deadline needs a decision',
  course: 'POL 2103 - Politics',
  status: 'open',
  priority: 'normal',
  created_at: '2026-11-10T00:00:00Z',
  updated_at: '2026-11-10T00:00:00Z',
  details: {
    current: '2026-10-19',
    new: '2026-10-22',
    evidence: 'Updated syllabus',
    confidence: 'current-confirmed',
  },
}

describe('ReviewCard', () => {
  it('shows both deadline values and submits the exact decision', async () => {
    const onDecision = vi.fn().mockResolvedValue(undefined)
    render(<ReviewCard item={item} courses={[]} busy={false} onDecision={onDecision} />)

    expect(screen.getByText('Research Essay deadline needs a decision')).toBeInTheDocument()
    expect(screen.getByText('Currently saved')).toBeInTheDocument()
    expect(screen.getByText('2026-10-19')).toBeInTheDocument()
    expect(screen.getByText('2026-10-22')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Use 2026-10-22' }))
    expect(onDecision).toHaveBeenCalledWith('use_new')

    fireEvent.click(screen.getByRole('button', { name: 'Keep 2026-10-19' }))
    expect(onDecision).toHaveBeenCalledWith('keep_current')
  })

  it('disables decisions while busy', () => {
    render(<ReviewCard item={item} courses={[]} busy onDecision={vi.fn().mockResolvedValue(undefined)} />)
    expect(screen.getByRole('button', { name: 'Use 2026-10-22' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Keep 2026-10-19' })).toBeDisabled()
  })

  it('renders the advanced evidence payload without executing anything', () => {
    render(<ReviewCard item={item} courses={[]} busy={false} onDecision={vi.fn().mockResolvedValue(undefined)} />)
    fireEvent.click(screen.getByText('Advanced details'))
    expect(screen.getByText(/"current": "2026-10-19"/)).toBeInTheDocument()
  })

  it('shows an exact personal-task proposal with task-specific decisions', () => {
    const onDecision = vi.fn().mockResolvedValue(undefined)
    const taskItem: ReviewItem = {
      ...item,
      kind: 'action_approval',
      title: 'Add task: Read Week 5',
      action_proposal_id: 'action-1',
      details: {
        action_type: 'task_change',
        proposal_details: {
          action_type: 'task_change',
          action: 'create',
          before: 'No personal task',
          after: 'Read Week 5 · POL 2103 - Politics · due 2026-10-01 09:00',
          effects: ["add 'Read Week 5' to Fall 2026/SEMESTER_TASKS.md", 'preserve unrelated Markdown and every existing task'],
          task_after: {
            title: 'Read Week 5',
            course_id: 'POL 2103 - Politics',
            due_date: '2026-10-01',
            due_time: '09:00',
          },
        },
      },
    }
    render(<ReviewCard item={taskItem} courses={[]} busy={false} onDecision={onDecision} />)
    expect(screen.getByText('No personal task')).toBeInTheDocument()
    expect(screen.getByText('Read Week 5 · POL 2103 - Politics · due 2026-10-01 09:00')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Add this task' }))
    expect(onDecision).toHaveBeenCalledWith('approve_action')
    fireEvent.click(screen.getByRole('button', { name: 'Keep task unchanged' }))
    expect(onDecision).toHaveBeenCalledWith('reject_action')
  })

  it('edits a task proposal before approval', () => {
    const onAmend = vi.fn().mockResolvedValue(undefined)
    const course: Course = {
      id: 'POL 2103 - Politics',
      code: 'POL 2103',
      name: 'POL 2103 - Politics',
      path: '/workspace/Fall 2026/POL 2103 - Politics',
      inbox_count: 0,
      material_count: 1,
      review_required: false,
    }
    const taskItem: ReviewItem = {
      ...item,
      kind: 'action_approval',
      title: 'Add task: Read Week 5',
      action_proposal_id: 'action-1',
      details: {
        action_type: 'task_change',
        proposal_details: {
          action_type: 'task_change',
          action: 'create',
          before: 'No personal task',
          after: 'Read Week 5 · POL 2103 - Politics · due 2026-10-01 09:00',
          effects: ["add 'Read Week 5' to Fall 2026/SEMESTER_TASKS.md"],
          task_after: {
            title: 'Read Week 5',
            course_id: 'POL 2103 - Politics',
            due_date: '2026-10-01',
            due_time: '09:00',
          },
        },
      },
    }
    render(<ReviewCard item={taskItem} courses={[course]} busy={false} onDecision={vi.fn()} onAmend={onAmend} />)

    fireEvent.click(screen.getByRole('button', { name: 'Edit proposal' }))
    fireEvent.change(screen.getByLabelText('Task'), { target: { value: 'Read Week 6' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save proposal' }))

    expect(onAmend).toHaveBeenCalledWith({
      title: 'Read Week 6',
      course_id: 'POL 2103 - Politics',
      due_date: '2026-10-01',
      due_time: '09:00',
    })
  })
})

describe('ReviewCard decision help', () => {
  it('renders suggested options and applies the chosen decision', async () => {
    vi.mocked(api.reviewAdvice).mockResolvedValue({
      review_id: 'review-1',
      kind: 'deadline_conflict',
      options: [
        { decision: 'keep_current', label: 'Keep the saved due date', rationale: 'Matches the original syllabus.' },
        { decision: 'use_new', label: 'Use the updated due date', rationale: 'The addendum moves it.' },
      ],
      recommended: 'keep_current',
      note: 'Confirm with the instructor if unsure.',
      model: 'test-model',
    })
    const onDecision = vi.fn().mockResolvedValue(undefined)
    render(<ReviewCard item={item} courses={[]} busy={false} onDecision={onDecision} />)

    fireEvent.click(screen.getByRole('button', { name: 'Help me decide' }))
    await waitFor(() => expect(api.reviewAdvice).toHaveBeenCalledWith('review-1'))
    expect(await screen.findByText('Keep the saved due date')).toBeInTheDocument()
    expect(screen.getByText('Recommended')).toBeInTheDocument()
    expect(screen.getByText('Confirm with the instructor if unsure.')).toBeInTheDocument()

    const applyButtons = screen.getAllByRole('button', { name: 'Apply' })
    fireEvent.click(applyButtons[1])
    expect(onDecision).toHaveBeenCalledWith('use_new')
  })
})
