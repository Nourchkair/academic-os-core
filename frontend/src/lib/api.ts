import { invoke } from '@tauri-apps/api/core'
import type { ActivityEvent, AttachmentResult, Course, DomainEntity, ImportResult, ReviewItem, SettingsPreview, StatusPayload, Task, WorkspaceCandidate, WorkspaceCreationResult, WorkspaceInspection, WorkspaceSnapshot } from '../types'

export class BridgeUnavailableError extends Error {
  constructor() {
    super('The Academia OS desktop bridge is unavailable. Launch the packaged app or configure a local interface bridge.')
    this.name = 'BridgeUnavailableError'
  }
}

async function command<T>(name: string, args: string[] = []): Promise<T> {
  if (typeof window === 'undefined' || !(window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__) {
    throw new BridgeUnavailableError()
  }
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

export const api = {
  status: () => command<StatusPayload>('status'),
  courses: () => command<Course[]>('courses'),
  tasks: () => command<Task[]>('tasks'),
  review: () => command<ReviewItem[]>('review'),
  reviewAction: (action: 'approve' | 'reject' | 'resolve', itemId: string) => command<ReviewItem>('review', [action, itemId]),
  reviewDecision: (itemId: string, decision: string) => command<ReviewItem>('review', ['decide', itemId, decision]),
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
  settings: () => command<Record<string, unknown>>('settings', ['show']),
  settingsUpdate: (updates: Record<string, unknown>, apply: boolean, approveStructural: boolean) => {
    const args = ['update']
    for (const [key, value] of Object.entries(updates)) args.push('--set', `${key}=${JSON.stringify(value)}`)
    if (apply) args.push('--apply')
    if (approveStructural) args.push('--approve-structural')
    return command<SettingsPreview>('settings', args)
  },
  capabilities: () => command<Record<string, unknown>>('capabilities'),
}
