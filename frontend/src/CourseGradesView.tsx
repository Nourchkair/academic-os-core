import { useEffect, useState } from 'react'
import { api } from './lib/api'
import { gradeParts } from './lib/grades'
import type { Course, CourseworkHistoryRecord, Task } from './types'

const kindLabels: Record<string, string> = {
  assignment: 'Assignment',
  essay: 'Essay',
  project: 'Project',
  exam: 'Exam',
  presentation: 'Presentation',
  quiz: 'Quiz',
  other: 'Other',
}

const statusLabels: Record<string, string> = {
  planned: 'Planned',
  in_progress: 'In progress',
  submitted: 'Submitted',
  graded: 'Graded',
  completed: 'Completed',
}

type GradeFilter = 'all' | 'graded' | 'awaiting'

function hasGrade(record: CourseworkHistoryRecord): boolean {
  return Boolean((record.grade || record.score || record.percentage || record.letter_grade || '').trim())
}

function normalized(value: string): string {
  return value.toLocaleLowerCase().replace(/[^a-z0-9]/g, '')
}

function recordDate(record: CourseworkHistoryRecord): string {
  return record.submitted_on || record.due_date || record.created_at
}

function formatDate(value: string): string {
  const date = new Date(`${value.slice(0, 10)}T12:00:00`)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

export function CourseGradesView({ course, semester, onOpenHistory }: { course: Course; semester: string; onOpenHistory: () => void }) {
  const [records, setRecords] = useState<CourseworkHistoryRecord[]>([])
  const [tasks, setTasks] = useState<Task[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<GradeFilter>('all')

  useEffect(() => {
    let active = true
    setLoading(true)
    setError(null)
    void Promise.all([
      api.courseworkHistory(course.id, semester),
      api.tasks(semester).catch(() => ({ tasks: [] })),
    ]).then(([history, taskPayload]) => {
      if (!active) return
      setRecords(history)
      const courseKeys = new Set([course.id, course.name, `${course.code} - ${course.name}`, course.code])
      setTasks((taskPayload.tasks || []).filter((task) => courseKeys.has(task.course || '')))
    }).catch((reason) => {
      if (active) setError(String(reason))
    }).finally(() => {
      if (active) setLoading(false)
    })
    return () => { active = false }
  }, [course.id, course.name, semester])

  const graded = records.filter(hasGrade)
  const awaiting = records.filter((record) => !hasGrade(record))
  const visible = (filter === 'graded' ? graded : filter === 'awaiting' ? awaiting : records)
    .slice()
    .sort((a, b) => Number(hasGrade(b)) - Number(hasGrade(a)) || recordDate(b).localeCompare(recordDate(a)))

  const weightFor = (record: CourseworkHistoryRecord): string | null => {
    const key = normalized(record.task_title || record.title)
    return tasks.find((task) => normalized(task.title) === key)?.weight || null
  }

  return <section className="course-grades">
    <div className="course-grades-heading">
      <div>
        <p className="eyebrow">Recorded results</p>
        <h3>Grades</h3>
        <p>Grade history recorded locally for {course.code}. It is not an official transcript, and Academia does not calculate a final course grade.</p>
      </div>
      <button className="secondary-button" type="button" onClick={onOpenHistory}>Manage in History</button>
    </div>

    <div className="course-grades-summary" aria-label="Grade record summary">
      <div><span>Graded records</span><strong>{graded.length}</strong><small>with a recorded grade</small></div>
      <div><span>No grade yet</span><strong>{awaiting.length}</strong><small>records without a recorded grade</small></div>
      <div><span>Assessment types</span><strong>{new Set(graded.map((record) => record.kind)).size}</strong><small>represented in your grades</small></div>
    </div>

    <div className="course-grades-toolbar">
      <div className="course-grades-filters" role="group" aria-label="Filter grade history">
        <button type="button" className={filter === 'all' ? 'active' : ''} aria-pressed={filter === 'all'} onClick={() => setFilter('all')}>All <span>{records.length}</span></button>
        <button type="button" className={filter === 'graded' ? 'active' : ''} aria-pressed={filter === 'graded'} onClick={() => setFilter('graded')}>Graded <span>{graded.length}</span></button>
        <button type="button" className={filter === 'awaiting' ? 'active' : ''} aria-pressed={filter === 'awaiting'} onClick={() => setFilter('awaiting')}>No grade yet <span>{awaiting.length}</span></button>
      </div>
      <p className="course-grades-note">Grades and weights are exactly as recorded. Missing records stay missing; do not treat this as a complete gradebook.</p>
    </div>

    {error ? <p className="setup-error" role="alert">{error}</p> : loading ? <p className="muted-copy" role="status">Loading {course.code} grade records…</p> : visible.length ? <div className="course-grades-list">
      {visible.map((record) => {
        const parts = gradeParts(record)
        const recordedGrade = Boolean(parts.score || parts.percentage || parts.letter)
        const weight = weightFor(record)
        return <article className={`course-grade-row ${recordedGrade ? 'graded' : ''}`} key={record.id}>
          <div className="course-grade-main">
            <div className="course-grade-heading"><span className="history-kind">{kindLabels[record.kind] || record.kind}</span><h4>{record.title}</h4></div>
            <div className="course-grade-meta">
              <span className={`history-status status-${record.status}`}>{statusLabels[record.status] || record.status}</span>
              {record.due_date && <span>Due {formatDate(record.due_date)}</span>}
              {record.submitted_on && <span>Submitted {formatDate(record.submitted_on)}</span>}
              {weight && <span>Weight {weight}</span>}
            </div>
            {record.notes && <p className="course-grade-notes">{record.notes}</p>}
          </div>
          <div className="course-grade-result">
            {parts.score ? <strong className="grade-score">{parts.score}</strong> : null}
            {parts.percentage ? <span className="grade-percentage">{parts.percentage}</span> : null}
            {parts.letter ? <b className="grade-letter">{parts.letter}</b> : null}
            {!recordedGrade && <span>Not recorded</span>}
            <small>{record.record_basis === 'user-confirmed' ? 'Student-recorded' : record.record_basis}</small>
          </div>
        </article>
      })}
    </div> : <article className="course-material-empty">
      <strong>{records.length ? 'No records match this filter' : 'No grade records yet'}</strong>
      <p>{records.length ? 'Choose another filter to see the rest of the course history.' : 'Add an assignment, essay, exam, or other coursework in History, then record its grade there.'}</p>
      <button type="button" className="secondary-button" onClick={onOpenHistory}>{records.length ? 'Open History' : 'Add the first record'} <span>→</span></button>
    </article>}
  </section>
}
