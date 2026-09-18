import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api } from './lib/api'
import type { SettingsPreview, StatusPayload, WorkflowPreferenceRecord, AgentSetupPlaybook } from './types'

type SettingsViewProps = { status: StatusPayload | null; onSaved: () => Promise<void> }
type Draft = {
  name: string
  institution: string
  program: string
  timezone: string
  root: string
  semester: string
}
type ObjectValue = Record<string, unknown>
type SavedPreferences = Record<string, WorkflowPreferenceRecord>

type WorkflowCardProps = {
  workflow: AgentSetupPlaybook
  saved: WorkflowPreferenceRecord | null
  onSaved: (record: WorkflowPreferenceRecord) => void
  onReset: (workflowId: string) => void
}

export function SettingsView({ status, onSaved }: SettingsViewProps) {
  const [config, setConfig] = useState<ObjectValue | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [preview, setPreview] = useState<SettingsPreview | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [playbooks, setPlaybooks] = useState<AgentSetupPlaybook[]>([])
  const [savedPreferences, setSavedPreferences] = useState<SavedPreferences>({})

  const loadSettings = useCallback(async () => {
    try {
      const value = await api.settings()
      setConfig(value)
      setDraft(toDraft(value, status))
    } catch (reason) {
      setError(`Settings could not be loaded: ${String(reason)}`)
    }
  }, [status])

  const loadPlaybooks = useCallback(async () => {
    try {
      const value = await api.playbooks()
      setPlaybooks(value.playbooks)
    } catch (reason) {
      setError(`Agent Setup Playbooks could not be loaded: ${String(reason)}`)
    }
  }, [])

  const loadWorkflowPreferences = useCallback(async () => {
    try {
      const value = await api.workflowPreferences()
      const next: SavedPreferences = {}
      for (const record of value.workflows) next[record.workflow_id] = record
      setSavedPreferences(next)
    } catch (reason) {
      setError(`Workflow preferences could not be loaded: ${String(reason)}`)
    }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadSettings()
  }, [loadSettings])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadPlaybooks()
  }, [loadPlaybooks])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadWorkflowPreferences()
  }, [loadWorkflowPreferences])

  const update = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft((current) => current ? { ...current, [key]: value } : current)
  const updates = useMemo(() => draft ? toUpdates(draft) : {}, [draft])
  const structuralPreview = Boolean(preview?.requires_approval)

  const previewChanges = async () => {
    try {
      setBusy(true); setError(null); setMessage(null)
      setPreview(await api.settingsUpdate(updates, false, false))
    } catch (reason) {
      setError(`Settings could not be previewed: ${String(reason)}`)
    } finally { setBusy(false) }
  }

  const applyChanges = async () => {
    if (!preview) return
    try {
      setBusy(true); setError(null); setMessage(null)
      await api.settingsUpdate(updates, true, structuralPreview)
      setMessage('Settings saved locally.')
      setPreview(null)
      await loadSettings()
      await onSaved()
    } catch (reason) {
      setError(`Settings were not changed: ${String(reason)}`)
    } finally { setBusy(false) }
  }

  return <div className="page-stack settings-page">
    <PageIntro eyebrow="Control" title="Settings" subtitle="Update the local profile and workspace that Academia OS reads. Importing files and migrating older material are available from the + button in the top-right corner." />
    {error && <p className="setup-error" role="alert">{error}</p>}
    {message && <p className="settings-success" role="status">{message}</p>}
    {draft ? <>
      <div className="settings-layout">
        <SettingsSection title="Profile" description="Personal details used only to label this local workspace.">
          <div className="settings-grid">
            <Field label="Name" value={draft.name} onChange={(value) => update('name', value)} />
            <Field label="Institution" value={draft.institution} onChange={(value) => update('institution', value)} />
            <Field label="Program or faculty" value={draft.program} onChange={(value) => update('program', value)} />
            <Field label="Time zone" value={draft.timezone} onChange={(value) => update('timezone', value)} />
          </div>
        </SettingsSection>
        <SettingsSection title="Workspace" description="Choose the local academic folder and semester this dashboard reads. Changing these values is previewed before anything is written.">
          <div className="settings-grid">
            <Field label="Academic root" value={draft.root} onChange={(value) => update('root', value)} />
            <Field label="Active semester" value={draft.semester} onChange={(value) => update('semester', value)} />
          </div>
          <p className="settings-note">Current workspace: {status?.workspace.academic_root || 'not connected'} · {status?.workspace.workspace_exists ? 'healthy enough to read' : 'not found'}</p>
        </SettingsSection>
      </div>
      <section className="settings-actions"><button className="secondary-button" onClick={() => void previewChanges()} disabled={busy}>{busy ? 'Preparing…' : 'Preview changes'}</button>{preview && <button className="primary-button" onClick={() => void applyChanges()} disabled={busy}>{structuralPreview ? 'Approve and apply structural changes' : 'Apply settings'}</button>}</section>
      {preview && <SettingsPreviewCard preview={preview} />}
    </> : <div className="loading-card">Loading your local settings…</div>}
    <EnhanceSetup playbooks={playbooks} savedPreferences={savedPreferences} onSaved={(record) => setSavedPreferences((current) => ({ ...current, [record.workflow_id]: record }))} onReset={(workflowId) => setSavedPreferences((current) => { const next = { ...current }; delete next[workflowId]; return next })} />
    <details className="advanced-card"><summary><span className="eyebrow">Advanced</span><strong>Technical details</strong></summary><p>Most users do not need these controls.</p><div className="advanced-grid"><Info label="Profile path" value={status?.profile || 'Unavailable'} /><Info label="Runtime path" value={stringAt(config, ['runtime', 'install_directory']) || 'Unavailable'} /><Info label="CLI version" value={status?.version || 'Unavailable'} /></div></details>
  </div>
}

function EnhanceSetup({ playbooks, savedPreferences, onSaved, onReset }: { playbooks: AgentSetupPlaybook[]; savedPreferences: SavedPreferences; onSaved: (record: WorkflowPreferenceRecord) => void; onReset: (workflowId: string) => void }) {
  return <section className="agent-playbooks">
    <div className="agent-playbooks-heading"><div><p className="eyebrow">Agent setup playbooks</p><h3>Use an authorized agent when you’re ready</h3><p>Academia OS provides portable playbooks for useful academic workflows. Your authorized agent chooses the tools and owns the external implementation; Academia OS does not connect accounts or run these automations.</p></div><span className="setup-boundary-note">Student authorization stays required</span></div>
    {playbooks.length ? <div className="workflow-card-grid">{playbooks.map((playbook) => <WorkflowCard key={playbook.id} workflow={playbook} saved={savedPreferences[playbook.id] || null} onSaved={onSaved} onReset={onReset} />)}</div> : <p className="muted-copy">Loading Agent Setup Playbooks…</p>}
  </section>
}

function WorkflowCard({ workflow, saved, onSaved, onReset }: WorkflowCardProps) {
  const [open, setOpen] = useState(false)
  const [values, setValues] = useState<Record<string, unknown>>(() => mergePreferences(workflow, saved))
  const [customInstructions, setCustomInstructions] = useState(saved?.custom_instructions || '')
  const [externalSetupNotes, setExternalSetupNotes] = useState(saved?.external_setup_notes || '')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setValues(mergePreferences(workflow, saved))
    setCustomInstructions(saved?.custom_instructions || '')
    setExternalSetupNotes(saved?.external_setup_notes || '')
  }, [workflow, saved])

  const save = async () => {
    try {
      setBusy(true); setError(null); setMessage(null)
      const result = await api.workflowSet(workflow.id, preferenceOverrides(workflow.suggested_defaults, values), customInstructions, externalSetupNotes, 'user', true)
      onSaved(result.saved_preferences as WorkflowPreferenceRecord)
      setMessage('Saved locally. This does not configure an external service.')
    } catch (reason) {
      setError(`This setup was not saved: ${String(reason)}`)
    } finally { setBusy(false) }
  }

  const reset = async () => {
    try {
      setBusy(true); setError(null); setMessage(null)
      const result = await api.workflowReset(workflow.id)
      setValues({ ...workflow.suggested_defaults })
      setCustomInstructions('')
      setExternalSetupNotes('')
      setMessage(result.reset_applied ? 'Reset locally to the recommended defaults. No external service was changed.' : 'Already using the recommended defaults. Only Academia’s local preference record was checked.')
      onReset(workflow.id)
    } catch (reason) {
      setError(`Preferences were not reset: ${String(reason)}`)
    } finally { setBusy(false) }
  }

  return <article className={`workflow-card ${open ? 'is-open' : ''}`}>
    <button className="workflow-card-toggle" type="button" aria-expanded={open} onClick={() => setOpen((current) => !current)}>
      <span className="workflow-card-toggle-copy"><span className={`workflow-level ${workflow.level}`}>{workflow.level}</span><strong>{workflow.title}</strong><small>{workflow.summary}</small></span><span className="workflow-card-chevron" aria-hidden="true">{open ? '−' : '+'}</span>
    </button>
    <div className="workflow-card-meta"><span>Needs</span><strong>{workflow.requires.map(capabilityLabel).join(' · ')}</strong></div>
    <div className="workflow-prompt"><span>Ask your AI agent</span><code>Use the “{workflow.title}” Agent Setup Playbook with my saved Academia preferences. Check your own tools, ask for any required authorization, and report exactly what you can configure.</code></div>
    {open && <div className="workflow-editor">
      <section className="playbook-guide"><p className="eyebrow">Playbook guide</p><h5>Why it is useful</h5><p>{workflow.why_useful}</p><PlaybookList title="Suggested defaults" items={Object.entries(workflow.suggested_defaults).map(([key, value]) => `${labelFromKey(key)}: ${formatPreferenceValue(value)}`)} /><PlaybookList title="Agent implementation steps" items={workflow.setup_steps.map((step) => `${step.instruction}${step.student_approval_required ? ' (student approval required)' : ''}`)} /><PlaybookList title="Student choices" items={workflow.student_choices} /><PlaybookList title="Safety contract" items={workflow.safety_rules} /><PlaybookList title="Verification" items={workflow.verification_steps} /></section>
      <section className="playbook-preferences"><p className="eyebrow">My playbook preferences</p><h5>Saved locally for your agent</h5><p className="workflow-helper">Start from the playbook defaults, then save only the choices you want your authorized AI agent to use. Saving here does not create an external connection or automation.</p><div className="workflow-preference-fields">{Object.entries(workflow.suggested_defaults).map(([key, defaultValue]) => <PreferenceField key={key} name={key} defaultValue={defaultValue} value={values[key]} onChange={(value) => setValues((current) => ({ ...current, [key]: value }))} />)}</div><label className="workflow-text-field"><span>Custom instructions</span><textarea value={customInstructions} onChange={(event) => setCustomInstructions(event.target.value)} placeholder="Tell your agent how you want this playbook to behave." /></label><label className="workflow-text-field"><span>Optional notes for the implementing agent</span><textarea value={externalSetupNotes} onChange={(event) => setExternalSetupNotes(event.target.value)} placeholder="Maintenance notes for the agent; do not enter credentials or secrets." /></label><div className="workflow-save-row"><button className="primary-button" type="button" onClick={() => void save()} disabled={busy}>{busy ? 'Saving…' : 'Save my playbook preferences'}</button>{message && <span className="workflow-save-message" role="status">{message}</span>}{error && <span className="workflow-save-error" role="alert">{error}</span>}</div><div className="workflow-reset-row"><button className="secondary-button" type="button" onClick={() => void reset()} disabled={busy}>Reset to recommended defaults</button><small>Only resets Academia’s local preference record. It does not change external services, calendars, email, or automations.</small></div></section>
    </div>}
  </article>
}

function PreferenceField({ name, defaultValue, value, onChange }: { name: string; defaultValue: unknown; value: unknown; onChange: (value: unknown) => void }) {
  if (typeof defaultValue === 'boolean') return <label className="workflow-checkbox"><input type="checkbox" checked={Boolean(value)} onChange={(event) => onChange(event.target.checked)} /><span>{labelFromKey(name)}</span></label>
  if (Array.isArray(defaultValue)) return <label className="workflow-text-field"><span>{labelFromKey(name)}</span><textarea value={Array.isArray(value) ? value.map(String).join('\n') : ''} onChange={(event) => onChange(event.target.value.split('\n').map((item) => item.trim()).filter(Boolean))} /><small>One value per line.</small></label>
  if (typeof defaultValue === 'number') return <label className="workflow-text-field"><span>{labelFromKey(name)}</span><input type="number" value={typeof value === 'number' ? value : defaultValue} onChange={(event) => onChange(Number(event.target.value))} /></label>
  return <label className="workflow-text-field"><span>{labelFromKey(name)}</span><input type={name === 'time' ? 'time' : 'text'} value={typeof value === 'string' ? value : ''} onChange={(event) => onChange(event.target.value)} /></label>
}

function PlaybookList({ title, items }: { title: string; items: string[] }) { return <div className="playbook-list"><h6>{title}</h6><ul>{items.map((item, index) => <li key={`${title}-${index}`}>{item}</li>)}</ul></div> }
function capabilityLabel(value: string): string { return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase()) }
function labelFromKey(value: string): string { return capabilityLabel(value) }
function mergePreferences(workflow: AgentSetupPlaybook, saved: WorkflowPreferenceRecord | null): Record<string, unknown> { return { ...workflow.suggested_defaults, ...(saved?.preferences || {}) } }
function preferenceOverrides(defaults: Record<string, unknown>, values: Record<string, unknown>): Record<string, unknown> { return Object.fromEntries(Object.entries(values).filter(([key, value]) => JSON.stringify(value) !== JSON.stringify(defaults[key]))) }
function formatPreferenceValue(value: unknown): string { if (Array.isArray(value)) return value.map(String).join(', '); if (value === null || value === undefined || value === '') return 'Not specified'; return String(value) }
function SettingsPreviewCard({ preview }: { preview: SettingsPreview }) { return <section className="settings-preview"><p className="eyebrow">Review before saving</p><h3>{preview.changes.length} change{preview.changes.length === 1 ? '' : 's'} found</h3>{preview.changes.map((change) => <div className="settings-change" key={change.key}><div><strong>{change.key}</strong>{change.structural && <span className="structural-badge">Structural</span>}</div><span>{format(change.before)} → {format(change.after)}</span><small>{change.structural ? 'May affect workspace paths or projections; explicit approval is required.' : 'Local profile setting only.'}</small></div>)}{preview.changes.length === 0 && <p className="muted-copy">No settings would change.</p>}</section> }
function SettingsSection({ title, description, children }: { title: string; description: string; children: ReactNode }) { return <section className="settings-section"><div><p className="eyebrow">Local settings</p><h3>{title}</h3><p>{description}</p></div><div className="settings-section-content">{children}</div></section> }
function Field({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) { return <label className="setup-field"><span>{label}</span><input value={value} onChange={(event) => onChange(event.target.value)} /></label> }
function Info({ label, value }: { label: string; value: string }) { return <div className="info-field"><span>{label}</span><strong>{value}</strong></div> }
function PageIntro({ eyebrow, title, subtitle }: { eyebrow: string; title: string; subtitle: string }) { return <section className="page-intro"><p className="eyebrow">{eyebrow}</p><h2>{title}</h2><p>{subtitle}</p></section> }
function toDraft(config: ObjectValue, status: StatusPayload | null): Draft { return { name: stringAt(config, ['student', 'name']), institution: stringAt(config, ['student', 'institution']), program: stringAt(config, ['student', 'program']), timezone: stringAt(config, ['academic', 'timezone']) || 'UTC', root: stringAt(config, ['academic', 'root_directory']) || status?.workspace.academic_root || '', semester: stringAt(config, ['academic', 'semester']) || status?.workspace.semester || '' } }
function toUpdates(draft: Draft): Record<string, unknown> { return { 'student.name': draft.name, 'student.institution': draft.institution, 'student.program': draft.program, 'academic.timezone': draft.timezone, 'academic.root_directory': draft.root, 'academic.semester': draft.semester } }
function valueAt(config: ObjectValue, path: string[]): unknown { let current: unknown = config; for (const part of path) { if (!current || typeof current !== 'object') return undefined; current = (current as ObjectValue)[part] } return current }
function stringAt(config: ObjectValue | null, path: string[]): string { const value = config ? valueAt(config, path) : undefined; return typeof value === 'string' ? value : '' }
function format(value: unknown): string { if (value === undefined || value === null || value === '') return 'Unknown'; return typeof value === 'object' ? JSON.stringify(value) : String(value) }
