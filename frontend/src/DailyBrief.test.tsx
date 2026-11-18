import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { DailyBrief } from './DailyBrief'
import { api } from './lib/api'
import type { DailyBriefPayload } from './types'

vi.mock('./lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./lib/api')>()
  return { ...actual, api: { ...actual.api, brief: vi.fn() } }
})

const brief: DailyBriefPayload = {
  schema_version: 1,
  generated_at: '2026-11-18T09:00:00-05:00',
  date: '2026-11-18',
  timezone: 'America/Toronto',
  semester: 'Fall 2026',
  student: 'Alex Student',
  headline: '2 things need attention',
  priorities: [
    { kind: 'review', title: 'Essay deadline needs a decision', detail: 'Waiting for your decision', action: 'changes' },
    { kind: 'task', title: 'Read Week 5', detail: 'Due 2026-11-19', action: 'planner' },
  ],
  deadlines: [],
  open_tasks: [],
  decisions: { reviews: 1, intake: 1, processing: 0, failed_processing: 0 },
  study: { due_count: 3, courses: [], exams: [], blocks: [{ id: 'block-1', course_id: 'POL 2103', course_name: 'Politics', title: 'Review sovereignty', reason: '3 items due', action: 'review', minutes: 15, start: '2026-11-18T09:00:00-05:00', end: '2026-11-18T09:15:00-05:00', summary: 'POL 2103 study block', description: 'Advisory block', source: 'academia_study_schedule' }] },
  sources: {
    schema_version: 1,
    generated_at: '2026-11-18T09:00:00-05:00',
    semester: 'Fall 2026',
    courses: [],
    totals: { assigned_readings: 2, linked_sources: 1, readable_sources: 1, readings_completed: 1, unverified_readings: 1, stale_sources: 0, missing_sources: 1, coverage_percent: 50, pending_intake: 1, syllabus_changed: 0, syllabus_not_applied: 0 },
    notes: [],
  },
  advisory: true,
  note: 'This brief is derived from recorded local data.',
}

describe('DailyBrief', () => {
  it('shows priorities, metrics, and navigates to the matching surface', async () => {
    vi.mocked(api.brief).mockResolvedValue(brief)
    const onNavigate = vi.fn()
    render(<DailyBrief semester="Fall 2026" onNavigate={onNavigate} />)
    expect(await screen.findByRole('heading', { name: '2 things need attention' })).toBeInTheDocument()
    expect(screen.getByText('Essay deadline needs a decision')).toBeInTheDocument()
    expect(screen.getByText('readings read')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Essay deadline needs a decision/ }))
    expect(onNavigate).toHaveBeenCalledWith('changes')
    fireEvent.click(screen.getByRole('button', { name: /Plan the week/ }))
    expect(onNavigate).toHaveBeenCalledWith('planner')
    await waitFor(() => expect(api.brief).toHaveBeenCalledWith('Fall 2026'))
  })
})
