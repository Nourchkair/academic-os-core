import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { SearchView } from './SearchView'
import type { Course, Task } from './types'

const course: Course = { id: 'POL 2103 - Politics', code: 'POL 2103', name: 'POL 2103 - Politics', path: '/workspace/Fall 2026/POL 2103 - Politics', inbox_count: 0, material_count: 3, review_required: false }
const task: Task = { id: 'task-1', title: 'Finish Second Essay', completed: false, course: course.id, source: 'Fall 2026/SEMESTER_TASKS.md', confidence: 'user-confirmed', due_date: '2026-11-24', user_task: true }
const library = [{ id: 'file-1', name: 'Second Essay instructions.pdf', path: '/workspace/Fall 2026/POL 2103 - Politics/00_INBOX/Second Essay instructions.pdf', relative_path: 'Fall 2026/POL 2103 - Politics/00_INBOX/Second Essay instructions.pdf', semester: 'Fall 2026', course_id: course.id, category: 'assessments' as const, extension: '.pdf', size: 100, modified_at: '' }]

describe('SearchView', () => {
  it('finds tasks, courses, and library material and opens the right surface', () => {
    const onOpenCourse = vi.fn()
    const onOpenPlanner = vi.fn()
    render(<SearchView semester="Fall 2026" courses={[course]} tasks={[task]} libraryItems={library} reviews={[]} intakeCandidates={[]} activity={[]} onOpenCourse={onOpenCourse} onOpenPlanner={onOpenPlanner} onOpenChanges={vi.fn()} onOpenActivity={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Search workspace'), { target: { value: 'Second Essay' } })
    expect(screen.getByText('Finish Second Essay')).toBeInTheDocument()
    expect(screen.getByText('Second Essay instructions.pdf')).toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button', { name: /Open course/ })[0])
    expect(onOpenCourse).toHaveBeenCalledWith(course.id)
    fireEvent.click(screen.getByRole('button', { name: /Open planner/ }))
    expect(onOpenPlanner).toHaveBeenCalled()
  })
})
