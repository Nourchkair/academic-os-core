import { Channel, invoke } from '@tauri-apps/api/core'
import type { AccountStatus, ActivityEvent, AgentSetupPlaybook, AttachmentResult, Course, CourseworkHistoryInput, CourseworkHistoryRecord, DomainEntity, ExtractionPreview, FilePreview, GoogleAuthorizationStart, GoogleAuthorizationStatus, GoogleCalendarEvent, GoogleCalendarProposalResult, GoogleConnectorStatus, ImportResult, ModelConnectionsPayload, ModelProviderInput, ModelRole, NotionPage, NotionPageContent, NotionStatus, LibraryItem, MCPAuthorizationStart, MCPAuthorizationStatus, MCPConnection, MCPConnectionInput, MCPRemoteInput, MigrationExecuteResult, MigrationPlanResult, MigrationStatusResult, PlaybooksPayload, ProcessingRecord, RecommendationsPayload, ReviewItem, SettingsPreview, StatusPayload, Task, TaskInput, TaskListPayload, TaskProposalAmendment, WorkflowPreferencesPayload, WorkflowResetPayload, WorkflowSetPayload, WorkflowShowPayload, WorkspaceCandidate, WorkspaceCreationResult, WorkspaceInspection, WorkspaceSnapshot } from '../types'

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

function newRunId() {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return `run-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

async function nativeChatStream<T>(payload: Record<string, unknown>, onEvent: (event: ChatStreamEvent) => void, signal?: AbortSignal): Promise<T> {
  const runId = newRunId()
  const channel = new Channel<ChatStreamEvent>()
  let final: T | null = null
  let failure: string | null = null
  let cancelled = false
  channel.onmessage = (event) => {
    onEvent(event)
    if (event.type === 'final') final = event as unknown as T
    else if (event.type === 'error') failure = typeof event.message === 'string' ? event.message : 'Codex could not complete this chat request.'
    else if (typeof event.error === 'string') failure = event.error
    else if (event.type === 'cancelled') cancelled = true
  }
  const abort = () => { void invoke('academia_chat_cancel', { runId }).catch(() => undefined) }
  signal?.addEventListener('abort', abort)
  try {
    await invoke('academia_chat_stream', { payload, runId, onEvent: channel })
  } catch (reason) {
    if (signal?.aborted || cancelled) throw new ChatCancelledError()
    if (failure) throw new ChatStreamError(failure)
    throw reason instanceof Error ? reason : new ChatStreamError(String(reason))
  } finally {
    signal?.removeEventListener('abort', abort)
  }
  if (signal?.aborted || cancelled) throw new ChatCancelledError()
  if (failure) throw new ChatStreamError(failure)
  if (final === null) throw new ChatStreamError('The native chat stream ended before a final answer.')
  return final
}

type NativeAccountEvent = { type: string; state?: AccountStatus; message?: string; error?: unknown }

let activeAccountRunId: string | null = null

async function nativeAccountCommand<T>(args: string[]): Promise<T> {
  const raw = await invoke<string>('academia_command', { command: 'account', args: [...args, '--json'] })
  const value = JSON.parse(raw) as T & { error?: unknown }
  if (value && typeof value === 'object' && typeof value.error === 'string') throw new Error(value.error)
  return value
}

async function nativeAccountLogin(onUpdate?: (status: AccountStatus) => void): Promise<AccountStatus> {
  const runId = newRunId()
  activeAccountRunId = runId
  const channel = new Channel<NativeAccountEvent>()
  let latest: AccountStatus | null = null
  let failure: string | null = null
  channel.onmessage = (event) => {
    if ((event.type === 'verification' || event.type === 'final') && event.state) {
      latest = event.state
      onUpdate?.(event.state)
    } else if (event.type === 'error' && typeof event.message === 'string') {
      failure = event.message
    } else if (typeof event.error === 'string') {
      failure = event.error
    }
  }
  try {
    await invoke('academia_account_login_stream', { runId, onEvent: channel })
  } catch (reason) {
    if (failure) throw new Error(failure)
    throw reason instanceof Error ? reason : new Error(String(reason))
  } finally {
    if (activeAccountRunId === runId) activeAccountRunId = null
  }
  if (failure) throw new Error(failure)
  return latest ?? nativeAccountCommand<AccountStatus>(['status'])
}

async function nativeAccountLoginCancel(): Promise<AccountStatus> {
  const runId = activeAccountRunId
  if (runId) await nativeAccountCommand<{ run_id: string; cancelled: boolean }>(['login-cancel', '--run-id', runId])
  return nativeAccountCommand<AccountStatus>(['status'])
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

export type PendingAction = {
  proposal_id: string
  action_type: string
  title: string
  tier: 'auto' | 'inline' | 'review'
  review_id?: string | null
  preview: {
    title?: string
    summary?: string
    changes?: Array<{ label: string; from: string | null; to: string | null }>
  } | null
  created_at: string
}

export type ActionExecution = {
  proposal_id: string
  action_type: string
  status: string
  tier: string
  verification: Record<string, unknown>
}

export const api = {
  study: <T>(args: string[]) => command<T>("study", args),
  chat: <T>(payload: Record<string, unknown>) => isTauriEnvironment() ? invoke<string>('academia_chat', { payload }).then((raw) => JSON.parse(raw) as T) : browserChat(payload) as Promise<T>,
  chatStream: <T>(payload: Record<string, unknown>, onEvent: (event: ChatStreamEvent) => void, signal?: AbortSignal) => isTauriEnvironment() ? nativeChatStream<T>(payload, onEvent, signal) : browserChatStream<T>(payload, onEvent, signal),
  chatCancel: (runId: string) => isTauriEnvironment() ? invoke<{ run_id: string; cancelled: boolean }>('academia_chat_cancel', { runId }) : fetch('/api/v1/chat/cancel', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ run_id: runId }) }).then(readJsonResponse<{ run_id: string; cancelled: boolean }>),
  accountStatus: () => isTauriEnvironment() ? nativeAccountCommand<AccountStatus>(['status']) : fetch('/api/v1/account').then(readJsonResponse<AccountStatus>),
  accountLogin: (onUpdate?: (status: AccountStatus) => void) => isTauriEnvironment() ? nativeAccountLogin(onUpdate) : fetch('/api/v1/account/login', { method: 'POST' }).then(readJsonResponse<AccountStatus>),
  accountLoginCancel: () => isTauriEnvironment() ? nativeAccountLoginCancel() : fetch('/api/v1/account/login/cancel', { method: 'POST' }).then(readJsonResponse<AccountStatus>),
  accountLogout: () => isTauriEnvironment() ? nativeAccountCommand<AccountStatus>(['logout']) : fetch('/api/v1/account/logout', { method: 'POST' }).then(readJsonResponse<AccountStatus>),
  googleConnectorStatus: () => isTauriEnvironment() ? command<GoogleConnectorStatus>('connectors', ['google', 'status']) : fetch('/api/v1/connectors/google').then(readJsonResponse<GoogleConnectorStatus>),
  importPreflight: (paths: string[], destination: string) => postJson<{
    destination: string
    files: Array<{
      path: string
      name: string
      status: 'ready' | 'missing'
      reason?: string
      size?: number
      extension?: string
      extractable?: boolean
      ocr_may_be_needed?: boolean
      image?: boolean
      duplicate?: { name: string; path: string; identical: boolean; same_name: boolean } | null
    }>
    ready: number
    duplicates: number
  }>('/api/v1/import/preflight', { paths, destination }),
  importPreflightDesktop: (paths: string[], destination: string) => command<{ files: Array<{ path: string; name: string; status: 'ready' | 'missing'; reason?: string; size?: number; extension?: string; extractable?: boolean; ocr_may_be_needed?: boolean; duplicate?: { name: string; path: string; identical: boolean; same_name: boolean } | null }>; ready: number; duplicates: number }>('import-preflight', ['--destination', destination, ...paths.flatMap((path) => ['--path', path]), '--json']),
  reviewAdvice: (reviewId: string) => isTauriEnvironment() ? command<{ review_id: string; kind: string; options: Array<{ decision: string; label: string; rationale: string }>; recommended: string; note: string; model: string }>('review', ['advice', reviewId, '--json']) : postJson<{
    review_id: string
    kind: string
    options: Array<{ decision: string; label: string; rationale: string }>
    recommended: string
    note: string
    model: string
  }>('/api/v1/review/advice', { review_id: reviewId }),
  actionPending: () => isTauriEnvironment() ? command<{ actions: PendingAction[] }>('actions', ['pending', '--json']) : fetch('/api/v1/actions/pending').then(readJsonResponse<{ actions: PendingAction[] }>),
  actionExecute: (proposalId: string) => isTauriEnvironment() ? command<ActionExecution>('actions', ['execute', proposalId, '--json']) : postJson<ActionExecution>('/api/v1/actions/execute', { proposal_id: proposalId }),
  actionDiscard: (proposalId: string) => isTauriEnvironment() ? command<{ proposal_id: string; discarded: boolean }>('actions', ['discard', proposalId, '--json']) : postJson<{ proposal_id: string; discarded: boolean }>('/api/v1/actions/discard', { proposal_id: proposalId }),
  modelConnections: () => isTauriEnvironment() ? command<ModelConnectionsPayload>('models', ['list']) : fetch('/api/v1/models').then(readJsonResponse<ModelConnectionsPayload>),
  notionStatus: () => isTauriEnvironment() ? command<NotionStatus>('connectors', ['notion', 'status']) : fetch('/api/v1/connectors/notion').then(readJsonResponse<NotionStatus>),
  connectNotion: (token: string) => isTauriEnvironment() ? invoke<string>('academia_notion_setup', { payload: { token } }).then((raw) => JSON.parse(raw) as NotionStatus) : postJson<NotionStatus>('/api/v1/connectors/notion/setup', { token }),
  testNotion: () => isTauriEnvironment() ? command<NotionStatus>('connectors', ['notion', 'test']) : postJson<NotionStatus>('/api/v1/connectors/notion/test', {}),
  disconnectNotion: () => isTauriEnvironment() ? command<NotionStatus>('connectors', ['notion', 'disconnect']) : postJson<NotionStatus>('/api/v1/connectors/notion/disconnect', {}),
  searchNotion: (query = '', max = 10) => isTauriEnvironment() ? command<{ query: string; count: number; pages: NotionPage[] }>('connectors', ['notion', 'search', '--query', query, '--max', String(max)]) : postJson<{ query: string; count: number; pages: NotionPage[] }>('/api/v1/connectors/notion/search', { query, max }),
  readNotionPage: (pageId: string) => isTauriEnvironment() ? command<NotionPageContent>('connectors', ['notion', 'read', pageId, '--max-blocks', '100']) : postJson<NotionPageContent>('/api/v1/connectors/notion/read', { page_id: pageId, max_blocks: 100 }),
  addModelProvider: (input: ModelProviderInput) => isTauriEnvironment() ? invoke<string>('academia_models_add', { payload: input }).then((raw) => JSON.parse(raw) as ModelConnectionsPayload) : postJson<ModelConnectionsPayload>('/api/v1/models/add', input),
  testModelProvider: (provider: string) => isTauriEnvironment() ? command<ModelConnectionsPayload>('models', ['test', provider]) : postJson<ModelConnectionsPayload>('/api/v1/models/test', { provider }),
  removeModelProvider: (provider: string) => isTauriEnvironment() ? command<ModelConnectionsPayload>('models', ['remove', provider]) : postJson<ModelConnectionsPayload>('/api/v1/models/remove', { provider }),
  setModelProviderEnabled: (provider: string, enabled: boolean) => isTauriEnvironment() ? command<ModelConnectionsPayload>('models', [enabled ? 'enable' : 'disable', provider]) : postJson<ModelConnectionsPayload>(enabled ? '/api/v1/models/enable' : '/api/v1/models/disable', { provider }),
  setModelPreferences: (preferences: Partial<Record<ModelRole, string | null>>) => isTauriEnvironment() ? command<ModelConnectionsPayload>('models', ['set-preferences', ...Object.entries(preferences).flatMap(([role, value]) => value !== undefined ? [`--${role}`, value ?? ''] : [])]) : postJson<ModelConnectionsPayload>('/api/v1/models/set-preferences', preferences),
  googleConnectorAuthStatus: () => isTauriEnvironment() ? command<GoogleAuthorizationStatus>('connectors', ['google', 'oauth-status']) : postJson<GoogleAuthorizationStatus>('/api/v1/connectors/google/oauth-status', {}),
  beginGoogleAuthorization: () => postJson<GoogleAuthorizationStart>('/api/v1/connectors/google/authorize', {}),
  finishGoogleAuthorization: () => command<GoogleConnectorStatus>('connectors', ['google', 'authorize']),
  cancelGoogleAuthorization: () => isTauriEnvironment() ? command<GoogleConnectorStatus>('connectors', ['google', 'oauth-cancel']) : postJson<GoogleConnectorStatus>('/api/v1/connectors/google/oauth-cancel', {}),
  disconnectGoogleConnector: () => isTauriEnvironment() ? command<GoogleConnectorStatus>('connectors', ['google', 'disconnect']) : postJson<GoogleConnectorStatus>('/api/v1/connectors/google/disconnect', {}),
  setupGoogleConnector: (input: { client_id: string; client_secret: string }) => postJson<GoogleConnectorStatus>('/api/v1/connectors/google/setup', input),
  setupGoogleConnectorFromPath: (path: string) => command<GoogleConnectorStatus>('connectors', ['google', 'setup', '--client-json', path]),
  googleCalendarEvents: (days = 14) => {
    const timeMin = new Date().toISOString()
    const timeMax = new Date(Date.now() + Math.min(Math.max(days, 1), 60) * 24 * 60 * 60 * 1000).toISOString()
    if (isTauriEnvironment()) {
      return command<{ time_min: string; time_max: string; count: number; events: GoogleCalendarEvent[] }>(
        'connectors', ['google', 'calendar', 'list', '--time-min', timeMin, '--time-max', timeMax, '--max', '20'],
      )
    }
    const query = new URLSearchParams({ time_min: timeMin, time_max: timeMax, max: '20' })
    return fetch(`/api/v1/connectors/google/calendar/events?${query.toString()}`).then(readJsonResponse<{ time_min: string; time_max: string; count: number; events: GoogleCalendarEvent[] }>)
  },
  proposeGoogleCalendarCreate: (event: { summary: string; start: string; end: string; location?: string; description?: string }) => {
    if (isTauriEnvironment()) {
      const args = ['google', 'calendar', 'propose-create', '--summary', event.summary, '--start', event.start, '--end', event.end]
      if (event.location) args.push('--location', event.location)
      if (event.description) args.push('--description', event.description)
      return command<GoogleCalendarProposalResult>('connectors', args)
    }
    return postJson<GoogleCalendarProposalResult>('/api/v1/connectors/google/calendar/propose-create', event)
  },
  proposeGoogleCalendarUpdate: (eventId: string, patch: Record<string, string>) => {
    if (isTauriEnvironment()) {
      const args = ['google', 'calendar', 'propose-update', eventId]
      for (const [key, value] of Object.entries(patch)) {
        if (key === 'location' && value === '') args.push('--clear-location')
        else if (key === 'description' && value === '') args.push('--clear-description')
        else args.push(`--${key.replaceAll('_', '-')}`, value)
      }
      return command<GoogleCalendarProposalResult>('connectors', args)
    }
    return postJson<GoogleCalendarProposalResult>('/api/v1/connectors/google/calendar/propose-update', { event_id: eventId, patch })
  },
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
  chatProviders: <T>() => isTauriEnvironment() ? command<T>('chat-providers') : fetch('/api/v1/chat/providers').then(readJsonResponse<T>),
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
