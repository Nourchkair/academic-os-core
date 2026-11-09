import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { ActionPanel } from './ActionPanel'
import { CoursesView } from './CoursesView'
import { DashboardChat } from './DashboardChat'
import { HomeView } from './HomeView'
import { getTaskUrgency, urgencyLabel } from './lib/task-urgency'
import { Onboarding } from './Onboarding'
import { SettingsView } from './SettingsView'
import { api, BridgeUnavailableError, isTauriEnvironment } from './lib/api'
import type { StudyChatRequest } from './lib/chat-history'
import type { ActivityEvent, Course, CourseworkHistoryRecord, CourseworkKind, LibraryItem, ProcessingRecord, StatusPayload, Task } from './types'

const nav = [
  { id: 'home', label: 'Home', icon: '⌂' },
  { id: 'chat', label: 'Study chat', icon: '◉' },
  { id: 'tasks', label: 'Tasks', icon: '✓' },
  { id: 'activity', label: 'Activity', icon: '◷' },
] as const

type View = 'home' | 'courses' | 'chat' | 'tasks' | 'activity' | 'settings'
type StudyResumeRequest = { courseId: string; sessionId: string }

type ActionMode = 'import' | 'migration'

type TooltipSide = 'top' | 'right' | 'bottom' | 'left'
type TooltipState = { text: string; side: TooltipSide; left: number; top: number; arrow: number; ready: boolean }

function AppTooltipLayer() {
  const [tooltip, setTooltip] = useState<TooltipState | null>(null)
  const tooltipRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let hovered: HTMLElement | null = null
    let focused: HTMLElement | null = null
    let frame = 0
    const activeTarget = () => focused || hovered
    const hide = () => { window.cancelAnimationFrame(frame); setTooltip(null) }
    const show = () => {
      const target = activeTarget()
      const text = target?.dataset.tooltip?.trim()
      if (!target?.isConnected || !text) { hide(); return }
      const sideAttr = target.dataset.tooltipSide
      let side: TooltipSide = sideAttr === 'left' || sideAttr === 'right' || sideAttr === 'top' || sideAttr === 'bottom' ? sideAttr : 'bottom'
      const rect = target.getBoundingClientRect()
      setTooltip({ text, side, left: 0, top: 0, arrow: 0, ready: false })
      window.cancelAnimationFrame(frame)
      frame = window.requestAnimationFrame(() => {
        if (activeTarget() !== target || !tooltipRef.current) return
        const bounds = target.getBoundingClientRect()
        const bubble = tooltipRef.current
        const width = bubble.offsetWidth
        const height = bubble.offsetHeight
        const gap = 9
        const edge = 8
        if (side === 'right' && bounds.right + gap + width > window.innerWidth - edge && bounds.left > width + gap + edge) side = 'left'
        else if (side === 'left' && bounds.left - gap - width < edge && bounds.right + width + gap < window.innerWidth - edge) side = 'right'
        if (side === 'top' && bounds.top - height - gap < edge) side = 'bottom'
        else if (side === 'bottom' && bounds.bottom + height + gap > window.innerHeight - edge) side = 'top'

        let left = bounds.left + bounds.width / 2 - width / 2
        let top = bounds.bottom + gap
        if (side === 'top') top = bounds.top - height - gap
        if (side === 'left') { left = bounds.left - width - gap; top = bounds.top + bounds.height / 2 - height / 2 }
        if (side === 'right') { left = bounds.right + gap; top = bounds.top + bounds.height / 2 - height / 2 }
        left = Math.max(edge, Math.min(left, window.innerWidth - width - edge))
        top = Math.max(edge, Math.min(top, window.innerHeight - height - edge))
        const arrow = side === 'left' || side === 'right'
          ? Math.max(9, Math.min(bounds.top + bounds.height / 2 - top, height - 9))
          : Math.max(9, Math.min(bounds.left + bounds.width / 2 - left, width - 9))
        setTooltip({ text, side, left, top, arrow, ready: true })
      })
    }
    const nearestTooltip = (target: EventTarget | null) => target instanceof Element ? target.closest<HTMLElement>('[data-tooltip]') : null
    const onPointerOver = (event: PointerEvent) => { hovered = nearestTooltip(event.target); show() }
    const onPointerOut = (event: PointerEvent) => {
      const from = nearestTooltip(event.target)
      const to = nearestTooltip(event.relatedTarget)
      if (from && from !== to && hovered === from) { hovered = null; show() }
    }
    const onFocusIn = (event: FocusEvent) => { focused = nearestTooltip(event.target); show() }
    const onFocusOut = (event: FocusEvent) => {
      const from = nearestTooltip(event.target)
      const to = nearestTooltip(event.relatedTarget)
      if (from && from !== to && focused === from) { focused = null; show() }
    }
    const onViewportChange = () => { if (activeTarget()) show() }
    const observer = new MutationObserver(() => { if (activeTarget()) show() })
    observer.observe(document.body, { attributes: true, attributeFilter: ['data-tooltip', 'data-tooltip-side'], subtree: true })
    document.addEventListener('pointerover', onPointerOver, true)
    document.addEventListener('pointerout', onPointerOut, true)
    document.addEventListener('focusin', onFocusIn, true)
    document.addEventListener('focusout', onFocusOut, true)
    document.addEventListener('scroll', onViewportChange, true)
    window.addEventListener('resize', onViewportChange)
    return () => {
      observer.disconnect()
      document.removeEventListener('pointerover', onPointerOver, true)
      document.removeEventListener('pointerout', onPointerOut, true)
      document.removeEventListener('focusin', onFocusIn, true)
      document.removeEventListener('focusout', onFocusOut, true)
      document.removeEventListener('scroll', onViewportChange, true)
      window.removeEventListener('resize', onViewportChange)
      window.cancelAnimationFrame(frame)
    }
  }, [])

  if (!tooltip) return null
  return createPortal(
    <div className="app-tooltip-layer" aria-hidden="true">
      <div ref={tooltipRef} className="app-tooltip" data-side={tooltip.side} style={{ left: tooltip.left, top: tooltip.top, '--tooltip-arrow': `${tooltip.arrow}px`, visibility: tooltip.ready ? 'visible' : 'hidden' } as CSSProperties} role="tooltip">{tooltip.text}</div>
    </div>,
    document.body,
  )
}

function App() {
  const [view, setView] = useState<View>('home')
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => window.localStorage.getItem('academia.sidebar.collapsed') === 'true')
  const [status, setStatus] = useState<StatusPayload | null>(null)
  const [courses, setCourses] = useState<Course[]>([])
  const [tasks, setTasks] = useState<Task[]>([])
  const [activity, setActivity] = useState<ActivityEvent[]>([])
  const [libraryItems, setLibraryItems] = useState<LibraryItem[]>([])
  const [inbox, setInbox] = useState<ProcessingRecord[]>([])
  const [selectedSemester, setSelectedSemester] = useState('')
  const [studyResumeRequest, setStudyResumeRequest] = useState<StudyResumeRequest | null>(null)
  const [studyChatRequest, setStudyChatRequest] = useState<StudyChatRequest | null>(null)
  const [semesterLoading, setSemesterLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [onboarding, setOnboarding] = useState(false)
  const [setupCandidates, setSetupCandidates] = useState<import('./types').WorkspaceCandidate[]>([])
  const [booting, setBooting] = useState(true)
  const [migrationBusy, setMigrationBusy] = useState(false)
  const [actionMode, setActionMode] = useState<ActionMode | null>(null)
  const [actionCourseId, setActionCourseId] = useState<string | undefined>()
  const [courseOpenRequest, setCourseOpenRequest] = useState<{ id: string; courseId: string } | null>(null)
  const chatNavRef = useRef<HTMLDetailsElement>(null)
  const chatMenuItems: { view: View; label: string; icon: string }[] = [
    { view: 'home', label: 'Home', icon: '⌂' },
    { view: 'courses', label: 'Courses', icon: '◫' },
    { view: 'tasks', label: 'Tasks', icon: '✓' },
    { view: 'settings', label: 'Settings', icon: '⚙' },
  ]

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
      const [courseData, taskData, activityData, libraryData, inboxData] = await Promise.all([
        api.courses(targetSemester),
        api.tasks(targetSemester),
        api.activity(),
        api.library({ semester: targetSemester }),
        api.inbox(),
      ])
      setStatus(next)
      setSelectedSemester(targetSemester)
      setCourses(courseData)
      setTasks(taskData)
      setActivity(activityData)
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
      const [courseData, taskData, libraryData] = await Promise.all([api.courses(semester), api.tasks(semester), api.library({ semester })])
      setSelectedSemester(semester)
      setCourses(courseData)
      setTasks(taskData)
      setLibraryItems(libraryData)
    } catch (reason) {
      setError(`The ${semester} workspace could not be loaded: ${String(reason)}`)
    } finally {
      setSemesterLoading(false)
    }
  }

  // eslint-disable-next-line react-hooks/set-state-in-effect, react-hooks/exhaustive-deps
  useEffect(() => { void refresh() }, [])

  useEffect(() => {
    let mounted = true
    const updateProcessing = () => {
      if (document.visibilityState !== 'visible') return
      void api.processingStatus().then((records) => {
        if (mounted) setInbox(records)
      }).catch(() => {})
    }
    updateProcessing()
    const timer = window.setInterval(updateProcessing, 10_000)
    window.addEventListener('focus', updateProcessing)
    document.addEventListener('visibilitychange', updateProcessing)
    return () => {
      mounted = false
      window.clearInterval(timer)
      window.removeEventListener('focus', updateProcessing)
      document.removeEventListener('visibilitychange', updateProcessing)
    }
  }, [])

  useEffect(() => {
    const closeChatNavigation = (event: PointerEvent) => {
      const dropdown = chatNavRef.current
      if (dropdown?.open && event.target instanceof Node && !dropdown.contains(event.target)) dropdown.open = false
    }
    const closeChatNavigationOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && chatNavRef.current) chatNavRef.current.open = false
    }
    document.addEventListener('pointerdown', closeChatNavigation)
    document.addEventListener('keydown', closeChatNavigationOnEscape)
    return () => {
      document.removeEventListener('pointerdown', closeChatNavigation)
      document.removeEventListener('keydown', closeChatNavigationOnEscape)
    }
  }, [])

  const resumeStudySession = useCallback((courseId: string, sessionId: string) => {
    setStudyResumeRequest({ courseId, sessionId })
    setView('courses')
  }, [])
  const clearStudyResumeRequest = useCallback(() => setStudyResumeRequest(null), [])
  const openStudyConversation = useCallback((conversationId: string) => {
    setStudyChatRequest({ id: crypto.randomUUID(), action: 'open', conversationId })
    setView('chat')
  }, [])
  const startStudyChat = useCallback((courseId: string, prompt?: string) => {
    setStudyChatRequest({ id: crypto.randomUUID(), action: 'new', courseId, prompt })
    setView('chat')
  }, [])
  const clearStudyChatRequest = useCallback(() => setStudyChatRequest(null), [])
  const openCourse = useCallback((courseId: string) => {
    setCourseOpenRequest({ id: crypto.randomUUID(), courseId })
    setView('courses')
  }, [])
  const clearCourseOpenRequest = useCallback(() => setCourseOpenRequest(null), [])

  if (booting) return <main className="connection-screen"><div className="connection-art">✦</div><p className="eyebrow">Academia OS</p><h2>Checking your local workspace</h2><p>Your academic files stay on this computer while we check whether setup is already complete.</p></main>
  if (onboarding) return <Onboarding candidates={setupCandidates} onComplete={refresh} onMigration={async () => { await refresh(); setOnboarding(false); setView('home'); setActionMode('migration') }} />
  if (error && !status) return <ConnectionNotice message={error} onRetry={() => void refresh()} />

  const navigate = (next: View) => setView(next)
  const semesters = status ? Array.from(new Set([status.workspace.semester, ...status.workspace.available_semesters])) : []
  const openActionPanel = (mode: ActionMode, courseId?: string) => { setActionMode(mode); setActionCourseId(courseId); setError(null) }
  const closeActionPanel = () => { if (!migrationBusy) setActionMode(null) }

  return <div className={`app-shell ${sidebarCollapsed ? 'sidebar-collapsed' : ''} ${view === 'chat' ? 'chat-mode' : ''}`}>
    {view !== 'chat' && <aside className="sidebar" aria-label="Application sidebar">
      <div className="sidebar-heading">
        <button className="brand" onClick={() => navigate('home')} aria-label="Academia OS home" data-tooltip={sidebarCollapsed ? 'Academia OS home' : undefined} data-tooltip-side={sidebarCollapsed ? 'right' : undefined}>
          <span className="brand-mark">A</span><span className="brand-wordmark"><strong>Academia</strong><span>OS</span></span>
        </button>
        <button className="sidebar-collapse" onClick={() => setSidebarCollapsed((collapsed) => {
          const next = !collapsed
          window.localStorage.setItem('academia.sidebar.collapsed', String(next))
          return next
        })} aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'} data-tooltip={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'} data-tooltip-side="right">
          <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="4.5" width="17" height="15" rx="2.5" /><path d={sidebarCollapsed ? 'M9 4.5v15M14 9l3 3-3 3' : 'M9 4.5v15M15 9l-3 3 3 3'} /></svg>
        </button>
      </div>
      <nav aria-label="Primary navigation">{nav.map((item) => <button key={item.id} className={`nav-item ${view === item.id || (item.id === 'home' && view === 'courses') ? 'active' : ''}`} onClick={() => navigate(item.id)} disabled={migrationBusy} data-tooltip={sidebarCollapsed ? item.label : undefined} data-tooltip-side={sidebarCollapsed ? 'right' : undefined}><span className="nav-icon">{item.icon}</span><span className="nav-label">{item.label}</span></button>)}</nav>
      <div className="sidebar-bottom">
        <button className={`profile-button ${view === 'settings' ? 'active' : ''}`} onClick={() => navigate('settings')} disabled={migrationBusy} aria-label="Open profile and settings" data-tooltip="Settings" data-tooltip-side="right">
          <span className="profile-avatar" aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="3.2" /><path d="M5.5 19c.6-3.1 2.9-4.8 6.5-4.8s5.9 1.7 6.5 4.8" /></svg></span>
          <span className="profile-copy"><b>{status?.student.name.split(' ')[0] || 'Profile'}</b><small>Profile & settings</small></span>
          <svg className="profile-chevron" viewBox="0 0 20 20" aria-hidden="true"><path d="m8 5 5 5-5 5" /></svg>
        </button>
      </div>
    </aside>}
    <main className="main-content">
      {view === 'chat' && <header className="topbar topbar-study-chat"><details className="chat-nav-dropdown" ref={chatNavRef}><summary aria-label="Open navigation menu"><span aria-hidden="true">☰</span><strong>Menu</strong><span className="chat-menu-caret" aria-hidden="true">⌄</span></summary><div className="chat-nav-menu" role="menu" aria-label="Main navigation">{chatMenuItems.map((item) => <button key={item.view} role="menuitem" data-tooltip={item.label} data-tooltip-side="right" onClick={() => setView(item.view)}><span aria-hidden="true">{item.icon}</span>{item.label}</button>)}</div></details></header>}
      {error && <p className="dashboard-inline-error" role="alert">{error}</p>}
      {view === 'home' && <HomeView status={status} courses={courses} tasks={tasks} activity={activity} inbox={inbox} semester={selectedSemester || status?.workspace.semester || ''} semesters={semesters} loading={semesterLoading} onSemesterChange={changeSemester} onOpenCourse={openCourse} onOpenIntake={() => openActionPanel('import')} onNavigate={navigate} />}
      {view === 'courses' && <CoursesView semesters={semesters} semester={selectedSemester || status?.workspace.semester || ''} courses={courses} items={libraryItems} inbox={inbox} loading={semesterLoading} onSemesterChange={changeSemester} onOpenActions={openActionPanel} onHistoryChanged={() => refresh()} studyResumeRequest={studyResumeRequest} onStudyResumeConsumed={clearStudyResumeRequest} onOpenStudyConversation={openStudyConversation} onStartStudyChat={startStudyChat} courseOpenRequest={courseOpenRequest} onCourseOpenConsumed={clearCourseOpenRequest} onBackHome={() => setView('home')} />}
      <div className={`chat-route-shell ${view === 'chat' ? 'active' : ''}`} aria-hidden={view !== 'chat'}><DashboardChat courses={courses} items={libraryItems} semester={selectedSemester || status?.workspace.semester || ''} onResumeStudySession={resumeStudySession} studyChatRequest={studyChatRequest} onStudyChatRequestConsumed={clearStudyChatRequest} /></div>
      {view === 'tasks' && <Tasks tasks={tasks} courses={courses} semester={selectedSemester || status?.workspace.semester || ''} timezone={status?.workspace.timezone} onNavigate={navigate} onChanged={() => refresh()} />}
      {view === 'activity' && <ActivityView activity={activity} processing={inbox} onNavigate={navigate} />}
      {view === 'settings' && status && <SettingsView status={status} onSaved={() => refresh()} />}
    </main>
    {actionMode && status && <ActionPanel key={`${actionMode}:${actionCourseId || 'general'}`} mode={actionMode} status={status} courses={courses} semester={selectedSemester || status.workspace.semester} initialCourseId={actionCourseId} onModeChange={setActionMode} onClose={closeActionPanel} onImported={async () => { await refresh(true) }} onMigrated={async () => { await refresh(true) }} onBusyChange={setMigrationBusy} />}
    <AppTooltipLayer />
  </div>
}

function ConnectionNotice({ message, onRetry }: { message: string; onRetry: () => void }) {
  const technical = message.includes('desktop bridge') || message.includes('invoke') || message.includes('local dashboard') || message.includes('academia dashboard')
  const localDashboard = !isTauriEnvironment() && technical
  return <section className="connection-screen"><div className="connection-art">⌘</div><p className="eyebrow">Get started</p><h2>Connect your local workspace</h2><p>{localDashboard ? <>Start <code>academia</code> in a terminal, then retry. Your academic files stay on this computer and the browser connects only to that local dashboard.</> : technical ? 'Open the Academia OS desktop app to load your courses, tasks, academic library, and activity.' : message}</p><button className="primary-button" onClick={onRetry}>Retry connection</button>{technical ? <details className="connection-help"><summary>Advanced connection details</summary><code>{localDashboard ? 'academia' : 'academia status --json'}</code><span>{localDashboard ? 'The browser dashboard is local-only. No academic files are sent to an external service.' : 'The packaged desktop app connects to the local Academia OS interface.'}</span></details> : null}</section>
}

function localDate(timezone: string) {
  return new Intl.DateTimeFormat('en-CA', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())
}

function sortTasks(tasks: Task[]) {
  return [...tasks].sort((a, b) => Number(a.completed) - Number(b.completed) || (a.due_date || '9999').localeCompare(b.due_date || '9999') || (a.due_time || '').localeCompare(b.due_time || '') || a.title.localeCompare(b.title))
}

function formatDue(task: Task) {
  if (!task.due_date) return 'Date to confirm'
  // A syllabus date is a local calendar date, never midnight UTC.
  const date = new Date(`${task.due_date.slice(0, 10)}T12:00:00Z`)
  const label = new Intl.DateTimeFormat(undefined, { timeZone: 'UTC', weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' }).format(date)
  const time = task.due_time?.match(/^(\d{2}):(\d{2})$/)
  const hour = time ? Number(time[1]) : 0
  return `Due ${label}${time ? ` at ${hour % 12 || 12}:${time[2]} ${hour >= 12 ? 'p.m.' : 'a.m.'}` : ''}`
}

function Tasks({ tasks, courses, semester, timezone = 'America/Toronto', onNavigate, onChanged }: { tasks: Task[]; courses: Course[]; semester: string; timezone?: string; onNavigate: (view: View) => void; onChanged: () => Promise<void> }) {
  const [filter, setFilter] = useState<'all' | 'week' | 'open' | 'completed'>('all')
  const today = localDate(timezone)
  const end = new Date(`${today}T12:00:00Z`)
  end.setUTCDate(end.getUTCDate() + 7)
  const weekEnd = end.toISOString().slice(0, 10)
  const visible = sortTasks(tasks.filter((task) => filter === 'all' || (filter === 'week' ? !task.completed && Boolean(task.due_date && task.due_date >= today && task.due_date <= weekEnd) : filter === 'completed' ? task.completed : !task.completed)))
  return <div className="page-stack">
    <PageIntro eyebrow="Plan" title="Tasks & deadlines" subtitle={`Your course assessments and deadlines. Times use ${timezone}. Mark a task done here and add or update its grade whenever you have it.`} />
    <div className="filter-row">{(['all', 'week', 'open', 'completed'] as const).map((value) => <button key={value} className={`filter-pill ${filter === value ? 'active' : ''}`} onClick={() => setFilter(value)}>{value === 'all' ? 'All tasks' : value === 'week' ? 'Next 7 days' : value === 'open' ? 'Open' : 'Completed'}</button>)}</div>
    <div className="task-list">{visible.map((task) => { const urgency = getTaskUrgency(task, timezone); return <article className={`task-row ${task.completed ? 'done' : ''}`} data-tone={urgency} key={task.id}>
      <span className="task-check">{task.completed ? '✓' : ''}</span>
      <div className="task-body"><h3>{task.title}{task.weight ? ` · ${task.weight} of grade` : ''}</h3><p>{task.course || 'Semester'} · {task.completed ? 'Completed' : task.due_date && task.due_date < today ? 'Past due date · completion unrecorded' : task.due_date === today ? 'Due today' : task.status || 'Completion unrecorded'}</p><details><summary>Source · {task.source.split('/').pop()}{task.source_location ? ` · ${task.source_location}` : ''}</summary><p>{task.confidence === 'likely' ? 'From local syllabus; later course updates have not been checked.' : task.confidence} · {task.source}</p></details></div>
      <span className="task-source"><span className={`status-pill tone-${urgency}`}>{urgencyLabel(urgency)}</span>{formatDue(task)}</span>
      <TaskCompletionControl task={task} courses={courses} semester={semester} onChanged={onChanged} />
    </article> })}{!visible.length && <EmptyCard title={filter === 'completed' ? 'No completed tasks recorded' : filter === 'week' ? 'No recorded deadlines in the next 7 days' : 'No tasks recorded'} body="Course deadlines appear after the syllabus has been indexed. An empty list does not confirm that no work is due." action="Go to Home" onClick={() => onNavigate('home')} />}</div>
  </div>
}

function TaskCompletionControl({ task, courses, semester, onChanged }: { task: Task; courses: Course[]; semester: string; onChanged: () => Promise<void> }) {
  const [open, setOpen] = useState(false)
  const [grade, setGrade] = useState('')
  const [savedGrade, setSavedGrade] = useState<string | null>(task.grade || null)
  const [existing, setExisting] = useState<CourseworkHistoryRecord | null>(null)
  const [busy, setBusy] = useState(false)
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [historyLoadFailed, setHistoryLoadFailed] = useState(false)
  const [error, setError] = useState('')
  const normalized = (value: string) => value.toLocaleLowerCase().replace(/[^a-z0-9]/g, '')
  const taskCourse = courses.find((course) => [course.id, course.code, course.name, `${course.code} - ${course.name}`].some((value) => normalized(value) === normalized(task.course || '')))
  const supportedKinds: CourseworkKind[] = ['assignment', 'essay', 'project', 'exam', 'presentation', 'quiz', 'other']
  const kind: CourseworkKind = supportedKinds.includes(task.kind as CourseworkKind) ? task.kind as CourseworkKind : 'assignment'

  const openEditor = async () => {
    setOpen(true)
    setError('')
    setGrade('')
    setExisting(null)
    setSavedGrade(null)
    setHistoryLoadFailed(false)
    if (!taskCourse) return
    setLoadingHistory(true)
    try {
      const records = await api.courseworkHistory(taskCourse.id, semester)
      const match = records.find((record) => normalized(record.task_title || record.title) === normalized(task.title)) || null
      setExisting(match)
      setGrade(match?.grade || '')
      setSavedGrade(match?.grade || null)
    } catch (reason) {
      setHistoryLoadFailed(true)
      setError(`Could not load this course's grade record. ${String(reason)}`)
    } finally {
      setLoadingHistory(false)
    }
  }

  const save = async (includeGrade: boolean) => {
    if (!taskCourse || busy) return
    setBusy(true)
    setError('')
    const enteredGrade = includeGrade ? grade.trim() : ''
    try {
      const status = enteredGrade ? 'graded' : 'completed'
      const input = { status: status as 'graded' | 'completed', ...(enteredGrade ? { grade: enteredGrade } : {}) }
      let next: CourseworkHistoryRecord
      if (existing) next = await api.updateCourseworkHistory(taskCourse.id, semester, existing.id, input)
      else next = await api.addCourseworkHistory(taskCourse.id, semester, {
        kind,
        title: task.title,
        task_title: task.title,
        status,
        ...(task.due_date ? { due_date: task.due_date.slice(0, 10) } : {}),
        ...(enteredGrade ? { grade: enteredGrade } : {}),
      })
      setExisting(next)
      setSavedGrade(next.grade || null)
      setGrade(next.grade || '')
      setOpen(false)
      await onChanged()
    } catch (reason) {
      setError(`Could not save this task update. ${String(reason)}`)
    } finally {
      setBusy(false)
    }
  }

  return <div className="task-completion-control">
    {task.completed
      ? <button type="button" className="task-grade-trigger" onClick={() => void openEditor()} data-tooltip="Add or edit the grade for this completed task">{savedGrade ? `Grade · ${savedGrade}` : 'Add grade'}</button>
      : <button type="button" className="task-done-trigger" onClick={() => void openEditor()} data-tooltip="Mark this task done and optionally record a grade">Mark done</button>}
    {open && <div className="task-grade-editor">
      <label><span>{loadingHistory ? 'Loading course record…' : task.completed ? 'Grade' : 'Grade (optional)'}</span><input value={grade} onChange={(event) => setGrade(event.target.value)} maxLength={50} placeholder="e.g. 71/100" disabled={busy || loadingHistory || !taskCourse} /></label>
      {error && <p className="task-grade-error" role="alert">{error}</p>}
      {!taskCourse && <p className="task-grade-error">This task is not linked to a course, so it cannot be saved to course history.</p>}
      <div><button type="button" className="task-save-done" onClick={() => void save(true)} disabled={busy || loadingHistory || historyLoadFailed || !taskCourse || !grade.trim()}>{loadingHistory ? 'Loading…' : busy ? 'Saving…' : task.completed ? 'Save grade' : 'Mark done'}</button>{!task.completed && <button type="button" className="task-skip-grade" onClick={() => void save(false)} disabled={busy || loadingHistory || historyLoadFailed || !taskCourse}>{loadingHistory ? 'Loading…' : busy ? 'Saving…' : 'Skip grade'}</button>}<button type="button" className="task-close-editor" onClick={() => setOpen(false)} disabled={busy || loadingHistory}>Cancel</button></div>
    </div>}
  </div>
}

type ActivityFilter = 'all' | 'processed' | 'not_processed' | 'in_progress' | 'failed' | 'imported' | 'other'

const activityFilters: { id: ActivityFilter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'processed', label: 'Processed' },
  { id: 'not_processed', label: 'Not processed' },
  { id: 'in_progress', label: 'In progress' },
  { id: 'failed', label: 'Failed' },
  { id: 'imported', label: 'Imported' },
  { id: 'other', label: 'Other activity' },
]

function ActivityView({ activity, processing, onNavigate }: { activity: ActivityEvent[]; processing: ProcessingRecord[]; onNavigate: (view: View) => void }) {
  const [filter, setFilter] = useState<ActivityFilter>('all')
  const [showArchive, setShowArchive] = useState(false)
  const currentProcessing = processing
    .filter((record) => record.status.toUpperCase() !== 'ACKNOWLEDGED')
    .map(toProcessingActivity)
  const entries = [...collapseResolvedProcessingFailures(activity, processing), ...currentProcessing]
    .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
  const archiveAge = 30 * 24 * 60 * 60 * 1000
  const cutoff = Date.now() - archiveAge
  const isOpenAttention = (event: ActivityEvent) => ['not_processed', 'in_progress', 'failed'].includes(getActivityFilter(event))
  const recentEntries = entries.filter((event) => isOpenAttention(event) || !Number.isFinite(Date.parse(event.created_at)) || Date.parse(event.created_at) >= cutoff)
  const archivedEntries = entries.filter((event) => !isOpenAttention(event) && Number.isFinite(Date.parse(event.created_at)) && Date.parse(event.created_at) < cutoff)
  const selectedEntries = showArchive ? archivedEntries : recentEntries
  const counts = Object.fromEntries(activityFilters.map(({ id }) => [id, id === 'all' ? selectedEntries.length : selectedEntries.filter((event) => getActivityFilter(event) === id).length])) as Record<ActivityFilter, number>
  const visible = selectedEntries.filter((event) => filter === 'all' || getActivityFilter(event) === filter)
  const emptyTitle: Record<ActivityFilter, string> = {
    all: 'Nothing has changed yet',
    processed: 'No processed files yet',
    not_processed: 'No files waiting to be processed',
    in_progress: 'No processing in progress',
    failed: 'No failed items',
    imported: 'No imports recorded yet',
    other: 'No other activity recorded',
  }
  const emptyBody = filter === 'all'
    ? 'Imports, processing, migrations, and other core actions will appear here with their source, actor, and timestamp.'
    : filter === 'not_processed' || filter === 'in_progress'
      ? 'Current processing status will appear here as files move through the local workflow.'
      : 'Matching events will appear here when Academia OS records them.'

  return <div className="page-stack">
    <PageIntro eyebrow="Audit trail" title="Activity" subtitle="Current and unresolved items stay visible. Resolved activity stays in the recent list for 30 days, then moves to the archive; the underlying audit history is preserved." />
    <section className="activity-page-panel">
      <div className="section-heading">
        <div><p className="eyebrow">{showArchive ? 'Archived activity' : 'Workspace activity'}</p><h3>{visible.length ? `${visible.length} item${visible.length === 1 ? '' : 's'} shown` : emptyTitle[filter]}</h3></div>
        <button className="text-button" onClick={() => onNavigate('home')}>Go to Home <span>→</span></button>
      </div>
      <div className="activity-retention-switch" role="group" aria-label="Choose recent or archived activity"><button type="button" className={!showArchive ? 'active' : ''} aria-pressed={!showArchive} onClick={() => setShowArchive(false)}>Recent · {recentEntries.length}</button><button type="button" className={showArchive ? 'active' : ''} aria-pressed={showArchive} onClick={() => setShowArchive(true)}>Archive · {archivedEntries.length}</button></div>
      <div className="filter-row activity-filter-row" role="group" aria-label="Filter activity">
        {activityFilters.map(({ id, label }) => <button key={id} type="button" data-filter={id} className={`filter-pill activity-filter-pill ${filter === id ? 'active' : ''}`} aria-pressed={filter === id} onClick={() => setFilter(id)}><span>{label}</span><small>{counts[id]}</small></button>)}
      </div>
      {visible.length ? <div className="activity-timeline">{visible.map((event) => <ActivityDetailRow event={event} key={event.id} />)}</div> : <EmptyCard title={emptyTitle[filter]} body={emptyBody} action="Go to Home" onClick={() => onNavigate('home')} />}
    </section>
  </div>
}

function collapseResolvedProcessingFailures(activity: ActivityEvent[], processing: ProcessingRecord[]): ActivityEvent[] {
  const failures = activity.filter((event) => event.event_type === 'file.processing_failed' && event.source)
  const groups: Array<{ source: string; events: ActivityEvent[] }> = []
  for (const event of failures) {
    const group = groups.find((candidate) => sameActivitySource(candidate.source, event.source))
    if (group) group.events.push(event)
    else groups.push({ source: event.source!, events: [event] })
  }

  const summaries: ActivityEvent[] = []
  for (const group of groups) {
    const sortedFailures = [...group.events].sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at))
    const latestFailure = sortedFailures.at(-1)!
    const currentRecord = processing.find((record) => sameActivitySource(record.source_path, group.source))
    const currentStatus = currentRecord?.status.toUpperCase()

    // The live processing record supersedes every older failure for this source.
    // Active work and current failures are represented once by toProcessingActivity.
    if (currentStatus && currentStatus !== 'ACKNOWLEDGED') continue

    const lastFailureTime = Date.parse(latestFailure.created_at)
    const success = activity
      .filter((event) => event.event_type === 'file.processed' && sameActivitySource(event.source, group.source))
      .filter((event) => Date.parse(event.created_at) > lastFailureTime)
      .sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at))[0]

    if (currentStatus === 'ACKNOWLEDGED' || success) {
      const name = group.source.split(/[\\/]/).filter(Boolean).at(-1) || 'file'
      const lastReason = latestFailure.details.reason
      summaries.push({
        id: `processing-recovered:${encodeURIComponent(group.source)}`,
        event_type: 'processing.recovered',
        title: `Recovered on retry · ${name}`,
        course: success?.course || latestFailure.course,
        details: {
          failed_attempt_count: sortedFailures.length,
          ...(typeof lastReason === 'string' ? { last_failure_reason: lastReason } : {}),
        },
        source: group.source,
        actor: success?.actor || 'Academia OS',
        confidence: 'Recovered',
        created_at: success?.created_at || currentRecord?.acknowledged_at || currentRecord?.updated_at || latestFailure.created_at,
      })
      continue
    }

    // Keep one unresolved row per source while retaining the number of logged attempts.
    summaries.push({
      ...latestFailure,
      details: { ...latestFailure.details, failed_attempt_count: sortedFailures.length },
    })
  }

  return [...activity.filter((event) => event.event_type !== 'file.processing_failed' || !event.source), ...summaries]
}

function toProcessingActivity(record: ProcessingRecord): ActivityEvent {
  const name = record.source_path.split(/[\\/]/).filter(Boolean).at(-1) || 'File'
  const status = record.status.toUpperCase()
  const isWaiting = status === 'PENDING' || status === 'DETECTED'
  const isVerified = status === 'VERIFIED'
  const title = status === 'FAILED' ? `Could not process ${name}` : isWaiting ? `Waiting to be processed · ${name}` : isVerified ? `Extracted; awaiting acknowledgement · ${name}` : `Processing · ${name}`
  const confidence = status === 'FAILED' ? 'Failed' : isWaiting ? 'Not processed' : isVerified ? 'Ready for acknowledgement' : 'In progress'
  return { id: `processing:${record.id}`, event_type: 'processing.current', title, details: { status, retry_count: record.retry_count, ...(record.failure_reason ? { reason: record.failure_reason } : {}) }, source: name, actor: 'Academia OS', confidence, created_at: record.updated_at || record.detected_at }
}

function sameActivitySource(left?: string, right?: string) {
  if (!left || !right) return false
  const normalize = (value: string) => value.replaceAll('\\', '/').toLowerCase().replace(/^\/+/, '')
  const a = normalize(left)
  const b = normalize(right)
  return a === b || a.endsWith(`/${b}`) || b.endsWith(`/${a}`)
}

function getActivityFilter(event: ActivityEvent): Exclude<ActivityFilter, 'all'> {
  const type = event.event_type.toLowerCase()
  const status = String(event.details.status || '').toUpperCase()
  if (type === 'processing.recovered') return 'other'
  if (type === 'file.processed' || status === 'ACKNOWLEDGED') return 'processed'
  if (type === 'file.imported') return 'imported'
  if (/processing_failed|action\.failed|\.failed$|unsupported/.test(type) || status === 'FAILED') return 'failed'
  if (type === 'processing.current') return status === 'PENDING' || status === 'DETECTED' ? 'not_processed' : 'in_progress'
  if (/processing|\.pending$/.test(type)) return 'in_progress'
  return 'other'
}

function PageIntro({ eyebrow, title, subtitle }: { eyebrow: string; title: string; subtitle: string }) { return <section className="page-intro"><p className="eyebrow">{eyebrow}</p><h2>{title}</h2><p>{subtitle}</p></section> }
function ActivityDetailRow({ event }: { event: ActivityEvent }) { const detail = Object.entries(event.details).filter(([key]) => !['content', 'body'].includes(key)).slice(0, 3); const category = getActivityFilter(event); const tone = category === 'failed' ? 'tone-overdue' : category === 'not_processed' ? 'tone-soon' : category === 'processed' ? 'tone-completed' : category === 'in_progress' ? 'tone-upcoming' : /review|pending|intake|proposal/.test(event.event_type.toLowerCase()) ? 'tone-soon' : 'tone-upcoming'; return <article className="activity-detail-row"><div className="activity-detail-marker"><span className={`activity-dot ${tone}`} /></div><div className="activity-detail-body"><div className="activity-detail-heading"><div><strong>{event.title}</strong><p>{event.course || 'Workspace'} · {event.actor}</p></div><time dateTime={event.created_at}>{formatActivityDate(event.created_at)}</time></div>{event.source && <p className="activity-source">Source · {event.source}</p>}{detail.length > 0 && <dl>{detail.map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd></div>)}</dl>}<span className="activity-confidence">{event.confidence || event.event_type}</span></div></article> }
function EmptyCard({ title, body, action, onClick }: { title: string; body: string; action: string; onClick?: () => void }) { return <article className="empty-card"><div className="empty-mark">✦</div><h3>{title}</h3><p>{body}</p>{onClick ? <button className="secondary-button" onClick={onClick}>{action} <span>→</span></button> : <span className="muted-copy">{action}</span>}</article> }
function formatActivityDate(value: string): string { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) }

export default App
