import { useEffect, useState } from 'react'
import { CourseCard } from './CourseCard'
import { SemesterPicker } from './SemesterPicker'
import { getTaskUrgency, urgencyLabel } from './lib/task-urgency'
import type { ActivityEvent, Course, ProcessingRecord, StatusPayload, Task } from './types'

type HomeViewProps = {
  status: StatusPayload | null
  courses: Course[]
  tasks: Task[]
  activity: ActivityEvent[]
  inbox: ProcessingRecord[]
  semester: string
  semesters: string[]
  loading: boolean
  onSemesterChange: (semester: string) => Promise<void>
  onOpenCourse: (courseId: string) => void
  onOpenIntake: () => void
  onNavigate: (view: 'tasks' | 'activity' | 'settings') => void
}

export function HomeView({ status, courses, tasks, activity, inbox, semester, semesters, loading, onSemesterChange, onOpenCourse, onOpenIntake, onNavigate }: HomeViewProps) {
  const timezone = status?.workspace.timezone || 'America/Toronto'
  const today = localDate(timezone)
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 30_000)
    return () => window.clearInterval(timer)
  }, [])

  const weekEndDate = new Date(`${today}T12:00:00Z`)
  weekEndDate.setUTCDate(weekEndDate.getUTCDate() + 7)
  const weekEnd = weekEndDate.toISOString().slice(0, 10)
  const weekTasks = tasks
    .filter((task) => !task.completed && Boolean(task.due_date && task.due_date >= today && task.due_date <= weekEnd))
    .sort((a, b) => (a.due_date || '9999').localeCompare(b.due_date || '9999') || (a.due_time || '').localeCompare(b.due_time || '') || a.title.localeCompare(b.title))
  const nextDeadline = tasks
    .filter((task) => !task.completed && Boolean(task.due_date && task.due_date >= today))
    .sort((a, b) => (a.due_date || '9999').localeCompare(b.due_date || '9999') || (a.due_time || '').localeCompare(b.due_time || '') || a.title.localeCompare(b.title))[0]
  const nextDeadlineUrgency = nextDeadline ? getTaskUrgency(nextDeadline, timezone, now) : 'upcoming'
  const pendingInbox = inbox.filter((item) => item.status !== 'ACKNOWLEDGED')
  const firstName = (status?.student.name || 'there').split(' ')[0]
  const hour = Number(new Intl.DateTimeFormat('en', { hour: 'numeric', hourCycle: 'h23', timeZone: timezone }).format(now))
  const greeting = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening'
  const dateLabel = new Intl.DateTimeFormat(undefined, { timeZone: timezone, weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' }).format(now)
  const timeLabel = new Intl.DateTimeFormat(undefined, { timeZone: timezone, hour: 'numeric', minute: '2-digit' }).format(now)
  const activeSemesterMissing = Boolean(status && status.workspace.available_semesters.length > 0 && !status.workspace.available_semesters.includes(semester))

  return <div className="home-dashboard">
    {activeSemesterMissing && <section className="data-note warning"><div className="data-note-icon">i</div><div><p className="eyebrow">Workspace</p><h3>{semester} is not present in this workspace</h3><p>Choose a semester that exists in the configured workspace.</p></div><button className="secondary-button" onClick={() => onNavigate('settings')}>Open Settings <span>→</span></button></section>}

    <section className="home-greeting" aria-label="Today's greeting">
      <div className="home-greeting-copy"><p className="eyebrow">{dateLabel}</p><h1>{greeting}, {firstName}</h1><p>Here’s what needs your attention this week.</p></div>
      <time className="home-clock" dateTime={now.toISOString()}><strong>{timeLabel}</strong><span>{status?.workspace.timezone || 'Local time'}</span></time>
    </section>

    <section className="home-deadline" data-tone={nextDeadlineUrgency} aria-label="Next deadline">
      <div className="home-deadline-mark" aria-hidden="true">◷</div>
      <div className="home-deadline-copy"><p className="eyebrow">Next deadline <span className="status-pill deadline-status">{nextDeadline ? urgencyLabel(nextDeadlineUrgency) : 'Clear'}</span></p>{nextDeadline ? <><h2>{nextDeadline.title}</h2><p>{nextDeadline.course || 'Semester'} · {formatDue(nextDeadline)}</p></> : <><h2>No upcoming deadlines recorded</h2><p>You’re clear for the next 7 days.</p></>}</div>
      <button className="home-deadline-link" onClick={() => onNavigate('tasks')}>View tasks <span>→</span></button>
    </section>

    <section className="home-classes-section">
      <div className="home-section-heading"><div><p className="eyebrow">Current session</p><h2>Your classes</h2></div><SemesterPicker semester={semester} semesters={semesters} loading={loading} onSemesterChange={onSemesterChange} /></div>
      <div className="course-browser-grid home-course-grid">
        {courses.map((course) => <CourseCard key={course.id} course={course} onOpen={() => onOpenCourse(course.id)} />)}
        {!courses.length && <article className="home-empty-classes"><strong>No classes in {semester || 'this semester'} yet</strong><p>Import a syllabus or choose another semester to see its classes here.</p><button className="secondary-button" onClick={onOpenIntake}>Add a syllabus <span>＋</span></button></article>}
      </div>
    </section>

    <div className="home-focus-layout">
      <section className="home-week-panel">
        <div className="home-section-heading compact"><div><p className="eyebrow">Next 7 days</p><h2>Open tasks</h2></div><span className="home-count" data-tone={weekTasks.length ? getTaskUrgency(weekTasks[0], timezone, now) : 'completed'}>{weekTasks.length}</span></div>
        <div className="home-week-list">{weekTasks.map((task) => { const urgency = getTaskUrgency(task, timezone, now); return <button className="home-week-task" data-tone={urgency} key={task.id} onClick={() => onNavigate('tasks')}><span className="home-week-task-date">{task.due_date ? shortDate(task.due_date) : ''}</span><span className="home-week-task-copy"><strong>{task.title}</strong><small>{task.course || 'Semester'}{task.weight ? ` · ${task.weight}` : ''}</small></span><span className="home-week-task-arrow" aria-hidden="true">→</span></button> })}{!weekTasks.length && <p className="home-empty-note">No open tasks are due within the next 7 days.</p>}</div>
        <button className="home-inline-link" onClick={() => onNavigate('tasks')}>See all tasks <span>→</span></button>
      </section>

      <div className="home-attention-column">
        <section className="home-attention-card" data-tone={status?.review_count ? 'soon' : 'completed'}><div className="home-attention-icon" aria-hidden="true">!</div><div><p className="eyebrow">Open decisions</p><strong>{status?.review_count ?? 0}</strong><span>{status?.review_count ? 'Waiting for your input' : 'Nothing waiting for a decision'}</span></div></section>
        <button type="button" className="home-attention-card home-attention-action" data-tone={pendingInbox.length ? 'soon' : 'completed'} onClick={() => onNavigate('activity')}><div className="home-attention-icon" aria-hidden="true">↓</div><div><p className="eyebrow">Intake</p><strong>{pendingInbox.length}</strong><span>{pendingInbox.length ? 'Items need review or processing' : 'No pending intake items'}</span></div><span className="home-attention-arrow" aria-hidden="true">→</span></button>
      </div>
    </div>

    {activity.length > 0 && <section className="home-recent-activity"><div className="home-section-heading compact"><div><p className="eyebrow">Workspace</p><h2>Recent activity</h2></div><button className="home-inline-link" onClick={() => onNavigate('activity')}>View all <span>→</span></button></div><div className="home-recent-list">{activity.slice(0, 4).map((event) => <div className="home-recent-row" key={event.id}><span className="activity-dot" /><div><strong>{event.title}</strong><small>{event.course || 'Workspace'}</small></div><time>{formatActivityDate(event.created_at)}</time></div>)}</div></section>}
  </div>
}

function localDate(timezone: string) { return new Intl.DateTimeFormat('en-CA', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date()) }
function shortDate(value: string) { const date = new Date(`${value.slice(0, 10)}T12:00:00Z`); return new Intl.DateTimeFormat(undefined, { timeZone: 'UTC', weekday: 'short', month: 'short', day: 'numeric' }).format(date) }
function formatDue(task: Task) { if (!task.due_date) return 'Date to confirm'; return `Due ${shortDate(task.due_date)}${task.due_time ? ` · ${task.due_time}` : ''}` }
function formatActivityDate(value: string) { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) }
