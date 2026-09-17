import { invoke } from '@tauri-apps/api/core'
import type { ActivityEvent, AttachmentResult, Course, DomainEntity, ExtractionPreview, ImportResult, MigrationExecuteResult, MigrationPlanResult, MigrationStatusResult, ReviewItem, SettingsPreview, StatusPayload, Task, WorkspaceCandidate, WorkspaceCreationResult, WorkspaceInspection, WorkspaceSnapshot } from '../types'

export class BridgeUnavailableError extends Error {
  constructor() {
    super('The Academia OS local dashboard is unavailable. Start `academia dashboard --open` in a terminal, or launch the packaged app.')
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

export const api = {
  status: () => command<StatusPayload>('status'),
  courses: () => command<Course[]>('courses'),
  tasks: () => command<Task[]>('tasks'),
  review: () => command<ReviewItem[]>('review'),
  reviewAction: (action: 'approve' | 'reject' | 'resolve', itemId: string) => command<ReviewItem>('review', [action, itemId]),
  reviewDecision: (itemId: string, decision: string) => command<ReviewItem>('review', ['decide', itemId, decision]),
  reviewExecute: (itemId: string) => command<Record<string, unknown>>('review', ['execute', itemId]),
  activity: () => command<ActivityEvent[]>('activity'),
  domain: (entityType?: string) => command<DomainEntity[]>('domain', entityType ? [entityType] : []),
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
  semester: (timezone: string) => command<{ semester: string; timezone: string }>('semester', ['--timezone', timezone]),
}
