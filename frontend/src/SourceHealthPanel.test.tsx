import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { SourceHealthPanel } from './SourceHealthPanel'
import type { SourceHealthCourse } from './types'

const health: SourceHealthCourse = {
  course_id: 'POL 2103 - Politics',
  course_name: 'Politics',
  assigned_readings: 2,
  linked_sources: 1,
  readable_sources: 1,
  readings_completed: 1,
  unverified_readings: 1,
  stale_sources: 0,
  missing_sources: 1,
  coverage_percent: 50,
  readings: [
    { reading_id: 'reading-1', title: 'Week 4 Reading', author: 'A. Author', chapter: '4', pages: '1–20', required: true, verification_result: 'EXACT MATCH — HIGH CONFIDENCE', source_id: 'Fall 2026/POL 2103 - Politics/05_REFERENCE/week-4.md', source_name: 'week-4.md', category: 'readings', processing_status: 'ACKNOWLEDGED', extraction_status: 'supported', readable: true, stale: false, read_status: 'read', read_updated_at: '2026-11-18T09:00:00Z', exam_ids: ['exam-1'] },
  ],
  exams: [{ exam_id: 'exam-1', title: 'Midterm', date: '2026-11-25', topic_count: 2, covered_topics: 1, uncovered_topics: ['Federalism'], source_count: 1, sources: [{ source_id: 'Fall 2026/POL 2103 - Politics/05_REFERENCE/week-4.md', name: 'week-4.md', available: true, readable: true, read_status: 'read', stale: false }], coverage_percent: 50 }],
  sync: { syllabus: [{ source_id: 'syllabus-1', name: 'Syllabus.pdf', relative_path: 'Fall 2026/POL 2103 - Politics/01_COURSE/Syllabus.pdf', status: 'changed', linked_entities: 3 }], pending_intake: 1 },
}

describe('SourceHealthPanel', () => {
  it('shows reading, exam, and syllabus coverage and records student status', () => {
    const onMark = vi.fn().mockResolvedValue(undefined)
    render(<SourceHealthPanel health={health} loading={false} busy={false} onMark={onMark} />)
    expect(screen.getByText('Week 4 Reading')).toBeInTheDocument()
    expect(screen.getByText('Exact match')).toBeInTheDocument()
    expect(screen.getByText('Not yet recorded: Federalism')).toBeInTheDocument()
    expect(screen.getByText('Changed · review extraction')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Unread' }))
    expect(onMark).toHaveBeenCalledWith(expect.objectContaining({ reading_id: 'reading-1' }), 'unread')
  })
})
