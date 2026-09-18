import { useEffect, useMemo, useState } from 'react'
import { ImportView } from './ImportView'
import { MigrationView } from './MigrationView'
import { Onboarding } from './Onboarding'
import { ReviewCard } from './ReviewCard'
import { SettingsView } from './SettingsView'
import { api, BridgeUnavailableError, isTauriEnvironment } from './lib/api'
import type { ActivityEvent, Course, DomainEntity, LibraryItem, ProcessingRecord, ReviewItem, StatusPayload, Task } from './types'

const nav = [
  { id: 'home', label: 'Home', icon: '⌂' },
  { id: 'courses', label: 'Courses', icon: '◫' },
  { id: 'tasks', label: 'Tasks', icon: '✓' },
  { id: 'library', label: 'Library', icon: '▤' },
  { id: 'import', label: 'Import', icon: '↓' },
  { id: 'migration', label: 'Migrate older material', icon: '↗' },
  { id: 'review', label: 'Review', icon: '◌' },
  { id: 'settings', label: 'Settings', icon: '⚙' },
] as const

type View = typeof nav[number]['id']
type LibraryCategory = 'all' | LibraryItem['category']

const categoryLabels: Record<LibraryCategory, string> = {
  all: 'All material',
  syllabi: 'Syllabi & guides',
  readings: 'Readings & references',
  notes: 'Notes & study aids',
  imports: 'Imported material',
  other: 'Other material',
}

function App() {
  const [view, setView] = useState<View>('home')
  const [status, setStatus] = useState<StatusPayload | null>(null)
  const [courses, setCourses] = useState<Course[]>([])
  const [tasks, setTasks] = useState<Task[]>([])
  const [reviews, setReviews] = useState<ReviewItem[]>([])
  const [activity, setActivity] = useState<ActivityEvent[]>([])
  const [domain, setDomain] = useState<DomainEntity[]>([])
  const [libraryItems, setLibraryItems] = useState<LibraryItem[]>([])
  const [inbox, setInbox] = useState<ProcessingRecord[]>([])
  const [error, setError] = useState<string | null>(null)
  const [actionBusy, setActionBusy] = useState<string | null>(null)
  const [onboarding, setOnboarding] = useState(false)
  const [setupCandidates, setSetupCandidates] = useState<import('./types').WorkspaceCandidate[]>([])
  const [booting, setBooting] = useState(true)
  const [migrationBusy, setMigrationBusy] = useState(false)

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

  const refresh = async (allowDuringMigration = false) => {
    if (migrationBusy && !allowDuringMigration) return
    try {
      setError(null)
      const next = await api.status()
      if (!next.workspace.workspace_exists) {
        if (allowDuringMigration) throw new Error('The workspace disappeared while refreshing migration status.')
        await beginOnboarding()
        return
      }
      const inspected = await api.workspaceInspect(next.workspace.academic_root)
      if (!inspected.recognized) {
        if (allowDuringMigration) throw new Error('The workspace was not recognized while refreshing migration status.')
        await beginOnboarding()
        return
      }
      const [courseData, taskData, reviewData, activityData, domainData, libraryData, inboxData] = await Promise.all([
        api.courses(),
        api.tasks(),
        api.review(),
        api.activity(),
        api.domain(),
        api.library(),
        api.inbox(),
      ])
      setStatus(next)
      setCourses(courseData)
      setTasks(taskData)
      setReviews(reviewData)
      setActivity(activityData)
      setDomain(domainData)
      setLibraryItems(libraryData)
      setInbox(inboxData)
      setOnboarding(false)
    } catch (reason) {
      if (allowDuringMigration) throw reason
      if (reason instanceof BridgeUnavailableError) setError(reason.message)
      else await beginOnboarding()
    } finally {
      setBooting(false)
    }
  }

  // This effect starts the local CLI read; refresh owns loading, setup, and error state.
  // eslint-disable-next-line react-hooks/set-state-in-effect, react-hooks/exhaustive-deps
  useEffect(() => { void refresh() }, [])

  if (booting) return <main className="connection-screen"><div className="connection-art">✦</div><p className="eyebrow">Academia OS</p><h2>Checking your local workspace</h2><p>Your academic files stay on this computer while we check whether setup is already complete.</p></main>
  if (onboarding) return <Onboarding candidates={setupCandidates} onComplete={refresh} onMigration={async () => { await refresh(); setOnboarding(false); setView('migration') }} />

  const title = nav.find((item) => item.id === view)?.label ?? 'Home'
  const navigate = (next: View) => setView(next)

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><div className="brand-mark">A</div><div><strong>Academia</strong><span>OS</span></div></div>
        <div className="workspace-chip"><span className="status-dot" />Local workspace</div>
        <nav aria-label="Primary navigation">
          {nav.map((item) => <button key={item.id} className={`nav-item ${view === item.id ? 'active' : ''}`} onClick={() => navigate(item.id)} disabled={migrationBusy}><span className="nav-icon">{item.icon}</span>{item.label}{item.id === 'review' && status?.review_count ? <em>{status.review_count}</em> : null}</button>)}
        </nav>
        <div className="sidebar-bottom"><button className="agent-pill" onClick={() => navigate('settings')} disabled={migrationBusy}><span className="agent-avatar">✦</span><span><b>Local access</b><small>Optional connections</small></span><span className="chevron">›</span></button></div>
      </aside>
      <main className="main-content">
        <header className="topbar"><div><p className="eyebrow">{status?.workspace.semester ?? 'Local academic workspace'}</p><h1>{title}</h1></div><div className="top-actions"><button className="search-button" onClick={() => navigate('library')}><span>⌕</span> Search library <kbd>⌘ K</kbd></button><button className="icon-button" aria-label="Refresh" onClick={() => void refresh()} disabled={migrationBusy}>↻</button><div className="profile-badge">{status?.student.name?.slice(0, 1) ?? 'A'}</div></div></header>
        {error ? <ConnectionNotice message={error} onRetry={() => void refresh()} /> : <>{view === 'home' && <Home status={status} tasks={tasks} reviews={reviews} activity={activity} domain={domain} inbox={inbox} onNavigate={navigate} />}{view === 'courses' && <Courses courses={courses} domain={domain} libraryItems={libraryItems} onNavigate={navigate} />}{view === 'tasks' && <Tasks tasks={tasks} onNavigate={navigate} />}{view === 'library' && <Library courses={courses} items={libraryItems} inbox={inbox} onNavigate={navigate} />}{view === 'import' && status && <ImportView status={status} courses={courses} onImported={refresh} onReview={() => navigate('review')} />}{view === 'migration' && status && <MigrationView status={status} onApplied={() => refresh(true)} onReview={() => navigate('review')} onBusyChange={setMigrationBusy} />}{view === 'review' && <Review reviews={reviews} activity={activity} courses={courses} actionBusy={actionBusy} onNavigate={navigate} onReviewDecision={async (decision, itemId) => { try { setActionBusy(itemId); setError(null); await api.reviewDecision(itemId, decision); if (decision === 'use_new') await api.reviewExecute(itemId); await refresh() } catch (reason) { setError(String(reason)) } finally { setActionBusy(null) } }} />}{view === 'settings' && <SettingsView status={status} onSaved={refresh} />}</>}
      </main>
    </div>
  )
}

function ConnectionNotice({ message, onRetry }: { message: string; onRetry: () => void }) {
  const technical = message.includes('desktop bridge') || message.includes('invoke') || message.includes('local dashboard') || message.includes('academia dashboard')
  const localDashboard = !isTauriEnvironment() && technical
  return <section className="connection-screen"><div className="connection-art">⌘</div><p className="eyebrow">Get started</p><h2>Connect your local workspace</h2><p>{localDashboard ? <>Start <code>academia</code> in a terminal, then retry. Your academic files stay on this computer and the browser connects only to that local dashboard.</> : technical ? 'Open the Academia OS desktop app to load your courses, tasks, readings, and review queue. Your academic files stay on this computer.' : message}</p><button className="primary-button" onClick={onRetry}>Retry connection</button>{technical ? <details className="connection-help"><summary>Advanced connection details</summary><code>{localDashboard ? 'academia' : 'academia status --json'}</code><span>{localDashboard ? 'The browser dashboard is local-only. No academic files are sent to an external service.' : 'Browser preview is intentionally data-free. The packaged desktop app connects to the local Academia OS interface.'}</span></details> : null}</section>
}

function Home({ status, tasks, reviews, activity, domain, inbox, onNavigate }: { status: StatusPayload | null; tasks: Task[]; reviews: ReviewItem[]; activity: ActivityEvent[]; domain: DomainEntity[]; inbox: ProcessingRecord[]; onNavigate: (view: View) => void }) {
  const openTasks = tasks.filter((task) => !task.completed)
  const pendingInbox = inbox.filter((item) => item.status !== 'ACKNOWLEDGED')
  const student = status?.student.name || 'there'
  const nextDeadline = domain.filter((entity) => entity.entity_type === 'deadline' && entity.evidence?.confidence === 'current-confirmed' && typeof entity.date === 'string').sort((left, right) => String(left.date).localeCompare(String(right.date)))[0]
  const materialCount = status?.workspace.material_count ?? 0
  const activeSemester = status?.workspace.semester || 'the active semester'
  const availableSemesters = status?.workspace.available_semesters ?? []
  const activeSemesterMissing = Boolean(status && availableSemesters.length > 0 && !availableSemesters.includes(status.workspace.semester))
  const currentViewEmpty = Boolean(status && !status.workspace.courses.length && !materialCount)
  return <div className="page-stack">{(activeSemesterMissing || currentViewEmpty) && <section className={`data-note ${activeSemesterMissing ? 'warning' : ''}`}><div className="data-note-icon">i</div><div><p className="eyebrow">What this dashboard is reading</p><h3>{activeSemesterMissing ? `${activeSemester} is not present in this workspace` : `No indexed material for ${activeSemester}`}</h3><p>{activeSemesterMissing ? `Available semester folders: ${availableSemesters.join(', ')}. Change the active semester in Settings; Academia OS will not move files as part of that change.` : 'The connection is working, but tasks require a course checklist or evidence-backed syllabus projection, and Review requires an explicit uncertainty or approval item.'}</p></div><button className="secondary-button" onClick={() => onNavigate(activeSemesterMissing ? 'settings' : 'library')}>{activeSemesterMissing ? 'Open Settings' : 'Open Library'} <span>→</span></button></section>}<section className="hero"><div><p className="eyebrow">{new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}</p><h2>Good morning, {student.split(' ')[0]}</h2><p className="hero-subtitle">{nextDeadline ? `Next confirmed deadline: ${String(nextDeadline.title)} · ${String(nextDeadline.date)}` : 'A calm view of what matters for school today.'}</p></div><div className="hero-orbit"><span className="orbit-small" /><span className="orbit-large" /><span className="orbit-core">✦</span></div></section><div className="metric-strip"><Metric label="Courses" value={String(status?.workspace.courses.length ?? 0)} /><Metric label="Material" value={String(materialCount)} /><Metric label="Open tasks" value={String(openTasks.length)} /><Metric label="Needs review" value={String(reviews.length)} /></div><section className="section-heading"><div><p className="eyebrow">Today</p><h3>Your academic focus</h3></div><button className="text-button" onClick={() => onNavigate('tasks')}>See all tasks <span>→</span></button></section><div className="card-grid two-col">{openTasks.slice(0, 2).map((task) => <article className="focus-card" key={task.id}><div className="card-topline"><span className="course-tag">{task.course || 'Academia'}</span><span className="soft-badge">{task.confidence}</span></div><h4>{task.title}</h4><p className="card-meta">{task.due_date ? `Due ${task.due_date}` : 'From your local academic files'}</p><button className="secondary-button" onClick={() => onNavigate('tasks')}>Open task <span>→</span></button></article>)}{!openTasks.length && <EmptyCard title="No confirmed tasks yet" body="Add a syllabus or import course material to start building your academic picture." action="Open Library" onClick={() => onNavigate('library')} />}</div><section className="attention-card"><div className="attention-icon">!</div><div className="attention-copy"><p className="eyebrow">Needs your attention</p><h3>{reviews.length ? `${reviews.length} item${reviews.length === 1 ? '' : 's'} to review` : pendingInbox.length ? `${pendingInbox.length} file${pendingInbox.length === 1 ? '' : 's'} waiting for intake` : 'Nothing waiting for review'}</h3><p>{reviews.length ? 'Uncertain information and approval-required changes stay here until you decide.' : pendingInbox.length ? 'These files are present in an inbox but have not been classified or acknowledged yet.' : 'When a source conflict or proposed action appears, it will show up here.'}</p></div><button className="secondary-button" onClick={() => onNavigate(reviews.length ? 'review' : pendingInbox.length ? 'library' : 'review')}>{reviews.length ? 'Open Review' : pendingInbox.length ? 'Open Library' : 'Open Activity'} <span>→</span></button></section><section className="activity-panel home-activity"><div className="section-heading"><div><p className="eyebrow">Recent</p><h3>Activity</h3></div><button className="text-button" onClick={() => onNavigate('review')}>View review & activity <span>→</span></button></div>{activity.slice(0, 4).map((event) => <ActivityRow event={event} key={event.id} />)}{!activity.length && <p className="muted-copy">No activity has been recorded yet. Imports and approved changes will appear here.</p>}</section></div>
}

function Courses({ courses, domain, libraryItems, onNavigate }: { courses: Course[]; domain: DomainEntity[]; libraryItems: LibraryItem[]; onNavigate: (view: View) => void }) {
  const deadlines = new Map(domain.filter((entity) => entity.entity_type === 'deadline' && entity.evidence?.confidence === 'current-confirmed').map((entity) => [entity.course_id, entity]))
  const [selected, setSelected] = useState<Course | null>(null)
  const selectedItems = selected ? libraryItems.filter((item) => item.course_id === selected.id) : []
  return <div className="page-stack"><PageIntro eyebrow="Semester" title="Courses" subtitle="Useful academic context, with original files always underneath."/><div className="course-grid">{courses.map((course) => <article className="course-card" key={course.id}><div className="course-card-header"><span className="course-code">{course.code}</span><span className={course.review_required ? 'review-dot' : 'complete-dot'}>{course.review_required ? 'Intake' : 'Clear'}</span></div><h3>{course.name.split(' - ').slice(1).join(' - ') || course.name}</h3><p>{course.material_count ? `${course.material_count} material item${course.material_count === 1 ? '' : 's'} indexed` : deadlines.get(course.id) ? `Next confirmed deadline: ${String(deadlines.get(course.id)?.title)} · ${String(deadlines.get(course.id)?.date)}` : 'No material indexed yet'}</p><button className="secondary-button" onClick={() => setSelected(course)}>{selected?.id === course.id ? 'Course selected' : 'Open course'} <span>→</span></button></article>)}{!courses.length && <EmptyCard title="No confirmed courses" body="Create a course from confirmed syllabus or course information. Academia OS will never infer one." action="Open settings" onClick={() => onNavigate('settings')} />}</div>{selected ? <section className="selected-course"><div><p className="eyebrow">Selected course</p><h3>{selected.name}</h3><p>{selected.path}</p>{selectedItems.length ? <ul className="selected-material-list">{selectedItems.slice(0, 5).map((item) => <li key={item.id}><span>{categoryLabels[item.category]}</span><strong>{item.name}</strong></li>)}</ul> : <p className="muted-copy">No visible material is indexed for this course yet.</p>}</div><div className="selected-course-actions"><span>{selectedItems.length} material item{selectedItems.length === 1 ? '' : 's'}</span><button className="text-button" onClick={() => onNavigate('library')}>Open Library <span>→</span></button></div></section> : null}</div>
}

function Tasks({ tasks, onNavigate }: { tasks: Task[]; onNavigate: (view: View) => void }) {
  const [filter, setFilter] = useState<'all' | 'open' | 'completed'>('all')
  const visible = tasks.filter((task) => filter === 'all' || (filter === 'completed' ? task.completed : !task.completed))
  return <div className="page-stack"><PageIntro eyebrow="Plan" title="Tasks" subtitle="Tasks are read from course checklists and structured, evidence-backed deadlines or assignments. Nothing is invented from a filename."/><div className="filter-row">{(['all', 'open', 'completed'] as const).map((value) => <button key={value} className={`filter-pill ${filter === value ? 'active' : ''}`} onClick={() => setFilter(value)}>{value === 'all' ? 'All tasks' : value === 'open' ? 'Open' : 'Completed'}</button>)}</div><div className="task-list">{visible.map((task) => <article className={`task-row ${task.completed ? 'done' : ''}`} key={task.id}><span className="task-check">{task.completed ? '✓' : ''}</span><div className="task-body"><h3>{task.title}</h3><p>{task.course || 'Semester'} · <span className="confidence">{task.confidence}</span> · <span className="task-origin">{task.kind === 'deadline' || task.kind === 'assignment' ? 'Evidence-backed academic item' : 'Course checklist'}</span></p></div><span className="task-source">{task.due_date ? `Due ${task.due_date}` : task.source.split('/').pop()}</span></article>)}{!visible.length && <EmptyCard title={filter === 'completed' ? 'No completed tasks' : 'No tasks yet'} body="Tasks appear when a course status checklist or an evidence-backed syllabus projection contains one. Unverified dates remain visibly unverified." action="Open Library" onClick={() => onNavigate('library')} />}</div></div>
}

function Library({ courses, items, inbox, onNavigate }: { courses: Course[]; items: LibraryItem[]; inbox: ProcessingRecord[]; onNavigate: (view: View) => void }) {
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState<LibraryCategory>('all')
  const [courseId, setCourseId] = useState('')
  const pendingPaths = useMemo(() => new Set(inbox.filter((item) => item.status !== 'ACKNOWLEDGED').map((item) => item.source_path)), [inbox])
  const counts = useMemo(() => items.reduce<Record<string, number>>((result, item) => { result[item.category] = (result[item.category] || 0) + 1; return result }, {}), [items])
  const visible = items.filter((item) => (category === 'all' || item.category === category) && (!courseId || item.course_id === courseId) && (!query.trim() || `${item.name} ${item.relative_path}`.toLowerCase().includes(query.trim().toLowerCase())))
  return <div className="page-stack"><PageIntro eyebrow="Sources" title="Library" subtitle="Every visible file in the active semester is listed here without opening or rewriting it. Category labels are navigation hints, not claims about authority."/><div className="library-toolbar"><label className="library-search"><span aria-hidden="true">⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search your local academic index" aria-label="Search your local academic index"/><kbd>⌘ K</kbd></label><button className="primary-button" onClick={() => onNavigate('import')}>Import material <span>↓</span></button></div><div className="library-grid">{(['syllabi', 'readings', 'notes', 'imports'] as const).map((value) => <LibraryTile key={value} icon={value === 'syllabi' ? '◈' : value === 'readings' ? '▤' : value === 'notes' ? '✎' : '↓'} title={categoryLabels[value]} body={value === 'imports' ? 'Files in course or semester intake awaiting classification.' : value === 'syllabi' ? 'Course context and assessment instructions.' : value === 'readings' ? 'Sources with provenance and edition verification.' : 'User-created and generated study material kept distinct.'} count={counts[value] || 0} selected={category === value} onClick={() => setCategory(category === value ? 'all' : value)} />)}</div><section className="source-note"><span className="info-icon">i</span><p>Imported material is shown even when it was already in the workspace before connection. Files awaiting processing are labeled as intake; only explicit uncertain/conflict decisions appear in Review.</p></section><section className="library-list-panel"><div className="library-list-heading"><div><p className="eyebrow">Indexed files</p><h3>{visible.length} visible item{visible.length === 1 ? '' : 's'}</h3></div><div className="library-filters"><button className={`filter-pill ${category === 'all' ? 'active' : ''}`} onClick={() => setCategory('all')}>All</button><select aria-label="Filter by course" value={courseId} onChange={(event) => setCourseId(event.target.value)}><option value="">All courses</option>{courses.map((course) => <option value={course.id} key={course.id}>{course.code} · {course.name.split(' - ').slice(1).join(' - ') || course.name}</option>)}</select></div></div><div className="library-file-list">{visible.map((item) => <LibraryFileRow item={item} pending={pendingPaths.has(item.path)} key={item.id} />)}{!visible.length && <EmptyCard title="No material matches this view" body={items.length ? 'Try another category, course, or search phrase.' : 'Import material or connect a workspace containing course files to populate the Library.'} action="Import material" onClick={() => onNavigate('import')} />}</div></section><div className="course-list compact">{courses.map((course) => <CourseRow course={course} key={course.id} onClick={() => setCourseId(course.id)} selected={courseId === course.id} />)}</div></div>
}

function Review({ reviews, activity, courses, actionBusy, onNavigate, onReviewDecision }: { reviews: ReviewItem[]; activity: ActivityEvent[]; courses: Course[]; actionBusy: string | null; onNavigate: (view: View) => void; onReviewDecision: (decision: string, itemId: string) => Promise<void> }) {
  return <div className="page-stack"><PageIntro eyebrow="Human oversight" title="Review" subtitle="Uncertain information and approval-required changes stay here until you decide. Unprocessed inbox files are shown separately in Library."/><div className="review-layout"><section><div className="section-heading"><div><p className="eyebrow">Queue</p><h3>{reviews.length} open item{reviews.length === 1 ? '' : 's'}</h3></div></div>{reviews.map((item) => <ReviewCard item={item} courses={courses} busy={actionBusy === item.id} onDecision={(decision) => onReviewDecision(decision, item.id)} key={item.id} />)}{!reviews.length && <EmptyCard title="Your review queue is clear" body="Conflicts, uncertain source matches, and approval-required actions will appear here." action="Open Library" onClick={() => onNavigate('library')} />}</section><section className="activity-panel"><p className="eyebrow">Activity</p><h3>What Academia OS changed</h3>{activity.slice(0, 8).map((event) => <ActivityRow event={event} key={event.id} />)}{!activity.length && <p className="muted-copy">No activity has been recorded yet.</p>}</section></div></div>
}

function PageIntro({ eyebrow, title, subtitle }: { eyebrow: string; title: string; subtitle: string }) { return <section className="page-intro"><p className="eyebrow">{eyebrow}</p><h2>{title}</h2><p>{subtitle}</p></section> }
function Metric({ label, value }: { label: string; value: string }) { return <div className="metric-cell"><strong>{value}</strong><span>{label}</span></div> }
function CourseRow({ course, onClick, selected }: { course: Course; onClick?: () => void; selected?: boolean }) { return <button className={`course-row ${selected ? 'selected' : ''}`} onClick={onClick} disabled={!onClick}><span className="course-symbol">{course.code.slice(0, 1)}</span><span><strong>{course.name}</strong><small>{course.material_count ? `${course.material_count} material item${course.material_count === 1 ? '' : 's'}` : 'No material indexed'}</small></span><span className={course.review_required ? 'row-status warm' : 'row-status'}>{course.review_required ? 'Intake' : 'Ready'}</span><span className="row-arrow">→</span></button> }
function LibraryTile({ icon, title, body, count, selected, onClick }: { icon: string; title: string; body: string; count: number; selected: boolean; onClick: () => void }) { return <button className={`library-tile ${selected ? 'selected' : ''}`} aria-pressed={selected} onClick={onClick}><span className="tile-icon">{icon}</span><span className="tile-count">{count}</span><strong>{title}</strong><span>{body}</span><span className="tile-arrow">→</span></button> }
function LibraryFileRow({ item, pending }: { item: LibraryItem; pending: boolean }) { return <article className="library-file-row"><div className="library-file-icon">{item.extension.replace('.', '').slice(0, 4).toUpperCase() || 'FILE'}</div><div className="library-file-main"><strong>{item.name}</strong><span>{item.relative_path}</span><small>{item.course_id || 'Semester intake'} · {categoryLabels[item.category]}</small></div><div className="library-file-meta"><span>{formatBytes(item.size)}</span>{pending && <em>Awaiting intake</em>}</div></article> }
function ActivityRow({ event }: { event: ActivityEvent }) { return <div className="activity-row"><span className="activity-dot" /><div><strong>{event.title}</strong><p>{event.course || 'Workspace'}{event.source ? ` · ${event.source}` : ''}</p></div><span className="activity-confidence">{event.confidence || event.event_type}</span></div> }
function EmptyCard({ title, body, action, onClick }: { title: string; body: string; action: string; onClick?: () => void }) { return <article className="empty-card"><div className="empty-mark">✦</div><h3>{title}</h3><p>{body}</p>{onClick ? <button className="secondary-button" onClick={onClick}>{action} <span>→</span></button> : <span className="muted-copy">{action}</span>}</article> }
function formatBytes(value: number): string { if (value < 1024) return `${value} B`; if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`; return `${(value / (1024 * 1024)).toFixed(1)} MB` }

export default App
