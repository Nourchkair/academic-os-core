import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Tasks } from './App'
import { api } from './lib/api'
import type { Course, Task } from './types'

vi.mock('./lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./lib/api')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      createTask: vi.fn(),
      updateTask: vi.fn(),
      completeTask: vi.fn(),
      reopenTask: vi.fn(),
      courseworkHistory: vi.fn().mockResolvedValue([]),
      addCourseworkHistory: vi.fn(),
      updateCourseworkHistory: vi.fn(),
    },
  }
})

const course: Course = {
  id: 'POL 2103 - Politics',
  code: 'POL 2103',
  name: 'POL 2103 - Politics',
  path: '/workspace/Fall 2026/POL 2103 - Politics',
  inbox_count: 0,
  material_count: 3,
  review_required: false,
}

const userTask: Task = {
  id: 'task:one',
  task_id: 'one',
  title: 'Draft the essay outline',
  completed: false,
  course: 'POL 2103 - Politics',
  source: 'Fall 2026/SEMESTER_TASKS.md',
  source_location: 'task:one',
  confidence: 'user-confirmed',
  kind: 'user_task',
  user_task: true,
  due_date: '2026-11-20',
  due_time: '09:30',
  status: 'open',
}

const derivedTask: Task = {
  id: 'derived:one',
  title: 'Read Week 4',
  completed: false,
  course: 'POL 2103 - Politics',
  source: 'Fall 2026/POL 2103 - Politics/01_COURSE/Course_Status.md',
  confidence: 'unverified',
}

function renderTasks(tasks: Task[], stateError: string | null = null, onChanged = vi.fn().mockResolvedValue(undefined)) {
  render(<Tasks tasks={tasks} courses={[course]} semester="Fall 2026" timezone="UTC" stateError={stateError} onNavigate={vi.fn()} onChanged={onChanged} />)
  return onChanged
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('Tasks', () => {
  it('completes a personal task without touching course history', async () => {
    const onChanged = renderTasks([userTask])
    fireEvent.click(screen.getByRole('button', { name: 'Mark done' }))
    await waitFor(() => expect(api.completeTask).toHaveBeenCalledWith('Fall 2026', 'one'))
    expect(api.createTask).not.toHaveBeenCalled()
    expect(api.addCourseworkHistory).not.toHaveBeenCalled()
    expect(onChanged).toHaveBeenCalled()
    expect(screen.getByText(/Your task/)).toBeTruthy()
  })

  it('reopens a completed personal task', async () => {
    renderTasks([{ ...userTask, completed: true, status: 'done' }])
    fireEvent.click(screen.getByRole('button', { name: 'Reopen' }))
    await waitFor(() => expect(api.reopenTask).toHaveBeenCalledWith('Fall 2026', 'one'))
  })

  it('creates a personal task with an optional course and due date', async () => {
    renderTasks([])
    fireEvent.click(screen.getByRole('button', { name: 'Add task' }))
    fireEvent.change(screen.getByLabelText('Task'), { target: { value: 'Plan the week' } })
    fireEvent.change(screen.getByLabelText(/Course/), { target: { value: course.id } })
    fireEvent.change(screen.getByLabelText(/Due date/), { target: { value: '2026-11-21' } })
    fireEvent.change(screen.getByLabelText(/Due time/), { target: { value: '14:00' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add task' }))
    await waitFor(() => expect(api.createTask).toHaveBeenCalledWith('Fall 2026', {
      title: 'Plan the week',
      course_id: course.id,
      due_date: '2026-11-21',
      due_time: '14:00',
    }))
  })

  it('edits a personal task and sends explicit clears', async () => {
    renderTasks([userTask])
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }))
    fireEvent.change(screen.getByLabelText('Task'), { target: { value: 'Revised outline' } })
    fireEvent.change(screen.getByLabelText(/Course/), { target: { value: '' } })
    fireEvent.change(screen.getByLabelText(/Due date/), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save task' }))
    await waitFor(() => expect(api.updateTask).toHaveBeenCalledWith('Fall 2026', 'one', {
      title: 'Revised outline',
      course_id: null,
      due_date: null,
      due_time: null,
    }))
  })

  it('keeps derived course tasks on the coursework-history path', async () => {
    renderTasks([derivedTask])
    fireEvent.click(screen.getByRole('button', { name: 'Mark done' }))
    expect(api.completeTask).not.toHaveBeenCalled()
    expect(await screen.findByRole('button', { name: 'Skip grade' })).toBeTruthy()
  })

  it('surfaces a malformed task block without offering personal-task writes', () => {
    renderTasks([], 'the SEMESTER_TASKS.md task block is not valid JSON')
    expect(screen.getByRole('alert').textContent).toContain('not valid JSON')
    expect(screen.getByRole('button', { name: 'Add task' })).toBeDisabled()
    expect(screen.queryByText('Draft the essay outline')).toBeNull()
  })
})
