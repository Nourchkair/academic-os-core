import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { LibraryPreviewDialog } from './LibraryPreviewDialog'
import { isPendingIntakeCandidate } from './lib/intake'
import type { ActivityEvent, Course, IntakeCandidate, LibraryItem, ReviewItem, Task } from './types'

type SearchViewProps = {
  semester: string
  courses: Course[]
  tasks: Task[]
  libraryItems: LibraryItem[]
  reviews: ReviewItem[]
  intakeCandidates: IntakeCandidate[]
  activity: ActivityEvent[]
  onOpenCourse: (courseId: string) => void
  onOpenPlanner: () => void
  onOpenChanges: () => void
  onOpenActivity: () => void
}

export function SearchView({ semester, courses, tasks, libraryItems, reviews, intakeCandidates, activity, onOpenCourse, onOpenPlanner, onOpenChanges, onOpenActivity }: SearchViewProps) {
  const [query, setQuery] = useState('')
  const [previewItem, setPreviewItem] = useState<LibraryItem | null>(null)
  const normalized = query.trim().toLowerCase()
  const results = useMemo(() => {
    if (!normalized) return null
    const matches = (value: unknown) => String(value || '').toLowerCase().includes(normalized)
    return {
      courses: courses.filter((course) => matches(course.code) || matches(course.name)).slice(0, 6),
      tasks: tasks.filter((task) => matches(task.title) || matches(task.course) || matches(task.source)).slice(0, 8),
      library: libraryItems.filter((item) => matches(item.name) || matches(item.relative_path) || matches(item.category)).slice(0, 8),
      changes: [
        ...reviews.filter((item) => matches(item.title) || matches(item.course) || matches(item.kind)).map((item) => ({ id: item.id, title: item.title, detail: item.course || item.kind, kind: 'Review decision' })),
        ...intakeCandidates.filter((candidate) => isPendingIntakeCandidate(candidate) && (matches(candidate.entity_title) || matches(candidate.course_id) || matches(candidate.value))).map((candidate) => ({ id: candidate.id, title: candidate.entity_title || 'Intake candidate', detail: `${candidate.course_id || 'Course not resolved'} · ${candidate.display_status || candidate.status}`, kind: 'Intake candidate' })),
      ].slice(0, 8),
      activity: activity.filter((event) => matches(event.title) || matches(event.course)).slice(0, 8),
    }
  }, [activity, courses, intakeCandidates, libraryItems, normalized, reviews, tasks])
  const count = results ? results.courses.length + results.tasks.length + results.library.length + results.changes.length + results.activity.length : 0

  return <div className="page-stack search-workspace">
    <section className="page-intro"><p className="eyebrow">Search</p><h2>Find anything in this semester</h2><p>Search courses, deadlines, tasks, library material, intake candidates, decisions, and Activity.</p></section>
    <label className="global-search"><span aria-hidden="true">⌕</span><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search courses, files, tasks, changes…" aria-label="Search workspace" /></label>
    {!normalized && <p className="search-hint">Type a course, file, deadline, task, or change.</p>}
    {normalized && !count && <article className="empty-card"><div className="empty-mark">⌕</div><h3>No matches in {semester}</h3><p>Try a shorter phrase, a course code, or a file name.</p></article>}
    {results && count > 0 && <div className="search-results">
      {results.courses.length > 0 && <SearchGroup title="Courses">{results.courses.map((course) => <SearchResult key={course.id} title={course.name} detail={`${course.code} · ${course.material_count} material item${course.material_count === 1 ? '' : 's'}`} action="Open course" onClick={() => onOpenCourse(course.id)} />)}</SearchGroup>}
      {results.tasks.length > 0 && <SearchGroup title="Planner">{results.tasks.map((task) => <SearchResult key={task.id} title={task.title} detail={`${task.course || 'Semester'}${task.due_date ? ` · due ${task.due_date}` : ''}`} action="Open planner" onClick={onOpenPlanner} />)}</SearchGroup>}
      {results.library.length > 0 && <SearchGroup title="Library">{results.library.map((item) => <SearchResult key={item.id} title={item.name} detail={`${item.relative_path} · ${item.category}`} action={item.course_id ? 'Open course' : 'Preview file'} onClick={() => item.course_id ? onOpenCourse(item.course_id) : setPreviewItem(item)} />)}</SearchGroup>}
      {results.changes.length > 0 && <SearchGroup title="Changes">{results.changes.map((item) => <SearchResult key={item.id} title={item.title} detail={`${item.kind} · ${item.detail}`} action="Open changes" onClick={onOpenChanges} />)}</SearchGroup>}
      {results.activity.length > 0 && <SearchGroup title="Activity">{results.activity.map((event) => <SearchResult key={event.id} title={event.title} detail={`${event.course || 'Workspace'} · ${event.event_type}`} action="Open activity" onClick={onOpenActivity} />)}</SearchGroup>}
    </div>}
    <LibraryPreviewDialog item={previewItem} onClose={() => setPreviewItem(null)} />
  </div>
}

function SearchGroup({ title, children }: { title: string; children: ReactNode }) {
  return <section className="search-group"><h3>{title}</h3><div className="search-group-list">{children}</div></section>
}

function SearchResult({ title, detail, action, onClick }: { title: string; detail: string; action: string; onClick: () => void }) {
  return <button type="button" className="search-result" onClick={onClick}><div><strong>{title}</strong><small>{detail}</small></div><span>{action} →</span></button>
}
