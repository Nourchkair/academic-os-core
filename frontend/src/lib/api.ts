import { invoke } from '@tauri-apps/api/core'
import type { ActivityEvent, AgentSetupPlaybook, AttachmentResult, Course, CourseworkHistoryInput, CourseworkHistoryRecord, DomainEntity, ExtractionPreview, FilePreview, ImportResult, LibraryItem, MigrationExecuteResult, MigrationPlanResult, MigrationStatusResult, PlaybooksPayload, ProcessingRecord, RecommendationsPayload, ReviewItem, SettingsPreview, StatusPayload, Task, TaskInput, TaskListPayload, WorkflowPreferencesPayload, WorkflowResetPayload, WorkflowSetPayload, WorkflowShowPayload, WorkspaceCandidate, WorkspaceCreationResult, WorkspaceInspection, WorkspaceSnapshot } from '../types'

export class BridgeUnavailableError extends Error {
  constructor() {
    super('The Academia OS local dashboard is unavailable. Start `academia` in a terminal, or launch the packaged app.')
    this.name = 'BridgeUnavailableError'
  }
}

export class DashboardApiError extends Error {
  readonly status: number
  readonly type: string

  constructor(status: number, type: string, message: string) {
    super(message)
    this.name = 'DashboardApiError'
    this.status = status
    this.type = type
  }
}

export function isTauriEnvironment() {
  return typeof window !== 'undefined' && Boolean((window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__)
}

type StructuredApiError = {
  error?: unknown
  type?: unknown
}

async function readJsonResponse<T>(response: Response): Promise<T> {
  const text = await response.text()
  let value: unknown
  try {
    value = text ? JSON.parse(text) : null
  } catch {
    throw new Error(`The local dashboard returned an invalid response (HTTP ${response.status}).`)
  }

  if (!response.ok) {
    const structured = value && typeof value === 'object' ? value as StructuredApiError : undefined
    const message = typeof structured?.error === 'string' ? structured.error : `Local dashboard request failed (HTTP ${response.status}).`
    const type = typeof structured?.type === 'string' ? structured.type : 'DashboardRequestError'
    throw new DashboardApiError(response.status, type, message)
  }
  return value as T
}

async function browserCommand<T>(name: string, args: string[]): Promise<T> {
  let response: Response
  try {
    response = await fetch('/api/v1/command', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: name, args }),
    })
  } catch {
    throw new BridgeUnavailableError()
  }
  return readJsonResponse<T>(response)
}

async function command<T>(name: string, args: string[] = []): Promise<T> {
  if (!isTauriEnvironment()) return browserCommand<T>(name, args)

  try {
    const result = await invoke<string>('academia_command', { command: name, args: [...args, '--json'] })
    return JSON.parse(result) as T
  } catch (error) {
    if (String(error).includes('not implemented') || String(error).includes('Failed to fetch')) {
      throw new BridgeUnavailableError()
    }
    throw error
  }
}

async function uploadFile(file: File, destination: string, uncertain: boolean): Promise<ImportResult> {
  const query = new URLSearchParams({ filename: file.name, destination })
  if (uncertain) query.set('uncertain', '1')

  let response: Response
  try {
    response = await fetch(`/api/v1/upload?${query.toString()}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: file,
    })
  } catch {
    throw new BridgeUnavailableError()
  }
  return readJsonResponse<ImportResult>(response)
}

async function browserFilePreview(path: string, semester?: string): Promise<FilePreview> {
  let response: Response
  try {
    const query = new URLSearchParams({ path })
    if (semester) query.set('semester', semester)
    response = await fetch(`/api/v1/file-preview?${query.toString()}`)
  } catch {
    throw new BridgeUnavailableError()
  }
  return readJsonResponse<FilePreview>(response)
}

async function browserChat(payload: Record<string, unknown>): Promise<{ message: string; model: string | null; effort: string; speed: string; notice: string | null }> {
  let response: Response
  try {
    response = await fetch('/api/v1/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
  } catch {
    throw new BridgeUnavailableError()
  }
  return readJsonResponse(response)
}

export function fileUrl(path: string, semester?: string): string {
  const query = new URLSearchParams({ path })
  if (semester) query.set('semester', semester)
  return `/api/v1/file?${query.toString()}`
}

export const api = {
  study: <T>(args: string[]) => command<T>("study", args),
  chat: <T>(payload: Record<string, unknown>) => isTauriEnvironment() ? invoke<string>('academia_chat', { payload }).then((raw) => JSON.parse(raw) as T) : browserChat(payload) as Promise<T>,
  chatProviders: <T>() => isTauriEnvironment() ? command<T>('study', ['providers']) : fetch('/api/v1/chat/providers').then(readJsonResponse<T>),
  status: () => command<StatusPayload>('status'),
  startupStatus: () => command<StatusPayload>('status', ['--fast']),
  courses: (semester?: string) => command<Course[]>('courses', semester ? ['--semester', semester] : []),
  tasks: (semester?: string) => command<TaskListPayload>('task', ['list', ...(semester ? ['--semester', semester] : [])]),
  createTask: (semester: string, input: TaskInput) => command<Task>('task', ['create', '--semester', semester, ...taskInputArgs(input)]),
  updateTask: (semester: string, taskId: string, input: Partial<TaskInput>) => command<Task>('task', ['update', taskId, '--semester', semester, ...taskUpdateArgs(input)]),
  completeTask: (semester: string, taskId: string) => command<Task>('task', ['complete', taskId, '--semester', semester]),
  reopenTask: (semester: string, taskId: string) => command<Task>('task', ['reopen', taskId, '--semester', semester]),
  agentCourseContext: (courseId: string, semester: string) => command<{ current_state?: { open_tasks?: Task[] } }>('agent', ['context', '--scope', 'course', '--course', courseId, '--semester', semester, '--detail', 'deep']),
  review: () => command<ReviewItem[]>('review'),
  reviewPendingExecution: () => command<ReviewItem[]>('review', ['list', '--pending-execution']),
  reviewAction: (action: 'approve' | 'reject' | 'resolve', itemId: string) => command<ReviewItem>('review', [action, itemId]),
  reviewDecision: (itemId: string, decision: string) => command<ReviewItem>('review', ['decide', itemId, decision]),
  reviewExecute: (itemId: string) => command<Record<string, unknown>>('review', ['execute', itemId]),
  activity: () => command<ActivityEvent[]>('activity'),
  processingStatus: () => command<ProcessingRecord[]>('process', ['status']),
  domain: (entityType?: string) => command<DomainEntity[]>('domain', entityType ? [entityType] : []),
  courseworkHistory: (courseId: string, semester: string) => command<CourseworkHistoryRecord[]>('history', ['list', '--course', courseId, '--semester', semester]),
  addCourseworkHistory: (courseId: string, semester: string, input: CourseworkHistoryInput) => command<CourseworkHistoryRecord>('history', courseworkHistoryArgs('add', courseId, semester, input)),
  updateCourseworkHistory: (courseId: string, semester: string, recordId: string, input: Partial<CourseworkHistoryInput>) => command<CourseworkHistoryRecord>('history', [...courseworkHistoryArgs('update', courseId, semester, input), '--id', recordId]),
  library: (options: { category?: string; courseId?: string; query?: string; semester?: string } = {}) => {
    const args = []
    if (options.semester) args.push('--semester', options.semester)
    if (options.category && options.category !== 'all') args.push('--category', options.category)
    if (options.courseId) args.push('--course', options.courseId)
    if (options.query) args.push('--query', options.query)
    return command<LibraryItem[]>('library', args)
  },
  filePreview: (path: string, semester?: string) => isTauriEnvironment() ? command<FilePreview>('file-preview', [path, ...(semester ? ['--semester', semester] : []), '--include-image-data']) : browserFilePreview(path, semester),
  inbox: () => command<ProcessingRecord[]>('inbox'),
  workspace: () => command<WorkspaceSnapshot>('workspace'),
  workspaceDiscover: () => command<WorkspaceCandidate[]>('workspace', ['discover']),
  workspaceInspect: (path: string) => command<WorkspaceInspection>('workspace', ['inspect', path]),
  workspaceAttach: (input: { path: string; name: string; institution: string; program: string; timezone: string; semester: string; apply: boolean }) => {
    const args = [
      'attach', input.path,
      '--name', input.name,
      '--institution', input.institution,
      '--program', input.program,
      '--timezone', input.timezone,
      '--semester', input.semester,
    ]
    if (input.apply) args.push('--apply')
    return command<AttachmentResult>('workspace', args)
  },
  workspaceCreate: (input: { path: string; name: string; institution: string; program: string; timezone: string; semester: string; apply: boolean }) => {
    const args = [
      'create', input.path,
      '--name', input.name,
      '--institution', input.institution,
      '--program', input.program,
      '--timezone', input.timezone,
      '--semester', input.semester,
    ]
    if (input.apply) args.push('--apply')
    return command<WorkspaceCreationResult>('workspace', args)
  },
  importFile: (source: string, destination: string, uncertain: boolean) => command<ImportResult>('import', [source, '--destination', destination, ...(uncertain ? ['--uncertain'] : [])]),
  uploadFile,
  migrationPlan: (source: string) => command<MigrationPlanResult>('migration', ['plan', source]),
  migrationStatus: (planPath: string) => command<MigrationStatusResult>('migration', ['status', '--plan', planPath]),
  migrationExecute: (planPath: string, indexes: number[], mode: 'copy' | 'move', apply: boolean, confirmMove: boolean) => {
    const args = ['execute', '--plan', planPath]
    for (const index of indexes) args.push('--item', String(index))
    args.push('--mode', mode)
    if (confirmMove) args.push('--confirm-move')
    if (apply) args.push('--apply')
    return command<MigrationExecuteResult>('migration', args)
  },
  extractSyllabus: (source: string, course: string, verifiedCurrent: boolean, apply: boolean) => command<ExtractionPreview>('extract', ['syllabus', source, '--course', course, ...(verifiedCurrent ? ['--verified-current'] : []), ...(apply ? ['--apply'] : [])]),
  settings: () => command<Record<string, unknown>>('settings', ['show']),
  settingsUpdate: (updates: Record<string, unknown>, apply: boolean, approveStructural: boolean) => {
    const args = ['update']
    for (const [key, value] of Object.entries(updates)) args.push('--set', `${key}=${JSON.stringify(value)}`)
    if (apply) args.push('--apply')
    if (approveStructural) args.push('--approve-structural')
    return command<SettingsPreview>('settings', args)
  },
  capabilities: () => command<Record<string, unknown>>('capabilities'),
  playbooks: () => command<PlaybooksPayload>('agent', ['playbooks']),
  /** @deprecated Use playbooks(). */
  recommendations: () => command<RecommendationsPayload>('agent', ['recommendations']),
  /** @deprecated Use playbook(). */
  recipe: (workflowId: string) => command<Record<string, unknown>>('agent', ['recipe', workflowId]),
  playbook: (playbookId: string) => command<AgentSetupPlaybook>('agent', ['playbook', playbookId]),
  workflowPreferences: () => command<WorkflowPreferencesPayload>('workflow', ['preferences']),
  workflowShow: (workflowId: string) => command<WorkflowShowPayload>('workflow', ['show', workflowId]),
  workflowReset: (workflowId: string) => command<WorkflowResetPayload>('workflow', ['reset', workflowId]),
  workflowSet: (workflowId: string, preferences: Record<string, unknown>, customInstructions: string, externalSetupNotes: string, updatedBy = 'user', replacePreferences = false) => {
    const args = ['set', workflowId]
    if (replacePreferences) args.push('--preferences-json', JSON.stringify(preferences), '--replace-preferences')
    else for (const [key, value] of Object.entries(preferences)) args.push('--set', `${key}=${JSON.stringify(value)}`)
    args.push('--custom-instructions', customInstructions, '--external-setup-notes', externalSetupNotes, '--updated-by', updatedBy)
    return command<WorkflowSetPayload>('workflow', args)
  },
  semester: (timezone: string) => command<{ semester: string; timezone: string }>('semester', ['--timezone', timezone]),
}

function taskInputArgs(input: TaskInput): string[] {
  const args = ['--title', input.title]
  if (input.course_id) args.push('--course', input.course_id)
  if (input.due_date) args.push('--due-date', input.due_date)
  if (input.due_time) args.push('--due-time', input.due_time)
  return args
}

function taskUpdateArgs(input: Partial<TaskInput>): string[] {
  const args: string[] = []
  if (input.title !== undefined) args.push('--title', input.title)
  if (input.course_id !== undefined) {
    if (input.course_id) args.push('--course', input.course_id)
    else args.push('--clear-course')
  }
  if (input.due_date !== undefined) {
    if (input.due_date) args.push('--due-date', input.due_date)
    else args.push('--clear-due-date')
  }
  if (input.due_time !== undefined) {
    if (input.due_time) args.push('--due-time', input.due_time)
    else args.push('--clear-due-time')
  }
  return args
}

function courseworkHistoryArgs(action: 'add' | 'update', courseId: string, semester: string, input: Partial<CourseworkHistoryInput>): string[] {  const args = [action, '--course', courseId, '--semester', semester]
  const pairs: Array<[keyof CourseworkHistoryInput, string]> = [
    ['kind', '--kind'], ['title', '--title'], ['status', '--status'], ['due_date', '--due-date'],
    ['submitted_on', '--submitted-on'], ['grade', '--grade'], ['task_title', '--task-title'], ['notes', '--notes'],
  ]
  for (const [key, flag] of pairs) {
    const value = input[key]
    if (value !== undefined) args.push(flag, String(value))
  }
  if (input.artifact_paths?.length) for (const path of input.artifact_paths) args.push('--artifact', path)
  else if (action === 'update' && input.artifact_paths !== undefined) args.push('--clear-artifacts')
  return args
}
