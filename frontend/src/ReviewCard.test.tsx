import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { ReviewCard } from './ReviewCard'
import type { ReviewItem } from './types'

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
})
