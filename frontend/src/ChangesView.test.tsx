import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { ChangesView } from './ChangesView'
import type { Course, IntakeCandidate, ReviewItem } from './types'

const course: Course = { id: 'POL 2103 - Politics', code: 'POL 2103', name: 'POL 2103 - Politics', path: '/workspace/Fall 2026/POL 2103 - Politics', inbox_count: 0, material_count: 3, review_required: false }

const review: ReviewItem = { id: 'review-1', kind: 'deadline_conflict', title: 'Essay deadline needs a decision', course: course.id, status: 'open', priority: 'normal', created_at: '', updated_at: '', details: {} }

const candidate: IntakeCandidate = {
  id: 'candidate-1', intake_id: 'intake-1', semester: 'Fall 2026', course_id: course.id, entity_type: 'assessment', entity_title: 'Second Essay',
  field: 'due_date', value: '2026-11-24', value_type: 'date', source_path: 'Fall 2026/POL 2103 - Politics/00_INBOX/announcement.md', source_locator: 'line 1',
  source_excerpt: 'The professor moved the Second Essay deadline to November 24.', source_kind: 'imported_document', confidence: 'likely', specificity: 'exact',
  status: 'resolved', display_status: 'resolved', resolution: { assessment_title: 'Second Essay' }, warnings: [], created_at: '', created_by: 'user', updated_at: '',
}

describe('ChangesView', () => {
  it('shows pending intake candidates and opens the course intake', () => {
    const onOpenIntake = vi.fn()
    render(<ChangesView reviews={[review]} intakeCandidates={[candidate]} courses={[course]} activity={[]} busy={false} error="" onDecision={vi.fn()} onExecute={vi.fn()} onOpenIntake={onOpenIntake} />)
    expect(screen.getByRole('heading', { name: 'Changes & approvals' })).toBeInTheDocument()
    expect(screen.getByText('Intake waiting for you')).toBeInTheDocument()
    expect(screen.getByText('Second Essay')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Open course intake/ }))
    expect(onOpenIntake).toHaveBeenCalledWith(candidate)
  })

  it('offers a course step for candidates without a resolved course', () => {
    const onOpenIntake = vi.fn()
    const unresolved = { ...candidate, id: 'candidate-2', course_id: null, status: 'needs_course', display_status: 'needs_course' }
    render(<ChangesView reviews={[]} intakeCandidates={[unresolved]} courses={[course]} activity={[]} busy={false} error="" onDecision={vi.fn()} onExecute={vi.fn()} onOpenIntake={onOpenIntake} />)
    fireEvent.click(screen.getByRole('button', { name: /Choose a course/ }))
    expect(onOpenIntake).toHaveBeenCalledWith(unresolved)
  })
})
