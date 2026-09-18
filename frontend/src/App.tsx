import { useEffect, useState } from 'react'
import { ActionPanel } from './ActionPanel'
import { CoursesView } from './CoursesView'
import { Onboarding } from './Onboarding'
import { SettingsView } from './SettingsView'
import { api, BridgeUnavailableError, isTauriEnvironment } from './lib/api'
import type { ActivityEvent, Course, DomainEntity, LibraryItem, ProcessingRecord, StatusPayload, Task } from './types'

const nav = [
  { id: 'home', label: 'Home', icon: '⌂' },
  { id: 'courses', label: 'Courses', icon: '◫' },
  { id: 'tasks', label: 'Tasks', icon: '✓' },
  { id: 'activity', label: 'Activity', icon: '◷' },
  { id: 'settings', label: 'Settings', icon: '⚙' },
] as const

type View = typeof nav[number]['id']

type ActionMode = 'import' | 'migration'

function App() {
  const [view, setView] = useState<View>('home')
  const [status, setStatus] = useState<StatusPayload | null>(null)
  const [courses, setCourses] = useState<Course[]>([])
  const [tasks, setTasks] = useState<Task[]>([])
  const [activity, setActivity] = useState<ActivityEvent[]>([])
  const [domain, setDomain] = useState<DomainEntity[]>([])
  const [libraryItems, setLibraryItems] = useState<LibraryItem[]>([])
  const [inbox, setInbox] = useState<ProcessingRecord[]>([])
  const [selectedSemester, setSelectedSemester] = useState('')
  const [semesterLoading, setSemesterLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [onboarding, setOnboarding] = useState(false)
  const [setupCandidates, setSetupCandidates] = useState<import('./types').WorkspaceCandidate[]>([])
  const [booting, setBooting] = useState(true)
  const [migrationBusy, setMigrationBusy] = useState(false)
  const [actionMode, setActionMode] = useState<ActionMode | null>(null)

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
        if (allowDuringMigration) throw new Error('The workspace disappeared while refreshing.')
        await beginOnboarding()
        return
      }
      const inspected = await api.workspaceInspect(next.workspace.academic_root)
      if (!inspected.recognized) {
        if (allowDuringMigration) throw new Error('The workspace was not recognized while refreshing.')
        await beginOnboarding()
        return
      }
      const available = new Set([next.workspace.semester, ...next.workspace.available_semesters])
      const targetSemester = selectedSemester && available.has(selectedSemester) ? selectedSemester : next.workspace.semester
      const [courseData, taskData, activityData, domainData, libraryData, inboxData] = await Promise.all([
        api.courses(targetSemester),
        api.tasks(),
        api.activity(),
        api.domain(),
        api.library({ semester: targetSemester }),
        api.inbox(),
      ])
      setStatus(next)
      setSelectedSemester(targetSemester)
      setCourses(courseData)
      setTasks(taskData)
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

  const changeSemester = async (semester: string) => {
    try {
      setSemesterLoading(true)
      setError(null)
      const [courseData, libraryData] = await Promise.all([api.courses(semester), api.library({ semester })])
      setSelectedSemester(semester)
      setCourses(courseData)
      setLibraryItems(libraryData)
    } catch (reason) {
      setError(`The ${semester} workspace could not be loaded: ${String(reason)}`)
    } finally {
      setSemesterLoading(false)
    }
  }

  // eslint-disable-next-line react-hooks/set-state-in-effect, react-hooks/exhaustive-deps
  useEffect(() => { void refresh() }, [])

  if (booting) return <main className="connection-screen"><div className="connection-art">✦</div><p className="eyebrow">Academia OS</p><h2>Checking your local workspace</h2><p>Your academic files stay on this computer while we check whether setup is already complete.</p></main>
  if (onboarding) return <Onboarding candidates={setupCandidates} onComplete={refresh} onMigration={async () => { await refresh(); setOnboarding(false); setView('courses'); setActionMode('migration') }} />
  if (error && !status) return <ConnectionNotice message={error} onRetry={() => void refresh()} />

  const navigate = (next: View) => setView(next)
  const semesters = status ? Array.from(new Set([status.workspace.semester, ...status.workspace.available_semesters])) : []
  const openActionPanel = (mode: ActionMode) => { setActionMode(mode); setError(null) }
  const closeActionPanel = () => { if (!migrationBusy) setActionMode(null) }

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">A</div><div><strong>Academia</strong><span>OS</span></div></div>
      <div className="workspace-chip"><span className="status-dot" />Local workspace</div>
      <nav aria-label="Primary navigation">{nav.map((item) => <button key={item.id} className={`nav-item ${view === item.id ? 'active' : ''}`} onClick={() => navigate(item.id)} disabled={migrationBusy}><span className="nav-icon">{item.icon}</span>{item.label}</button>)}</nav>
      <div className="sidebar-bottom"><button className="agent-pill" onClick={() => navigate('settings')} disabled={migrationBusy}><span className="agent-avatar">✦</span><span><b>Local workspace</b><small>Profile & workspace</small></span><span className="chevron">›</span></button></div>
    </aside>
    <main className="main-content">
      <header className="topbar"><div className="top-actions"><button className="icon-button" aria-label="Refresh" onClick={() => void refresh()} disabled={migrationBusy}>↻</button><button className="workspace-action-button" aria-label="Open import and migration actions" title="Import or migrate material" onClick={() => openActionPanel('import')} disabled={migrationBusy}>+</button></div></header>
      {error && <p className="dashboard-inline-error" role="alert">{error}</p>}
      {view === 'home' && <Home status={status} tasks={tasks} activity={activity} domain={domain} inbox={inbox} onNavigate={navigate} />}
      {view === 'courses' && <CoursesView semesters={semesters} semester={selectedSemester || status?.workspace.semester || ''} courses={courses} items={libraryItems} inbox={inbox} loading={semesterLoading} onSemesterChange={changeSemester} onOpenActions={openActionPanel} />}
      {view === 'tasks' && <Tasks tasks={tasks} onNavigate={navigate} />}
      {view === 'activity' && <ActivityView activity={activity} onNavigate={navigate} />}
      {view === 'settings' && status && <SettingsView status={status} onSaved={() => refresh()} />}
    </main>
    {actionMode && status && <ActionPanel mode={actionMode} status={status} courses={courses} semester={selectedSemester || status.workspace.semester} onModeChange={setActionMode} onClose={closeActionPanel} onImported={async () => { await refresh(true) }} onMigrated={async () => { await refresh(true) }} onBusyChange={setMigrationBusy} />}
  </div>
}

function ConnectionNotice({ message, onRetry }: { message: string; onRetry: () => void }) {
  const technical = message.includes('desktop bridge') || message.includes('invoke') || message.includes('local dashboard') || message.includes('academia dashboard')
  const localDashboard = !isTauriEnvironment() && technical
  return <section className="connection-screen"><div className="connection-art">⌘</div><p className="eyebrow">Get started</p><h2>Connect your local workspace</h2><p>{localDashboard ? <>Start <code>academia</code> in a terminal, then retry. Your academic files stay on this computer and the browser connects only to that local dashboard.</> : technical ? 'Open the Academia OS desktop app to load your courses, tasks, academic library, and activity.' : message}</p><button className="primary-button" onClick={onRetry}>Retry connection</button>{technical ? <details className="connection-help"><summary>Advanced connection details</summary><code>{localDashboard ? 'academia' : 'academia status --json'}</code><span>{localDashboard ? 'The browser dashboard is local-only. No academic files are sent to an external service.' : 'The packaged desktop app connects to the local Academia OS interface.'}</span></details> : null}</section>
}

function Home({ status, tasks, activity, domain, inbox, onNavigate }: { status: StatusPayload | null; tasks: Task[]; activity: ActivityEvent[]; domain: DomainEntity[]; inbox: ProcessingRecord[]; onNavigate: (view: View) => void }) {
  const openTasks = tasks.filter((task) => !task.completed)
  const pendingInbox = inbox.filter((item) => item.status !== 'ACKNOWLEDGED')
  const student = status?.student.name || 'there'
  const nextDeadline = domain.filter((entity) => entity.entity_type === 'deadline' && entity.evidence?.confidence === 'current-confirmed' && typeof entity.date === 'string').sort((left, right) => String(left.date).localeCompare(String(right.date)))[0]
  const materialCount = status?.workspace.material_count ?? 0
  const activeSemester = status?.workspace.semester || 'the active semester'
  const availableSemesters = status?.workspace.available_semesters ?? []
  const activeSemesterMissing = Boolean(status && availableSemesters.length > 0 && !availableSemesters.includes(status.workspace.semester))
  const currentViewEmpty = Boolean(status && !status.workspace.courses.length && !materialCount)
  return <div className="page-stack">
    {(activeSemesterMissing || currentViewEmpty) && <section className={`data-note ${activeSemesterMissing ? 'warning' : ''}`}><div className="data-note-icon">i</div><div><p className="eyebrow">What this dashboard is reading</p><h3>{activeSemesterMissing ? `${activeSemester} is not present in this workspace` : `No indexed material for ${activeSemester}`}</h3><p>{activeSemesterMissing ? `Available semester folders: ${availableSemesters.join(', ')}. Choose another semester from Courses; Academia OS will not move files as part of that change.` : 'The connection is working, but this workspace has no recognized courses or visible material for the active semester yet.'}</p></div><button className="secondary-button" onClick={() => onNavigate(activeSemesterMissing ? 'settings' : 'courses')}>{activeSemesterMissing ? 'Open Settings' : 'Open Courses'} <span>→</span></button></section>}
    <section className="hero"><div><p className="eyebrow">{new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}</p><h2>Good morning, {student.split(' ')[0]}</h2><p className="hero-subtitle">{nextDeadline ? `Next confirmed deadline: ${String(nextDeadline.title)} · ${String(nextDeadline.date)}` : 'A calm view of what matters for school today.'}</p></div><div className="hero-orbit"><span className="orbit-small" /><span className="orbit-large" /><span className="orbit-core">✦</span></div></section>
    <div className="metric-strip"><Metric label="Courses" value={String(status?.workspace.courses.length ?? 0)} /><Metric label="Material" value={String(materialCount)} /><Metric label="Open tasks" value={String(openTasks.length)} /><Metric label="Needs input" value={String(status?.review_count ?? 0)} /><Metric label="Intake" value={String(pendingInbox.length)} /></div>
    <section className="section-heading"><div><p className="eyebrow">Today</p><h3>Your academic focus</h3></div><button className="text-button" onClick={() => onNavigate('tasks')}>See all tasks <span>→</span></button></section>
    <div className="card-grid two-col"><section className="focus-card"><div className="card-topline"><span className="course-tag">Open tasks</span><span className="soft-badge">{openTasks.length ? `${openTasks.length} to do` : 'Clear'}</span></div>{openTasks.slice(0, 3).map((task) => <div className="focus-task" key={task.id}><strong>{task.title}</strong><span>{task.course || 'Semester'}{task.due_date ? ` · Due ${task.due_date}` : ''}</span></div>)}{!openTasks.length && <p className="muted-copy">No open tasks are currently recorded from structured course evidence.</p>}</section><section className="activity-panel"><div className="card-topline"><div><p className="eyebrow">Activity</p><h3>Recent local changes</h3></div><button className="text-button" onClick={() => onNavigate('activity')}>View all <span>→</span></button></div><div className="activity-preview">{activity.slice(0, 4).map((event) => <ActivityRow event={event} key={event.id} />)}{!activity.length && <p className="muted-copy">No changes have been recorded yet.</p>}</div></section></div>
  </div>
}

function Tasks({ tasks, onNavigate }: { tasks: Task[]; onNavigate: (view: View) => void }) {
  const [filter, setFilter] = useState<'all' | 'open' | 'completed'>('all')
  const visible = tasks.filter((task) => filter === 'all' || (filter === 'completed' ? task.completed : !task.completed))
  return <div className="page-stack"><PageIntro eyebrow="Plan" title="Tasks" subtitle="Tasks are read from course checklists and structured, evidence-backed deadlines or assignments. Nothing is invented from a filename."/><section className="task-definition-card"><div className="task-definition-icon">✓</div><div><p className="eyebrow">What becomes a task</p><h3>Only two sources create tasks here</h3><ul><li><strong>Course checklist:</strong> a checkbox such as <code>- [ ] Read the syllabus</code> in a course’s <code>01_COURSE/Course_Status.md</code>.</li><li><strong>Structured academic evidence:</strong> an <code>assignment</code> or <code>deadline</code> with a title, recognized course, and source evidence in the local domain projection.</li></ul><p>Files in <code>00_INBOX</code>, filenames, arbitrary notes, and template checklists do not become tasks automatically.</p></div></section><div className="filter-row">{(['all', 'open', 'completed'] as const).map((value) => <button key={value} className={`filter-pill ${filter === value ? 'active' : ''}`} onClick={() => setFilter(value)}>{value === 'all' ? 'All tasks' : value === 'open' ? 'Open' : 'Completed'}</button>)}</div><div className="task-list">{visible.map((task) => <article className={`task-row ${task.completed ? 'done' : ''}`} key={task.id}><span className="task-check">{task.completed ? '✓' : ''}</span><div className="task-body"><h3>{task.title}</h3><p>{task.course || 'Semester'} · <span className="confidence">{task.confidence}</span> · <span className="task-origin">{task.kind === 'deadline' || task.kind === 'assignment' ? 'Evidence-backed academic item' : 'Course checklist'}</span></p></div><span className="task-source">{task.due_date ? `Due ${task.due_date}` : task.source.split('/').pop()}</span></article>)}{!visible.length && <EmptyCard title={filter === 'completed' ? 'No completed tasks' : 'No tasks yet'} body="Tasks appear when a course status checklist or an evidence-backed syllabus projection contains one. Unverified dates remain visibly unverified." action="Open Courses" onClick={() => onNavigate('courses')} />}</div></div>
}

function ActivityView({ activity, onNavigate }: { activity: ActivityEvent[]; onNavigate: (view: View) => void }) {
  return <div className="page-stack"><PageIntro eyebrow="Audit trail" title="Activity" subtitle="A chronological record of changes Academia OS actually completed in this local workspace. Reads, scans, and external agent conversations are not recorded as changes unless the core performed an action."/><section className="activity-page-panel"><div className="section-heading"><div><p className="eyebrow">What Academia OS changed</p><h3>{activity.length ? `${activity.length} recorded event${activity.length === 1 ? '' : 's'}` : 'No changes recorded yet'}</h3></div><button className="text-button" onClick={() => onNavigate('courses')}>Open Courses <span>→</span></button></div>{activity.length ? <div className="activity-timeline">{activity.map((event) => <ActivityDetailRow event={event} key={event.id} />)}</div> : <EmptyCard title="Nothing has changed yet" body="Imports, verified processing, migrations, and other core actions will appear here with their source, actor, and timestamp." action="Open Courses" onClick={() => onNavigate('courses')} />}</section></div>
}

function PageIntro({ eyebrow, title, subtitle }: { eyebrow: string; title: string; subtitle: string }) { return <section className="page-intro"><p className="eyebrow">{eyebrow}</p><h2>{title}</h2><p>{subtitle}</p></section> }
function Metric({ label, value }: { label: string; value: string }) { return <div className="metric-cell"><strong>{value}</strong><span>{label}</span></div> }
function ActivityDetailRow({ event }: { event: ActivityEvent }) { const detail = Object.entries(event.details).filter(([key]) => !['content', 'body'].includes(key)).slice(0, 3); return <article className="activity-detail-row"><div className="activity-detail-marker"><span className="activity-dot" /></div><div className="activity-detail-body"><div className="activity-detail-heading"><div><strong>{event.title}</strong><p>{event.course || 'Workspace'} · {event.actor}</p></div><time dateTime={event.created_at}>{formatActivityDate(event.created_at)}</time></div>{event.source && <p className="activity-source">Source · {event.source}</p>}{detail.length > 0 && <dl>{detail.map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd></div>)}</dl>}<span className="activity-confidence">{event.confidence || event.event_type}</span></div></article> }
function ActivityRow({ event }: { event: ActivityEvent }) { return <div className="activity-row"><span className="activity-dot" /><div><strong>{event.title}</strong><p>{event.course || 'Workspace'}{event.source ? ` · ${event.source}` : ''}</p></div><span className="activity-confidence">{event.confidence || event.event_type}</span></div> }
function EmptyCard({ title, body, action, onClick }: { title: string; body: string; action: string; onClick?: () => void }) { return <article className="empty-card"><div className="empty-mark">✦</div><h3>{title}</h3><p>{body}</p>{onClick ? <button className="secondary-button" onClick={onClick}>{action} <span>→</span></button> : <span className="muted-copy">{action}</span>}</article> }
function formatActivityDate(value: string): string { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) }

export default App
