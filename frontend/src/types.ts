export type Course = {
  id: string
  code: string
  name: string
  path: string
  inbox_count: number
  material_count: number
  review_required: boolean
}

export type Task = {
  id: string
  title: string
  completed: boolean
  course?: string
  source: string
  source_location?: string | null
  confidence: string
  kind?: string
  due_date?: string | null
}

export type ProcessingRecord = {
  id: string
  source_path: string
  signature: string
  status: string
  detected_at: string
  updated_at: string
  retry_count: number
  lease_until?: string | null
  failure_reason?: string | null
  verification?: Record<string, unknown> | null
  acknowledged_at?: string | null
}

export type LibraryItem = {
  id: string
  name: string
  path: string
  relative_path: string
  semester: string
  course_id?: string | null
  category: 'syllabi' | 'readings' | 'notes' | 'generated' | 'imports' | 'other'
  extension: string
  size: number
  modified_at: string
  provenance?: string | null
  source_type?: string
  artifact_id?: string | null
  artifact_kind?: string | null
  created_by?: string | null
  authoritative?: boolean | null
  source_refs?: Array<Record<string, unknown>>
}

export type FilePreview = {
  id: string
  name: string
  extension: string
  kind: 'text' | 'pdf'
  size: number
  content: string
  truncated: boolean
}

export type WorkspaceSnapshot = {
  academic_root: string
  semester: string
  available_semesters: string[]
  timezone: string
  student: { name: string; institution: string; program?: string }
  courses: Course[]
  tasks: Task[]
  today: { exists: boolean; lines: string[]; path: string }
  material_count: number
  inbox_count: number
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

export type WorkflowRecipe = {
  id: string
  title: string
  summary: string
  why_useful: string
  level: 'recommended' | 'optional' | 'advanced'
  requires: string[]
  optional_capabilities: string[]
  student_choices: string[]
  suggested_defaults: Record<string, unknown>
  setup_steps: Array<{ id: string; instruction: string; student_approval_required: boolean; owner: string }>
  safety_rules: string[]
  verification_steps: string[]
  maintenance: string[]
  academia_interfaces: string[]
  adaptation_notes: string[]
  authority_notes?: Record<string, unknown>
}

export type AgentSetupPlaybook = WorkflowRecipe & {
  kind: 'agent_setup_playbook'
  execution_owner: 'external_agent'
  ownership: Record<'academia_os' | 'playbook' | 'external_agent' | 'student', string>
}

export type WorkflowPreferenceRecord = {
  workflow_id: string
  preferences: Record<string, unknown>
  custom_instructions: string
  external_setup_notes: string
  updated_at: string
  updated_by: string
}

export type WorkflowPreferencesPayload = {
  schema_version: number
  workflows: WorkflowPreferenceRecord[]
}

export type WorkflowShowPayload = {
  workflow_id: string
  recommended_playbook: AgentSetupPlaybook
  /** @deprecated Use recommended_playbook. Kept for compatibility with older agents. */
  recommended_recipe: WorkflowRecipe
  saved_preferences: WorkflowPreferenceRecord | null
  effective_preferences: Record<string, unknown>
  preference_semantics: string
}

export type WorkflowSetPayload = WorkflowShowPayload & { saved: boolean }
export type WorkflowResetPayload = WorkflowShowPayload & { reset: boolean; reset_applied: boolean }

export type PlaybooksPayload = {
  schema_version: number
  kind: 'agent_setup_playbook_registry'
  ownership: Record<'academia_os' | 'playbook' | 'external_agent' | 'student', string>
  playbooks: AgentSetupPlaybook[]
}

export type RecommendationsPayload = {
  schema_version: number
  ownership: Record<'academia' | 'external_agent' | 'student', string>
  workflows: WorkflowRecipe[]
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

export type ExtractionPreview = {
  applied: boolean
  extraction: {
    status: string
    source: { path: string; media_type: string; content_hash: string; extraction_method: string; warnings: string[]; unsupported: string[] }
    candidates: Array<{ kind: string; entity_type: string; entity: Record<string, unknown>; evidence: Record<string, unknown>; confidence: string; reason: string }>
    warnings: string[]
    unsupported: string[]
  }
  reconciliation: { applied: boolean; added_count: number; duplicate_count: number; conflict_count: number; warnings: string[]; reviews: Array<Record<string, unknown>>; actions: Array<Record<string, unknown>> }
}

export type AgentStatus = {
  name: string
  status: string
  message?: string
  configured?: boolean
  detected?: boolean
  dedicated_adapter?: string
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

export type MigrationItem = {
  source: string
  destination: string
  relative_path: string
  semester: string
  size: number
  sha256: string
}

export type MigrationPlanFields = {
  version: number
  source_root: string
  academic_root: string
  current_semester: string
  created_at: string
  item_count: number
  total_size: number
  items: MigrationItem[]
}

export type MigrationPlanResult = MigrationPlanFields & {
  plan_path: string
  review_path: string
  status: 'planned'
  action: 'plan'
}

export type MigrationReport = {
  mode?: 'copy' | 'move'
  selected?: number
  copied?: number
  moved?: number
  skipped?: number
  failed?: number
  destinations?: string[]
  failures?: string[]
  [key: string]: unknown
}

export type MigrationStatusResult = MigrationPlanFields & {
  plan_path: string
  report_path: string
  report: MigrationReport | null
  status: 'ready' | 'report_available'
  action: 'status'
}

export type MigrationExecuteResult = {
  action: 'execute'
  status: 'confirmation_required' | 'completed' | 'completed_with_failures'
  applied: boolean
  mode: 'copy' | 'move'
  selected: number
  selected_indexes: number[]
  copied?: number
  moved?: number
  skipped?: number
  failed?: number
  destinations?: string[]
  failures?: string[]
  plan_path: string
  report_path: string
}
