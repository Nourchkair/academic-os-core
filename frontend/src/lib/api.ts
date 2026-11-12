import { invoke } from '@tauri-apps/api/core'
import type { AccountStatus, ActivityEvent, AgentSetupPlaybook, AttachmentResult, Course, CourseworkHistoryInput, CourseworkHistoryRecord, DomainEntity, ExtractionPreview, FilePreview, ImportResult, LibraryItem, MCPAuthorizationStart, MCPAuthorizationStatus, MCPConnection, MCPConnectionInput, MCPRemoteInput, MigrationExecuteResult, MigrationPlanResult, MigrationStatusResult, PlaybooksPayload, ProcessingRecord, RecommendationsPayload, ReviewItem, SettingsPreview, StatusPayload, Task, TaskInput, TaskListPayload, TaskProposalAmendment, WorkflowPreferencesPayload, WorkflowResetPayload, WorkflowSetPayload, WorkflowShowPayload, WorkspaceCandidate, WorkspaceCreationResult, WorkspaceInspection, WorkspaceSnapshot } from '../types'

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

export class ChatStreamError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ChatStreamError'
  }
}

export class ChatCancelledError extends Error {
  constructor() {
    super('The assistant run was cancelled.')
    this.name = 'ChatCancelledError'
  }
}

export type ChatStreamEvent = {
  type: string
  [key: string]: unknown
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

async function browserChatStream<T>(payload: Record<string, unknown>, onEvent: (event: ChatStreamEvent) => void, signal?: AbortSignal): Promise<T> {
  let response: Response
  try {
    response = await fetch('/api/v1/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal,
    })
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw error
    throw new BridgeUnavailableError()
  }
  if (!response.ok) return readJsonResponse<never>(response)
  if (!response.body) throw new ChatStreamError('The local dashboard did not return a chat stream.')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let final: T | null = null
  const processLine = (line: string) => {
    const trimmed = line.trim()
    if (!trimmed) return
    let event: ChatStreamEvent
    try {
      event = JSON.parse(trimmed) as ChatStreamEvent
    } catch {
      throw new ChatStreamError('The local chat stream returned invalid data.')
    }
    onEvent(event)
    if (event.type === 'final') {
      final = event as unknown as T
    } else if (event.type === 'error') {
      throw new ChatStreamError(typeof event.message === 'string' ? event.message : 'Codex could not complete this chat request.')
    } else if (event.type === 'cancelled') {
      throw new ChatCancelledError()
    }
  }
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let newline = buffer.indexOf('\n')
      while (newline >= 0) {
        processLine(buffer.slice(0, newline))
        buffer = buffer.slice(newline + 1)
        newline = buffer.indexOf('\n')
      }
    }
    buffer += decoder.decode()
    processLine(buffer)
  } catch (error) {
    await reader.cancel().catch(() => undefined)
    throw error
  }
  if (final === null) throw new ChatStreamError('The local chat stream ended before a final answer.')
  return final
}

export function fileUrl(path: string, semester?: string): string {
  const query = new URLSearchParams({ path })
  if (semester) query.set('semester', semester)
  return `/api/v1/file?${query.toString()}`
}

async function postJson<T>(path: string, body: Record<string, unknown>): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  } catch {
    throw new BridgeUnavailableError()
  }
  return readJsonResponse<T>(response)
}

export const api = {
  study: <T>(args: string[]) => command<T>("study", args),
  chat: <T>(payload: Record<string, unknown>) => isTauriEnvironment() ? invoke<string>('academia_chat', { payload }).then((raw) => JSON.parse(raw) as T) : browserChat(payload) as Promise<T>,
  chatStream: <T>(payload: Record<string, unknown>, onEvent: (event: ChatStreamEvent) => void, signal?: AbortSignal) => browserChatStream<T>(payload, onEvent, signal),
  chatCancel: (runId: string) => fetch('/api/v1/chat/cancel', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ run_id: runId }) }).then(readJsonResponse<{ run_id: string; cancelled: boolean }>),
  accountStatus: () => fetch('/api/v1/account').then(readJsonResponse<AccountStatus>),
  accountLogin: () => fetch('/api/v1/account/login', { method: 'POST' }).then(readJsonResponse<AccountStatus>),
  accountLoginCancel: () => fetch('/api/v1/account/login/cancel', { method: 'POST' }).then(readJsonResponse<AccountStatus>),
  accountLogout: () => fetch('/api/v1/account/logout', { method: 'POST' }).then(readJsonResponse<AccountStatus>),
  mcpConnections: () => isTauriEnvironment() ? command<MCPConnection[]>('mcp-connections', ['list']) : fetch('/api/v1/mcp/connections').then(readJsonResponse<MCPConnection[]>),
  addMCPConnection: (input: MCPConnectionInput) => {
    if (isTauriEnvironment()) {
      const args = ['add', '--name', input.name, '--command', input.command]
      for (const value of input.args) args.push('--arg', value)
      if (input.cwd) args.push('--cwd', input.cwd)
      return command<MCPConnection>('mcp-connections', args)
    }
    return postJson<MCPConnection>('/api/v1/mcp/connections', input)
  },
  addRemoteMCPConnection: (input: MCPRemoteInput) => isTauriEnvironment() ? command<MCPConnection>('mcp-connections', ['add-remote', '--name', input.name, '--url', input.url]) : postJson<MCPConnection>('/api/v1/mcp/connections/add-remote', input),
  authorizeMCPConnection: (id: string) => isTauriEnvironment() ? command<MCPAuthorizationStatus>('mcp-connections', ['authorize', id]) : postJson<MCPAuthorizationStart>('/api/v1/mcp/connections/authorize', { id }),
  mcpOAuthStatus: (id: string) => isTauriEnvironment() ? command<MCPAuthorizationStatus>('mcp-connections', ['oauth-status', id]) : postJson<MCPAuthorizationStatus>('/api/v1/mcp/connections/oauth-status', { id }),
  cancelMCPAuthorization: (id: string) => isTauriEnvironment() ? command<MCPAuthorizationStatus>('mcp-connections', ['oauth-cancel', id]) : postJson<MCPAuthorizationStatus>('/api/v1/mcp/connections/oauth-cancel', { id }),
  trustMCPConnection: (id: string) => isTauriEnvironment() ? command<MCPConnection>('mcp-connections', ['trust', id]) : postJson<MCPConnection>('/api/v1/mcp/connections/trust', { id }),
  inspectMCPConnection: (id: string) => isTauriEnvironment() ? command<MCPConnection>('mcp-connections', ['inspect', id]) : postJson<MCPConnection>('/api/v1/mcp/connections/inspect', { id }),
  grantMCPConnection: (id: string, tools: string[]) => {
    if (isTauriEnvironment()) {
      const args = ['grant', id]
      for (const tool of tools) args.push('--tool', tool)
      return command<MCPConnection>('mcp-connections', args)
    }
    return postJson<MCPConnection>('/api/v1/mcp/connections/grant', { id, tools })
  },
  enableMCPConnection: (id: string) => isTauriEnvironment() ? command<MCPConnection>('mcp-connections', ['enable', id]) : postJson<MCPConnection>('/api/v1/mcp/connections/enable', { id }),
  disableMCPConnection: (id: string) => isTauriEnvironment() ? command<MCPConnection>('mcp-connections', ['disable', id]) : postJson<MCPConnection>('/api/v1/mcp/connections/disable', { id }),
  disconnectMCPConnection: (id: string) => isTauriEnvironment() ? command<MCPConnection>('mcp-connections', ['disconnect', id]) : postJson<MCPConnection>('/api/v1/mcp/connections/disconnect', { id }),
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
  reviewShow: (itemId: string) => command<ReviewItem>('review', ['show', itemId]),
  reviewPendingExecution: () => command<ReviewItem[]>('review', ['list', '--pending-execution']),
  reviewAction: (action: 'approve' | 'reject' | 'resolve', itemId: string) => command<ReviewItem>('review', [action, itemId]),
  reviewDecision: (itemId: string, decision: string) => command<ReviewItem>('review', ['decide', itemId, decision]),
  reviewExecute: (itemId: string) => command<Record<string, unknown>>('review', ['execute', itemId]),
  amendReview: (itemId: string, fields: TaskProposalAmendment) => command<ReviewItem>('review', ['amend', itemId, ...taskAmendmentArgs(fields)]),
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

function taskAmendmentArgs(input: TaskProposalAmendment): string[] {
  const args: string[] = []
  if (input.title !== undefined) args.push('--task-title', input.title)
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
