export type Course = {
  id: string
  code: string
  name: string
  path: string
  inbox_count: number
  review_required: boolean
}

export type Task = {
  id: string
  title: string
  completed: boolean
  course?: string
  source: string
  confidence: string
}

export type WorkspaceSnapshot = {
  academic_root: string
  semester: string
  timezone: string
  student: { name: string; institution: string; program?: string }
  courses: Course[]
  tasks: Task[]
  today: { exists: boolean; lines: string[]; path: string }
  review_count: number
  workspace_exists: boolean
}

export type ReviewItem = {
  id: string
  kind: string
  title: string
  course?: string
  details: Record<string, unknown>
  status: string
  priority: string
  created_at: string
  updated_at: string
  action_proposal_id?: string
}

export type ActivityEvent = {
  id: string
  event_type: string
  title: string
  course?: string
  details: Record<string, unknown>
  source?: string
  confidence?: string
  actor: string
  created_at: string
}

export type AgentStatus = {
  name: string
  status: string
  message?: string
  configured?: boolean
  detected?: boolean
}

export type StatusPayload = {
  version: string
  profile: string
  student: WorkspaceSnapshot['student']
  workspace: WorkspaceSnapshot
  review_count: number
  recent_activity: ActivityEvent[]
  agents: Record<string, AgentStatus>
  acquisition: { watched_folders: string[]; browser: { enabled: boolean; allowed_sites: string[] } }
}
