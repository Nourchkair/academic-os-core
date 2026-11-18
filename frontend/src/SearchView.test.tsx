import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { SearchView } from './SearchView'
import type { Course, IntakeCandidate, Task } from './types'

const course: Course = { id: 'POL 2103 - Politics', code: 'POL 2103', name: 'POL 2103 - Politics', path: '/workspace/Fall 2026/POL 2103 - Politics', inbox_count: 0, material_count: 3, review_required: false }
const task: Task = { id: 'task-1', title: 'Finish Second Essay', completed: false, course: course.id, source: 'Fall 2026/SEMESTER_TASKS.md', confidence: 'user-confirmed', due_date: '2026-11-24', user_task: true }
const library = [{ id: 'file-1', name: 'Second Essay instructions.pdf', path: '/workspace/Fall 2026/POL 2103 - Politics/00_INBOX/Second Essay instructions.pdf', relative_path: 'Fall 2026/POL 2103 - Politics/00_INBOX/Second Essay instructions.pdf', semester: 'Fall 2026', course_id: course.id, category: 'assessments' as const, extension: '.pdf', size: 100, modified_at: '' }]
const candidate = (id: string, title: string, status: string, displayStatus: string): IntakeCandidate => ({
  id, intake_id: `intake-${id}`, semester: 'Fall 2026', course_id: course.id, entity_type: 'assessment', entity_title: title,
  field: 'due_date', value: '2026-11-24', value_type: 'date', source_path: 'Fall 2026/POL 2103 - Politics/00_INBOX/announcement.md', source_locator: 'line 1',
  source_excerpt: 'The professor moved the deadline.', source_kind: 'imported_document', confidence: 'likely', specificity: 'exact', status, display_status: displayStatus,
  resolution: {}, warnings: [], created_at: '', created_by: 'user', updated_at: '',
})

describe('SearchView', () => {
  it('finds tasks, courses, and library material and opens the right surface', () => {
    const onOpenCourse = vi.fn()
    const onOpenPlanner = vi.fn()
    render(<SearchView semester="Fall 2026" courses={[course]} tasks={[task]} libraryItems={library} reviews={[]} intakeCandidates={[candidate('candidate-1', 'Second Essay', 'resolved', 'resolved'), candidate('candidate-2', 'Old Applied Essay', 'proposed', 'applied')]} activity={[]} onOpenCourse={onOpenCourse} onOpenPlanner={onOpenPlanner} onOpenChanges={vi.fn()} onOpenActivity={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Search workspace'), { target: { value: 'Second Essay' } })
    expect(screen.getByText('Finish Second Essay')).toBeInTheDocument()
    expect(screen.getByText('Second Essay instructions.pdf')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /Open changes/ }).length).toBeGreaterThan(0)
    fireEvent.click(screen.getAllByRole('button', { name: /Open course/ })[0])
    expect(onOpenCourse).toHaveBeenCalledWith(course.id)
    fireEvent.click(screen.getByRole('button', { name: /Open planner/ }))
    expect(onOpenPlanner).toHaveBeenCalled()
  })

  it('does not surface applied intake history as an action', () => {
    render(<SearchView semester="Fall 2026" courses={[course]} tasks={[task]} libraryItems={library} reviews={[]} intakeCandidates={[candidate('candidate-2', 'Old Applied Essay', 'proposed', 'applied')]} activity={[]} onOpenCourse={vi.fn()} onOpenPlanner={vi.fn()} onOpenChanges={vi.fn()} onOpenActivity={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Search workspace'), { target: { value: 'Old Applied Essay' } })
    expect(screen.getByText('No matches in Fall 2026')).toBeInTheDocument()
  })

  it('includes semester-level inbox files and opens a read-only preview', () => {
    const semesterItem = { ...library[0], id: 'file-2', name: 'Semester announcement.md', relative_path: 'Fall 2026/00_INBOX/Semester announcement.md', course_id: null }
    render(<SearchView semester="Fall 2026" courses={[course]} tasks={[task]} libraryItems={[...library, semesterItem]} reviews={[]} intakeCandidates={[]} activity={[]} onOpenCourse={vi.fn()} onOpenPlanner={vi.fn()} onOpenChanges={vi.fn()} onOpenActivity={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Search workspace'), { target: { value: 'Semester announcement' } })
    fireEvent.click(screen.getByRole('button', { name: /Preview file/ }))
    expect(screen.getByRole('heading', { name: 'Semester announcement.md' })).toBeInTheDocument()
  })
})
