import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { HomeView } from './HomeView'
import type { Course, ProcessingRecord, StatusPayload, Task } from './types'

const course: Course = {
  id: 'POL 2103 - Politics',
  code: 'POL 2103',
  name: 'POL 2103 - Politics',
  path: '/workspace/Fall 2026/POL 2103 - Politics',
  inbox_count: 0,
  material_count: 3,
  review_required: false,
}

const task: Task = {
  id: 'task-1',
  title: 'Read Week 4',
  completed: false,
  course: 'POL 2103 - Politics',
  source: 'Course_Status.md',
  confidence: 'unverified',
  due_date: '2026-11-12',
}

const inboxItem: ProcessingRecord = {
  id: 'processing-1',
  source_path: '/workspace/Fall 2026/POL 2103 - Politics/00_INBOX/lecture.pdf',
  signature: 'signature',
  status: 'PENDING',
  detected_at: '2026-11-11T00:00:00Z',
  updated_at: '2026-11-11T00:00:00Z',
  retry_count: 0,
}

const status: StatusPayload = {
  version: '0.4.10',
  profile: '/profile.json',
  student: { name: 'Alex Student', institution: 'Example University', program: 'History' },
  workspace: {
    academic_root: '/workspace',
    semester: 'Fall 2026',
    available_semesters: ['Fall 2026'],
    timezone: 'UTC',
    student: { name: 'Alex Student', institution: 'Example University', program: 'History' },
    courses: [course],
    tasks: [],
    today: { exists: false, lines: [], path: '/workspace/Fall 2026/TODAY.md' },
    material_count: 3,
    inbox_count: 1,
    review_count: 1,
    workspace_exists: true,
  },
  review_count: 2,
  recent_activity: [],
  agents: {},
  acquisition: { watched_folders: [], browser: { enabled: false, allowed_sites: [] } },
}

afterEach(() => {
  vi.useRealTimers()
})

describe('HomeView', () => {
  it('shows verified deadlines, open tasks, review decisions, and intake', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-11-11T12:00:00Z'))
    const onNavigate = vi.fn()

    render(
      <HomeView
        status={status}
        courses={[course]}
        tasks={[task]}
        activity={[]}
        inbox={[inboxItem]}
        semester="Fall 2026"
        semesters={['Fall 2026']}
        loading={false}
        onSemesterChange={vi.fn().mockResolvedValue(undefined)}
        onOpenCourse={vi.fn()}
        onOpenIntake={vi.fn()}
        onNavigate={onNavigate}
      />,
    )

    expect(screen.getByRole('heading', { name: 'Good afternoon, Alex' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Read Week 4' })).toBeInTheDocument()
    expect(screen.getByText('Open decisions')).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()
    expect(screen.getByText('Waiting for your input')).toBeInTheDocument()
    expect(screen.getByText('Items need review or processing')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /View tasks/ }))
    expect(onNavigate).toHaveBeenCalledWith('tasks')
  })

  it('warns when the selected semester is absent from the workspace', () => {
    render(
      <HomeView
        status={status}
        courses={[]}
        tasks={[]}
        activity={[]}
        inbox={[]}
        semester="Winter 2027"
        semesters={['Fall 2026']}
        loading={false}
        onSemesterChange={vi.fn().mockResolvedValue(undefined)}
        onOpenCourse={vi.fn()}
        onOpenIntake={vi.fn()}
        onNavigate={vi.fn()}
      />,
    )

    expect(screen.getByText('Winter 2027 is not present in this workspace')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Open Settings/ })).toBeInTheDocument()
  })
})
