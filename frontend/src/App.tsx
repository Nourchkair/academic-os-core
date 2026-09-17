import { useEffect, useState } from 'react'
import { ImportView } from './ImportView'
import { Onboarding } from './Onboarding'
import { ReviewCard } from './ReviewCard'
import { SettingsView } from './SettingsView'
import { api, BridgeUnavailableError } from './lib/api'
import type { ActivityEvent, Course, DomainEntity, ReviewItem, StatusPayload, Task } from './types'

const nav = [
  { id: 'home', label: 'Home', icon: '⌂' },
  { id: 'courses', label: 'Courses', icon: '◫' },
  { id: 'tasks', label: 'Tasks', icon: '✓' },
  { id: 'library', label: 'Library', icon: '▤' },
  { id: 'import', label: 'Import', icon: '↓' },
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
  const [domain, setDomain] = useState<DomainEntity[]>([])
  const [error, setError] = useState<string | null>(null)
  const [actionBusy, setActionBusy] = useState<string | null>(null)
  const [onboarding, setOnboarding] = useState(false)
  const [setupCandidates, setSetupCandidates] = useState<import('./types').WorkspaceCandidate[]>([])
  const [booting, setBooting] = useState(true)

  const beginOnboarding = async () => {
    try {
      const candidates = await api.workspaceDiscover()
      setSetupCandidates(candidates)
      setOnboarding(true)
      setError(null)
    } catch (reason) {
      setError(reason instanceof BridgeUnavailableError ? reason.message : 'Open the Academia OS desktop app to begin setup.')
    }
  }

  const refresh = async () => {
    try {
      setError(null)
      const next = await api.status()
      if (!next.workspace.workspace_exists) {
        await beginOnboarding()
        return
      }
      const inspected = await api.workspaceInspect(next.workspace.academic_root)
      if (!inspected.recognized) {
        await beginOnboarding()
        return
      }
      setStatus(next)
      const [courseData, taskData, reviewData, activityData, domainData] = await Promise.all([api.courses(), api.tasks(), api.review(), api.activity(), api.domain()])
      setCourses(courseData)
      setTasks(taskData)
      setReviews(reviewData)
      setActivity(activityData)
      setDomain(domainData)
      setOnboarding(false)
    } catch (reason) {
      if (reason instanceof BridgeUnavailableError) setError(reason.message)
      else await beginOnboarding()
    } finally {
      setBooting(false)
    }
  }

  // This effect starts the external CLI read; refresh owns loading, setup, and error state.
  // eslint-disable-next-line react-hooks/set-state-in-effect, react-hooks/exhaustive-deps
  useEffect(() => { void refresh() }, [])

  if (booting) return <main className="connection-screen"><div className="connection-art">✦</div><p className="eyebrow">Academia OS</p><h2>Checking your local workspace</h2><p>Your academic files stay on this computer while we check whether setup is already complete.</p></main>
  if (onboarding) return <Onboarding candidates={setupCandidates} onComplete={refresh} />

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
        {error ? <ConnectionNotice message={error} onRetry={() => void refresh()} /> : <>{view === 'home' && <Home status={status} tasks={tasks} reviews={reviews} activity={activity} domain={domain} onNavigate={setView} />}{view === 'courses' && <Courses courses={courses} domain={domain} />}{view === 'tasks' && <Tasks tasks={tasks} />}{view === 'library' && <Library courses={courses} onNavigate={setView} />}{view === 'import' && status && <ImportView status={status} courses={courses} onImported={refresh} onReview={() => setView('review')} />}{view === 'review' && <Review reviews={reviews} activity={activity} courses={courses} actionBusy={actionBusy} onReviewDecision={async (decision, itemId) => { try { setActionBusy(itemId); setError(null); await api.reviewDecision(itemId, decision); if (decision === 'use_new') await api.reviewExecute(itemId); await refresh() } catch (reason) { setError(String(reason)) } finally { setActionBusy(null) } }} />}{view === 'settings' && <Settings status={status} onSaved={refresh} />}</>}
      </main>
    </div>
  )
}

function ConnectionNotice({ message, onRetry }: { message: string; onRetry: () => void }) {
  const technical = message.includes('desktop bridge') || message.includes('invoke')
  return <section className="connection-screen"><div className="connection-art">⌘</div><p className="eyebrow">Get started</p><h2>Connect your local workspace</h2><p>{technical ? 'Open the Academia OS desktop app to load your courses, tasks, readings, and review queue. Your academic files stay on this computer.' : message}</p><button className="primary-button" onClick={onRetry}>Retry connection</button>{technical ? <details className="connection-help"><summary>Advanced connection details</summary><code>academia status --json</code><span>Browser preview is intentionally data-free. The packaged desktop app connects to the local Academia OS interface.</span></details> : null}</section>
}

function Home({ status, tasks, reviews, activity, domain, onNavigate }: { status: StatusPayload | null; tasks: Task[]; reviews: ReviewItem[]; activity: ActivityEvent[]; domain: DomainEntity[]; onNavigate: (view: View) => void }) {
  const openTasks = tasks.filter((task) => !task.completed)
  const student = status?.student.name || 'there'
  const nextDeadline = domain.filter((entity) => entity.entity_type === 'deadline' && entity.evidence?.confidence === 'current-confirmed' && typeof entity.date === 'string').sort((left, right) => String(left.date).localeCompare(String(right.date)))[0]
  return <div className="page-stack"><section className="hero"><div><p className="eyebrow">{new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}</p><h2>Good morning, {student.split(' ')[0]}</h2><p className="hero-subtitle">{nextDeadline ? `Next confirmed deadline: ${String(nextDeadline.title)} · ${String(nextDeadline.date)}` : 'A calm view of what matters for school today.'}</p></div><div className="hero-orbit"><span className="orbit-small" /><span className="orbit-large" /><span className="orbit-core">✦</span></div></section><section className="section-heading"><div><p className="eyebrow">Today</p><h3>Your academic focus</h3></div><button className="text-button" onClick={() => onNavigate('tasks')}>See all tasks <span>→</span></button></section><div className="card-grid two-col">{openTasks.slice(0, 2).map((task) => <article className="focus-card" key={task.id}><div className="card-topline"><span className="course-tag">{task.course || 'Academia'}</span><span className="soft-badge">{task.confidence}</span></div><h4>{task.title}</h4><p className="card-meta">From your local academic files</p><button className="secondary-button" onClick={() => onNavigate('tasks')}>Open task <span>→</span></button></article>)}{!openTasks.length && <EmptyCard title="No confirmed tasks yet" body="Add a syllabus or import course material to start building your academic picture." action="Open Library" onClick={() => onNavigate('library')} />}</div><section className="attention-card"><div className="attention-icon">!</div><div className="attention-copy"><p className="eyebrow">Needs your attention</p><h3>{reviews.length ? `${reviews.length} item${reviews.length === 1 ? '' : 's'} to review` : 'Nothing waiting for review'}</h3><p>{reviews.length ? 'Academia OS keeps uncertain or approval-required changes here.' : 'When a deadline conflict, source question, or proposed action appears, it will show up here.'}</p></div><button className="secondary-button" onClick={() => onNavigate('review')}>{reviews.length ? 'Review now' : 'View review queue'} <span>→</span></button></section><section className="section-heading"><div><p className="eyebrow">Courses</p><h3>Your semester at a glance</h3></div><button className="text-button" onClick={() => onNavigate('courses')}>View courses <span>→</span></button></section><div className="course-list">{status?.workspace.courses.slice(0, 4).map((course) => <CourseRow key={course.id} course={course} />)}{!status?.workspace.courses.length && <EmptyCard title="Your courses will appear here" body="Academia OS does not invent courses. Add confirmed course material when you are ready." action="Learn about import" onClick={() => onNavigate('library')} />}</div>{activity.length ? <section className="activity-preview"><div className="section-heading"><div><p className="eyebrow">Recent activity</p><h3>What changed</h3></div><button className="text-button" onClick={() => onNavigate('review')}>Open activity <span>→</span></button></div>{activity.slice(0, 3).map((event) => <ActivityRow event={event} key={event.id} />)}</section> : null}</div>
}

function Courses({ courses, domain }: { courses: Course[]; domain: DomainEntity[] }) {
  const deadlines = new Map(domain.filter((entity) => entity.entity_type === 'deadline' && entity.evidence?.confidence === 'current-confirmed').map((entity) => [entity.course_id, entity]))
  const [selected, setSelected] = useState<Course | null>(null)
  return <div className="page-stack"><PageIntro eyebrow="Semester" title="Courses" subtitle="Useful academic context, with original files always underneath."/><div className="course-grid">{courses.map((course) => <article className="course-card" key={course.id}><div className="course-card-header"><span className="course-code">{course.code}</span><span className={course.review_required ? 'review-dot' : 'complete-dot'}>{course.review_required ? 'Review' : 'Clear'}</span></div><h3>{course.name.split(' - ').slice(1).join(' - ') || course.name}</h3><p>{course.inbox_count ? `${course.inbox_count} item${course.inbox_count === 1 ? '' : 's'} waiting in intake` : deadlines.get(course.id) ? `Next confirmed deadline: ${String(deadlines.get(course.id)?.title)} · ${String(deadlines.get(course.id)?.date)}` : 'No new material waiting'}</p><button className="secondary-button" onClick={() => setSelected(course)}>{selected?.id === course.id ? 'Course selected' : 'Open course'} <span>→</span></button></article>)}{!courses.length && <EmptyCard title="No confirmed courses" body="Create a course from confirmed syllabus or course information. Academia OS will never infer one." action="Open settings" />}</div>{selected ? <section className="selected-course"><div><p className="eyebrow">Selected course</p><h3>{selected.name}</h3><p>{selected.path}</p></div><span>{selected.inbox_count} intake item{selected.inbox_count === 1 ? '' : 's'}</span></section> : null}</div>
}

function Tasks({ tasks }: { tasks: Task[] }) {
  const [filter, setFilter] = useState<'all' | 'open' | 'completed'>('all')
  const visible = tasks.filter((task) => filter === 'all' || (filter === 'completed' ? task.completed : !task.completed))
  return <div className="page-stack"><PageIntro eyebrow="Plan" title="Tasks" subtitle="Deadlines and study work derived from supported academic sources."/><div className="filter-row">{(['all', 'open', 'completed'] as const).map((value) => <button key={value} className={`filter-pill ${filter === value ? 'active' : ''}`} onClick={() => setFilter(value)}>{value === 'all' ? 'All tasks' : value === 'open' ? 'Open' : 'Completed'}</button>)}</div><div className="task-list">{visible.map((task) => <article className={`task-row ${task.completed ? 'done' : ''}`} key={task.id}><span className="task-check">{task.completed ? '✓' : ''}</span><div className="task-body"><h3>{task.title}</h3><p>{task.course || 'Semester'} · <span className="confidence">{task.confidence}</span> · <span className="task-origin">Source-backed academic work</span></p></div><span className="task-source">{task.source.split('/').pop()}</span></article>)}{!visible.length && <EmptyCard title={filter === 'completed' ? 'No completed tasks' : 'No tasks yet'} body="Tasks will be derived from confirmed material. Unverified dates remain visibly unverified." action="Import material" />}</div></div>
}

function Library({ courses, onNavigate }: { courses: Course[]; onNavigate: (view: View) => void }) {
  const [query, setQuery] = useState('')
  const filteredCourses = courses.filter((course) => `${course.code} ${course.name}`.toLowerCase().includes(query.toLowerCase()))
  return <div className="page-stack"><PageIntro eyebrow="Sources" title="Library" subtitle="Readings, syllabi, notes, and source history in one human-friendly place."/><div className="library-toolbar"><label className="library-search"><span aria-hidden="true">⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search your local academic index" aria-label="Search your local academic index"/><kbd>⌘ K</kbd></label><button className="primary-button" onClick={() => onNavigate('import')}>Import material <span>↓</span></button></div><div className="library-grid"><LibraryTile icon="◈" title="Syllabi & course guides" body="Authoritative course context and assessment instructions."/><LibraryTile icon="▤" title="Readings & references" body="Sources with provenance and edition verification."/><LibraryTile icon="✎" title="Notes & study aids" body="User-created and AI-generated material kept distinct."/><LibraryTile icon="↓" title="Imported material" body="Manual imports and watched-folder intake awaiting review."/></div><section className="source-note"><span className="info-icon">i</span><p>Browser access is optional. You can build a complete academic system with manual imports and watched folders alone.</p></section><div className="course-list compact">{filteredCourses.map((course) => <CourseRow course={course} key={course.id} />)}{courses.length > 0 && !filteredCourses.length ? <p className="muted-copy">No indexed courses match “{query}”.</p> : null}</div></div>
}

function Review({ reviews, activity, courses, actionBusy, onReviewDecision }: { reviews: ReviewItem[]; activity: ActivityEvent[]; courses: Course[]; actionBusy: string | null; onReviewDecision: (decision: string, itemId: string) => Promise<void> }) {
  return <div className="page-stack"><PageIntro eyebrow="Human oversight" title="Review" subtitle="Uncertain information and approval-required changes stay here until you decide."/><div className="review-layout"><section><div className="section-heading"><div><p className="eyebrow">Queue</p><h3>{reviews.length} open item{reviews.length === 1 ? '' : 's'}</h3></div></div>{reviews.map((item) => <ReviewCard item={item} courses={courses} busy={actionBusy === item.id} onDecision={(decision) => onReviewDecision(decision, item.id)} key={item.id} />)}{!reviews.length && <EmptyCard title="Your review queue is clear" body="Conflicts, uncertain source matches, and approval-required actions will appear here." action="Open activity" />}</section><section className="activity-panel"><p className="eyebrow">Activity</p><h3>What Academia OS changed</h3>{activity.slice(0, 8).map((event) => <ActivityRow event={event} key={event.id} />)}{!activity.length && <p className="muted-copy">No activity has been recorded yet.</p>}</section></div></div>
}

function Settings({ status, onSaved }: { status: StatusPayload | null; onSaved: () => Promise<void> }) { return <SettingsView status={status} onSaved={onSaved} /> }

function PageIntro({ eyebrow, title, subtitle }: { eyebrow: string; title: string; subtitle: string }) { return <section className="page-intro"><p className="eyebrow">{eyebrow}</p><h2>{title}</h2><p>{subtitle}</p></section> }
function CourseRow({ course }: { course: Course }) { return <article className="course-row"><div className="course-symbol">{course.code.slice(0, 1)}</div><div><h3>{course.name}</h3><p>{course.inbox_count ? `${course.inbox_count} item${course.inbox_count === 1 ? '' : 's'} in intake` : 'Up to date'}</p></div><span className={course.review_required ? 'row-status warm' : 'row-status'}>{course.review_required ? 'Needs review' : 'Ready'}</span><span className="row-arrow">→</span></article> }
function ActivityRow({ event }: { event: ActivityEvent }) { return <div className="activity-row"><span className="activity-dot" /><div><strong>{event.title}</strong><p>{event.course || 'Workspace'}{event.source ? ` · ${event.source}` : ''}</p></div><span className="activity-confidence">{event.confidence || event.event_type}</span></div> }
function EmptyCard({ title, body, action, onClick }: { title: string; body: string; action: string; onClick?: () => void }) { return <article className="empty-card"><div className="empty-mark">✦</div><h3>{title}</h3><p>{body}</p><button className="secondary-button" onClick={onClick}>{action} <span>→</span></button></article> }
function LibraryTile({ icon, title, body }: { icon: string; title: string; body: string }) { return <article className="library-tile"><span className="tile-icon">{icon}</span><h3>{title}</h3><p>{body}</p><span className="tile-arrow">→</span></article> }

export default App
