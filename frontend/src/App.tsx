import { useEffect, useState } from 'react'
import { api, BridgeUnavailableError } from './lib/api'
import type { ActivityEvent, Course, ReviewItem, StatusPayload, Task } from './types'

const nav = [
  { id: 'home', label: 'Home', icon: '⌂' },
  { id: 'courses', label: 'Courses', icon: '◫' },
  { id: 'tasks', label: 'Tasks', icon: '✓' },
  { id: 'library', label: 'Library', icon: '▤' },
  { id: 'review', label: 'Review', icon: '◌' },
  { id: 'settings', label: 'Settings', icon: '⚙' },
] as const

type View = typeof nav[number]['id']

function App() {
  const [view, setView] = useState<View>('home')
  const [status, setStatus] = useState<StatusPayload | null>(null)
  const [courses, setCourses] = useState<Course[]>([])
  const [tasks, setTasks] = useState<Task[]>([])
  const [reviews, setReviews] = useState<ReviewItem[]>([])
  const [activity, setActivity] = useState<ActivityEvent[]>([])
  const [error, setError] = useState<string | null>(null)
  const [actionBusy, setActionBusy] = useState<string | null>(null)

  const refresh = async () => {
    try {
      setError(null)
      const next = await api.status()
      setStatus(next)
      const [courseData, taskData, reviewData, activityData] = await Promise.all([api.courses(), api.tasks(), api.review(), api.activity()])
      setCourses(courseData)
      setTasks(taskData)
      setReviews(reviewData)
      setActivity(activityData)
    } catch (reason) {
      setError(reason instanceof BridgeUnavailableError ? reason.message : String(reason))
    }
  }

  // This effect starts the external CLI read; refresh owns the resulting loading/error state.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void refresh() }, [])

  const title = nav.find((item) => item.id === view)?.label ?? 'Home'
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><div className="brand-mark">A</div><div><strong>Academia</strong><span>OS</span></div></div>
        <div className="workspace-chip"><span className="status-dot" />Local workspace</div>
        <nav aria-label="Primary navigation">
          {nav.map((item) => <button key={item.id} className={`nav-item ${view === item.id ? 'active' : ''}`} onClick={() => setView(item.id)}><span className="nav-icon">{item.icon}</span>{item.label}{item.id === 'review' && status?.review_count ? <em>{status.review_count}</em> : null}</button>)}
        </nav>
        <div className="sidebar-bottom"><button className="agent-pill" onClick={() => setView('settings')}><span className="agent-avatar">✦</span><span><b>Agents optional</b><small>Manage connections</small></span><span className="chevron">›</span></button></div>
      </aside>
      <main className="main-content">
        <header className="topbar"><div><p className="eyebrow">{status?.workspace.semester ?? 'Local academic workspace'}</p><h1>{title}</h1></div><div className="top-actions"><button className="search-button" onClick={() => setError('Search will use the local Academia OS index when the desktop bridge is connected.')}><span>⌕</span> Search <kbd>⌘ K</kbd></button><button className="icon-button" aria-label="Refresh" onClick={() => void refresh()}>↻</button><div className="profile-badge">{status?.student.name?.slice(0, 1) ?? 'A'}</div></div></header>
        {error ? <ConnectionNotice message={error} onRetry={() => void refresh()} /> : <>{view === 'home' && <Home status={status} tasks={tasks} reviews={reviews} activity={activity} onNavigate={setView} />}{view === 'courses' && <Courses courses={courses} />}{view === 'tasks' && <Tasks tasks={tasks} />}{view === 'library' && <Library courses={courses} />}{view === 'review' && <Review reviews={reviews} activity={activity} actionBusy={actionBusy} onReviewAction={async (action, itemId) => { try { setActionBusy(itemId); setError(null); await api.reviewAction(action, itemId); await refresh() } catch (reason) { setError(String(reason)) } finally { setActionBusy(null) } }} />}{view === 'settings' && <Settings status={status} />}</>}
      </main>
    </div>
  )
}

function ConnectionNotice({ message, onRetry }: { message: string; onRetry: () => void }) {
  const technical = message.includes('desktop bridge') || message.includes('invoke')
  return <section className="connection-screen"><div className="connection-art">⌘</div><p className="eyebrow">Get started</p><h2>Connect your local workspace</h2><p>{technical ? 'Open the Academia OS desktop app to load your courses, tasks, readings, and review queue. Your academic files stay on this computer.' : message}</p><button className="primary-button" onClick={onRetry}>Retry connection</button>{technical ? <details className="connection-help"><summary>Advanced connection details</summary><code>academia status --json</code><span>Browser preview is intentionally data-free. The packaged desktop app connects to the local Academia OS interface.</span></details> : null}</section>
}

function Home({ status, tasks, reviews, activity, onNavigate }: { status: StatusPayload | null; tasks: Task[]; reviews: ReviewItem[]; activity: ActivityEvent[]; onNavigate: (view: View) => void }) {
  const openTasks = tasks.filter((task) => !task.completed)
  const student = status?.student.name || 'there'
  return <div className="page-stack"><section className="hero"><div><p className="eyebrow">{new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}</p><h2>Good morning, {student.split(' ')[0]}</h2><p className="hero-subtitle">A calm view of what matters for school today.</p></div><div className="hero-orbit"><span className="orbit-small" /><span className="orbit-large" /><span className="orbit-core">✦</span></div></section><section className="section-heading"><div><p className="eyebrow">Today</p><h3>Your academic focus</h3></div><button className="text-button" onClick={() => onNavigate('tasks')}>See all tasks <span>→</span></button></section><div className="card-grid two-col">{openTasks.slice(0, 2).map((task) => <article className="focus-card" key={task.id}><div className="card-topline"><span className="course-tag">{task.course || 'Academia'}</span><span className="soft-badge">{task.confidence}</span></div><h4>{task.title}</h4><p className="card-meta">From your local academic files</p><button className="secondary-button" onClick={() => onNavigate('tasks')}>Open task <span>→</span></button></article>)}{!openTasks.length && <EmptyCard title="No confirmed tasks yet" body="Add a syllabus or import course material to start building your academic picture." action="Open Library" onClick={() => onNavigate('library')} />}</div><section className="attention-card"><div className="attention-icon">!</div><div className="attention-copy"><p className="eyebrow">Needs your attention</p><h3>{reviews.length ? `${reviews.length} item${reviews.length === 1 ? '' : 's'} to review` : 'Nothing waiting for review'}</h3><p>{reviews.length ? 'Academia OS keeps uncertain or approval-required changes here.' : 'When a deadline conflict, source question, or proposed action appears, it will show up here.'}</p></div><button className="secondary-button" onClick={() => onNavigate('review')}>{reviews.length ? 'Review now' : 'View review queue'} <span>→</span></button></section><section className="section-heading"><div><p className="eyebrow">Courses</p><h3>Your semester at a glance</h3></div><button className="text-button" onClick={() => onNavigate('courses')}>View courses <span>→</span></button></section><div className="course-list">{status?.workspace.courses.slice(0, 4).map((course) => <CourseRow key={course.id} course={course} />)}{!status?.workspace.courses.length && <EmptyCard title="Your courses will appear here" body="Academia OS does not invent courses. Add confirmed course material when you are ready." action="Learn about import" onClick={() => onNavigate('library')} />}</div>{activity.length ? <section className="activity-preview"><div className="section-heading"><div><p className="eyebrow">Recent activity</p><h3>What changed</h3></div><button className="text-button" onClick={() => onNavigate('review')}>Open activity <span>→</span></button></div>{activity.slice(0, 3).map((event) => <ActivityRow event={event} key={event.id} />)}</section> : null}</div>
}

function Courses({ courses }: { courses: Course[] }) {
  const [selected, setSelected] = useState<Course | null>(null)
  return <div className="page-stack"><PageIntro eyebrow="Semester" title="Courses" subtitle="Useful academic context, with original files always underneath."/><div className="course-grid">{courses.map((course) => <article className="course-card" key={course.id}><div className="course-card-header"><span className="course-code">{course.code}</span><span className={course.review_required ? 'review-dot' : 'complete-dot'}>{course.review_required ? 'Review' : 'Clear'}</span></div><h3>{course.name.split(' - ').slice(1).join(' - ') || course.name}</h3><p>{course.inbox_count ? `${course.inbox_count} item${course.inbox_count === 1 ? '' : 's'} waiting in intake` : 'No new material waiting'}</p><button className="secondary-button" onClick={() => setSelected(course)}>{selected?.id === course.id ? 'Course selected' : 'Open course'} <span>→</span></button></article>)}{!courses.length && <EmptyCard title="No confirmed courses" body="Create a course from confirmed syllabus or course information. Academia OS will never infer one." action="Open settings" />}</div>{selected ? <section className="selected-course"><div><p className="eyebrow">Selected course</p><h3>{selected.name}</h3><p>{selected.path}</p></div><span>{selected.inbox_count} intake item{selected.inbox_count === 1 ? '' : 's'}</span></section> : null}</div>
}

function Tasks({ tasks }: { tasks: Task[] }) {
  const [filter, setFilter] = useState<'all' | 'open' | 'completed'>('all')
  const visible = tasks.filter((task) => filter === 'all' || (filter === 'completed' ? task.completed : !task.completed))
  return <div className="page-stack"><PageIntro eyebrow="Plan" title="Tasks" subtitle="Deadlines and study work derived from supported academic sources."/><div className="filter-row">{(['all', 'open', 'completed'] as const).map((value) => <button key={value} className={`filter-pill ${filter === value ? 'active' : ''}`} onClick={() => setFilter(value)}>{value === 'all' ? 'All tasks' : value === 'open' ? 'Open' : 'Completed'}</button>)}</div><div className="task-list">{visible.map((task) => <article className={`task-row ${task.completed ? 'done' : ''}`} key={task.id}><span className="task-check">{task.completed ? '✓' : ''}</span><div className="task-body"><h3>{task.title}</h3><p>{task.course || 'Semester'} · <span className="confidence">{task.confidence}</span></p></div><span className="task-source">{task.source.split('/').pop()}</span></article>)}{!visible.length && <EmptyCard title={filter === 'completed' ? 'No completed tasks' : 'No tasks yet'} body="Tasks will be derived from confirmed material. Unverified dates remain visibly unverified." action="Import material" />}</div></div>
}

function Library({ courses }: { courses: Course[] }) {
  const [query, setQuery] = useState('')
  const filteredCourses = courses.filter((course) => `${course.code} ${course.name}`.toLowerCase().includes(query.toLowerCase()))
  return <div className="page-stack"><PageIntro eyebrow="Sources" title="Library" subtitle="Readings, syllabi, notes, and source history in one human-friendly place."/><label className="library-search"><span aria-hidden="true">⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search your local academic index" aria-label="Search your local academic index"/><kbd>⌘ K</kbd></label><div className="library-grid"><LibraryTile icon="◈" title="Syllabi & course guides" body="Authoritative course context and assessment instructions."/><LibraryTile icon="▤" title="Readings & references" body="Sources with provenance and edition verification."/><LibraryTile icon="✎" title="Notes & study aids" body="User-created and AI-generated material kept distinct."/><LibraryTile icon="↓" title="Imported material" body="Manual imports and watched-folder intake awaiting review."/></div><section className="source-note"><span className="info-icon">i</span><p>Browser access is optional. You can build a complete academic system with manual imports and watched folders alone.</p></section><div className="course-list compact">{filteredCourses.map((course) => <CourseRow course={course} key={course.id} />)}{courses.length > 0 && !filteredCourses.length ? <p className="muted-copy">No indexed courses match “{query}”.</p> : null}</div></div>
}

function Review({ reviews, activity, actionBusy, onReviewAction }: { reviews: ReviewItem[]; activity: ActivityEvent[]; actionBusy: string | null; onReviewAction: (action: 'approve' | 'reject' | 'resolve', itemId: string) => Promise<void> }) {
  return <div className="page-stack"><PageIntro eyebrow="Human oversight" title="Review" subtitle="Uncertain information and approval-required changes stay here until you decide."/><div className="review-layout"><section><div className="section-heading"><div><p className="eyebrow">Queue</p><h3>{reviews.length} open item{reviews.length === 1 ? '' : 's'}</h3></div></div>{reviews.map((item) => <article className="review-row" key={item.id}><div className="review-type">{item.kind.replaceAll('_', ' ')}</div><div className="review-copy"><h3>{item.title}</h3><p>{item.course || 'Workspace'} · {item.priority} priority{item.action_proposal_id ? ' · approval required' : ''}</p><DetailList details={item.details} /></div><div className="review-actions">{item.action_proposal_id ? <><button className="secondary-button" disabled={actionBusy === item.id} onClick={() => void onReviewAction('approve', item.id)}>{actionBusy === item.id ? 'Saving…' : 'Approve'}</button><button className="quiet-button" disabled={actionBusy === item.id} onClick={() => void onReviewAction('reject', item.id)}>Reject</button></> : <button className="secondary-button" disabled={actionBusy === item.id} onClick={() => void onReviewAction('resolve', item.id)}>{actionBusy === item.id ? 'Saving…' : 'Mark resolved'}</button>}</div></article>)}{!reviews.length && <EmptyCard title="Your review queue is clear" body="Conflicts, uncertain source matches, and approval-required actions will appear here." action="Open activity" />}</section><section className="activity-panel"><p className="eyebrow">Activity</p><h3>What Academia OS changed</h3>{activity.slice(0, 8).map((event) => <ActivityRow event={event} key={event.id} />)}{!activity.length && <p className="muted-copy">No activity has been recorded yet.</p>}</section></div></div>
}

function Settings({ status }: { status: StatusPayload | null }) { return <div className="page-stack"><PageIntro eyebrow="Control" title="Settings" subtitle="Your choices stay local. Technical details and agent connections live below the everyday workflow."/><section className="settings-card"><SettingRow title="Workspace" value={status?.workspace.academic_root || 'Not connected'} detail="Local files remain readable without an agent."/><SettingRow title="Browser access" value={status?.acquisition.browser.enabled ? 'On' : 'Off'} detail="Manual import and watched folders remain available. Turn on advanced access only if you explicitly choose it."/><SettingRow title="Watched folders" value={status?.acquisition.watched_folders.length ? `${status.acquisition.watched_folders.length} configured` : 'None configured'} detail="A watched folder can send new local files into review without browser automation."/><SettingRow title="Agents & connections" value="Optional" detail="Hermes has an optional adapter; Codex, Claude, and ChatGPT/Work can use AGENTS.md plus the local CLI without a dedicated adapter."/></section><section className="advanced-card"><p className="eyebrow">Advanced</p><h3>Local interface</h3><p>Agents should use the documented Academia CLI rather than reverse-engineering Markdown files.</p><code>academia status --json</code><code>academia review --json</code></section></div> }

function PageIntro({ eyebrow, title, subtitle }: { eyebrow: string; title: string; subtitle: string }) { return <section className="page-intro"><p className="eyebrow">{eyebrow}</p><h2>{title}</h2><p>{subtitle}</p></section> }
function CourseRow({ course }: { course: Course }) { return <article className="course-row"><div className="course-symbol">{course.code.slice(0, 1)}</div><div><h3>{course.name}</h3><p>{course.inbox_count ? `${course.inbox_count} item${course.inbox_count === 1 ? '' : 's'} in intake` : 'Up to date'}</p></div><span className={course.review_required ? 'row-status warm' : 'row-status'}>{course.review_required ? 'Needs review' : 'Ready'}</span><span className="row-arrow">→</span></article> }
function DetailList({ details }: { details: Record<string, unknown> }) {
  const entries = Object.entries(details)
  if (!entries.length) return <p className="muted-copy">No additional details provided.</p>
  return <dl className="detail-list">{entries.map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value)}</dd></div>)}</dl>
}
function ActivityRow({ event }: { event: ActivityEvent }) { return <div className="activity-row"><span className="activity-dot" /><div><strong>{event.title}</strong><p>{event.course || 'Workspace'}{event.source ? ` · ${event.source}` : ''}</p></div><span className="activity-confidence">{event.confidence || event.event_type}</span></div> }
function EmptyCard({ title, body, action, onClick }: { title: string; body: string; action: string; onClick?: () => void }) { return <article className="empty-card"><div className="empty-mark">✦</div><h3>{title}</h3><p>{body}</p><button className="secondary-button" onClick={onClick}>{action} <span>→</span></button></article> }
function LibraryTile({ icon, title, body }: { icon: string; title: string; body: string }) { return <article className="library-tile"><span className="tile-icon">{icon}</span><h3>{title}</h3><p>{body}</p><span className="tile-arrow">→</span></article> }
function SettingRow({ title, value, detail }: { title: string; value: string; detail: string }) { return <div className="setting-row"><div><h3>{title}</h3><p>{detail}</p></div><span>{value}</span><button aria-label={`Edit ${title}`}>›</button></div> }

export default App
