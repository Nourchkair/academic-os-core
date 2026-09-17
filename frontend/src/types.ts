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

export type SettingsPreview = {
  applied: boolean
  requires_approval: boolean
  changes: Array<{ key: string; before: unknown; after: unknown; structural: boolean }>
}

export type DomainEntity = {
  entity_type: string
  id: string
  course_id: string
  title: string
  evidence: {
    source: string
    source_path: string
    source_location?: string | null
    provenance: string
    confidence: string
    authority: string
    verification_result?: string | null
    last_verified_at?: string | null
  }
  [key: string]: unknown
}

export type WorkspaceCandidate = {
  path: string
  score: number
  reasons: string[]
  label: string
}

export type WorkspaceInspection = {
  path: string
  read_only: boolean
  recognized: boolean
  markers: Record<string, boolean>
  semesters: Array<{
    name: string
    path: string
    course_count: number
    courses: Array<{
      name: string
      path: string
      course_code: string
      directories: string[]
      missing_directories: string[]
      complete_structure: boolean
      file_count: number
    }>
  }>
  semester_count: number
  course_count: number
  file_count: number
  operational_state_present: boolean
  suggested_semester: string
  anomalies: Array<{ severity: string; path: string; message: string }>
}

export type AttachmentResult = {
  applied: boolean
  requires_confirmation: boolean
  profile_path: string
  profile_state: string
  backup_profile?: string | null
  academic_files_changed: boolean
  operational_state_created: boolean
  inspection: WorkspaceInspection
  candidate: Record<string, unknown>
}

export type WorkspaceCreationResult = {
  applied: boolean
  requires_confirmation: boolean
  academic_root: string
  profile_path: string
  academic_files_changed: boolean
  candidate: Record<string, unknown>
  status?: string
  semester_root?: string
  install_root?: string
}

export type ImportResult = {
  source_type: string
  original_file: string
  acquired_at: string
  destination: string
  state_path: string
  review_item_id?: string
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
