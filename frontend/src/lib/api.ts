import { invoke } from '@tauri-apps/api/core'
import type { ActivityEvent, Course, ReviewItem, StatusPayload, Task, WorkspaceSnapshot } from '../types'

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
  activity: () => command<ActivityEvent[]>('activity'),
  workspace: () => command<WorkspaceSnapshot>('workspace'),
  settings: () => command<Record<string, unknown>>('settings', ['show']),
}
