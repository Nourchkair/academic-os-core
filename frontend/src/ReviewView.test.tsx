import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { ReviewView } from './ReviewView'
import type { ActivityEvent, ReviewItem } from './types'

const openItem: ReviewItem = {
  id: 'review-1',
  kind: 'deadline_conflict',
  title: 'Research Essay deadline needs a decision',
  course: 'POL 2103 - Politics',
  status: 'open',
  priority: 'normal',
  created_at: '2026-11-10T00:00:00Z',
  updated_at: '2026-11-10T00:00:00Z',
  details: { current: '2026-10-19', new: '2026-10-22', evidence: 'Updated syllabus' },
}

const approvedItem: ReviewItem = {
  id: 'review-2',
  kind: 'action_approval',
  title: 'Import lecture.pdf',
  course: 'POL 2103 - Politics',
  status: 'approved',
  priority: 'normal',
  created_at: '2026-11-10T00:00:00Z',
  updated_at: '2026-11-10T00:00:00Z',
  action_proposal_id: 'action-1',
  details: {
    action_type: 'file_copy',
    proposal_details: {
      action_type: 'file_copy',
      source_path: '/tmp/lecture.pdf',
      target_id: 'Fall 2026/POL 2103 - Politics/00_INBOX',
      effects: ['copy lecture.pdf into the course inbox', 'preserve the original source'],
    },
  },
}

const verified: ActivityEvent = {
  id: 'activity-1',
  event_type: 'action.verified',
  title: 'Import lecture.pdf',
  course: 'POL 2103 - Politics',
  details: { proposal_id: 'action-1', verification: { verified: true } },
  actor: 'user',
  created_at: '2026-11-10T00:05:00Z',
}

describe('ReviewView', () => {
  it('renders open decisions and submits the exact decision', () => {
    const onDecision = vi.fn().mockResolvedValue(undefined)
    render(<ReviewView items={[openItem]} courses={[]} activity={[]} busy={false} error="" onDecision={onDecision} onExecute={vi.fn()} />)

    expect(screen.getByText('Review & approvals')).toBeInTheDocument()
    expect(screen.getByText('1 open decision')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Use 2026-10-22' }))
    expect(onDecision).toHaveBeenCalledWith('review-1', 'use_new')
  })

  it('executes an approved action separately', () => {
    const onExecute = vi.fn().mockResolvedValue(undefined)
    render(<ReviewView items={[approvedItem]} courses={[]} activity={[]} busy={false} error="" onDecision={vi.fn()} onExecute={onExecute} />)

    expect(screen.getByText('1 approved action ready to execute')).toBeInTheDocument()
    expect(screen.getByText('Nothing has been copied or changed yet.')).toBeInTheDocument()
    expect(screen.getByText('/tmp/lecture.pdf')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Execute approved action' }))
    expect(onExecute).toHaveBeenCalledWith('review-2')
  })

  it('shows the approval timeline and empty state', () => {
    render(<ReviewView items={[]} courses={[]} activity={[verified]} busy={false} error="" onDecision={vi.fn()} onExecute={vi.fn()} />)

    expect(screen.getByText('No decisions waiting')).toBeInTheDocument()
    expect(screen.getByText('Approval timeline')).toBeInTheDocument()
    expect(screen.getByText('Import lecture.pdf')).toBeInTheDocument()
    expect(screen.getByText(/verified · user/)).toBeInTheDocument()
  })

  it('disables execution while busy and surfaces errors', () => {
    render(<ReviewView items={[approvedItem]} courses={[]} activity={[]} busy error="Execution failed safely." onDecision={vi.fn()} onExecute={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Executing…' })).toBeDisabled()
    expect(screen.getByRole('alert')).toHaveTextContent('Execution failed safely.')
  })

  it('highlights the exact Review item linked from chat', () => {
    render(<ReviewView items={[approvedItem]} courses={[]} activity={[]} busy={false} error="" focusId="review-2" onFocusConsumed={vi.fn()} onDecision={vi.fn()} onExecute={vi.fn()} />)

    expect(document.getElementById('review-review-2')).toHaveClass('review-card-focus')
  })
})
