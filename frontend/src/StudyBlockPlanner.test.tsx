import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { StudyBlockPlanner } from './StudyBlockPlanner'
import { api } from './lib/api'
import type { StudySchedulePayload } from './types'

vi.mock('./lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./lib/api')>()
  return {
    ...actual,
    api: { ...actual.api, studySchedule: vi.fn(), proposeGoogleCalendarCreate: vi.fn() },
  }
})

const schedule: StudySchedulePayload = {
  schema_version: 1,
  generated_at: '2026-11-18T09:00:00-05:00',
  timezone: 'America/Toronto',
  window: { start_date: '2026-11-18', days: 7, start_time: '09:00', end_time: '21:00' },
  minutes_requested: 120,
  minutes_scheduled: 45,
  blocks: [{
    id: 'block-1', course_id: 'POL 2103 - Politics', course_name: 'Politics', title: 'Review sovereignty',
    reason: '3 practice items are due', action: 'review', minutes: 30,
    start: '2026-11-18T09:00:00-05:00', end: '2026-11-18T09:30:00-05:00',
    summary: 'POL 2103 study block', description: 'Advisory study block', source: 'academia_study_schedule',
  }],
  unscheduled: [],
  calendar_checked: true,
  calendar_error: null,
  advisory: true,
  calendar_changes: false,
  note: 'Nothing is added to Google Calendar until the student approves a Review proposal.',
}

describe('StudyBlockPlanner', () => {
  it('shows blocks and creates a Review proposal without writing to the calendar', async () => {
    vi.mocked(api.studySchedule).mockResolvedValue(schedule)
    vi.mocked(api.proposeGoogleCalendarCreate).mockResolvedValue({ proposal: { id: 'proposal-1' }, review: { id: 'review-1' }, next_step: 'review' } as never)
    const onOpenReview = vi.fn()
    render(<StudyBlockPlanner semester="Fall 2026" onOpenSettings={vi.fn()} onOpenReview={onOpenReview} />)
    expect(await screen.findByText('Review sovereignty')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Add to Calendar' }))
    await waitFor(() => expect(api.proposeGoogleCalendarCreate).toHaveBeenCalledWith({
      summary: 'POL 2103 study block',
      start: '2026-11-18T09:00:00-05:00',
      end: '2026-11-18T09:30:00-05:00',
      description: 'Advisory study block',
    }))
    expect(onOpenReview).toHaveBeenCalledWith('review-1')
    expect(api.studySchedule).toHaveBeenCalled()
  })
})

  it('does not propose calendar events when the connector is missing', async () => {
    vi.mocked(api.studySchedule).mockResolvedValue({ ...schedule, calendar_checked: false, calendar_error: 'Google Calendar is not connected; blocks were placed without calendar conflict checks.' })
    vi.mocked(api.proposeGoogleCalendarCreate).mockClear()
    render(<StudyBlockPlanner semester="Fall 2026" onOpenSettings={vi.fn()} onOpenReview={vi.fn()} />)
    expect(await screen.findByText(/Google Calendar is not connected/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add to Calendar' })).toBeDisabled()
    expect(api.proposeGoogleCalendarCreate).not.toHaveBeenCalled()
  })
