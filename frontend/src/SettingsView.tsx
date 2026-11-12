import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api, isTauriEnvironment } from './lib/api'
import { AssistantAccountCard } from './AssistantAccountCard'
import { MCPConnectionsCard } from './MCPConnectionsCard'
import type { SettingsPreview, StatusPayload, WorkflowPreferenceRecord, AgentSetupPlaybook } from './types'
import type { Update } from '@tauri-apps/plugin-updater'

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
  const [availableUpdate, setAvailableUpdate] = useState<Update | null>(null)
  const updateRef = useRef<Update | null>(null)
  const [updateBusy, setUpdateBusy] = useState(false)
  const [updateMessage, setUpdateMessage] = useState<string | null>(null)
  const [updateError, setUpdateError] = useState<string | null>(null)
  const [updateProgress, setUpdateProgress] = useState<number | null>(null)

  useEffect(() => () => {
    if (updateRef.current) void updateRef.current.close()
  }, [])

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

  const checkForUpdates = async () => {
    setUpdateBusy(true); setUpdateMessage(null); setUpdateError(null)
    try {
      const { check } = await import('@tauri-apps/plugin-updater')
      const update = await check()
      if (updateRef.current) await updateRef.current.close()
      updateRef.current = update
      setAvailableUpdate(update)
      if (!update) {
        setUpdateProgress(null)
        setUpdateMessage('Academia OS is up to date.')
        return
      }
      setUpdateProgress(null)
      setUpdateMessage(null)
    } catch (reason) {
      setUpdateError(`Update check failed: ${String(reason)}`)
    } finally { setUpdateBusy(false) }
  }

  const installUpdate = async () => {
    if (!availableUpdate) return
    setUpdateBusy(true); setUpdateMessage('Preparing update…'); setUpdateError(null); setUpdateProgress(null)
    try {
      let downloadedBytes = 0
      let contentLength = 0
      await availableUpdate.downloadAndInstall((event) => {
        if (event.event === 'Started') {
          contentLength = event.data.contentLength ?? 0
          setUpdateMessage('Downloading update…')
          setUpdateProgress(contentLength > 0 ? 0 : null)
        } else if (event.event === 'Progress') {
          downloadedBytes += event.data.chunkLength
          if (contentLength > 0) setUpdateProgress(Math.min(100, Math.round((downloadedBytes / contentLength) * 100)))
        } else {
          setUpdateProgress(100)
          setUpdateMessage('Installing update…')
        }
      })
      updateRef.current = null
      setAvailableUpdate(null)
      const { relaunch } = await import('@tauri-apps/plugin-process')
      await relaunch()
    } catch (reason) {
      setUpdateError(`Update could not be installed: ${String(reason)}`)
      setUpdateMessage(null)
    } finally { setUpdateBusy(false) }
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
    <SettingsSection title="ChatGPT sign-in" description="Connect the installed Codex CLI to your ChatGPT plan for Study chat and proposal runs. Academia never reads or stores your credentials.">
      <AssistantAccountCard />
    </SettingsSection>
    <SettingsSection title="External MCP connections" description="Manage local external MCP servers explicitly. Only server-declared read-only tools can be granted, and no connection starts automatically.">
      <MCPConnectionsCard />
    </SettingsSection>
    <SettingsSection title="App updates" description="Check for signed Academia OS updates and install them on this device. Your academic workspace stays in place.">
      {isTauriEnvironment() ? <>
        <p className="settings-note">Installed version {status?.version || 'not available'}</p>
        <div className="settings-actions update-settings-actions">
          <button className="secondary-button" type="button" onClick={() => void checkForUpdates()} disabled={updateBusy}>{updateBusy ? 'Checking…' : 'Check for updates'}</button>
        </div>
        {availableUpdate && <div className="app-update-card" role="status" aria-live="polite">
          <div className="app-update-copy">
            <p className="eyebrow">Update available</p>
            <h4>Academia OS {availableUpdate.version}</h4>
            <p>Current version: {availableUpdate.currentVersion}</p>
            {availableUpdate.date && <small>Released {formatUpdateDate(availableUpdate.date)}</small>}
            {availableUpdate.body?.trim() && <p className="app-update-notes">{availableUpdate.body.trim()}</p>}
          </div>
          <button className="primary-button" type="button" onClick={() => void installUpdate()} disabled={updateBusy}>{updateBusy ? 'Installing…' : `Install ${availableUpdate.version} and restart`}</button>
        </div>}
        {updateProgress !== null && <progress className="app-update-progress" max={100} value={updateProgress} aria-label="Update download progress" />}
        {updateMessage && <p className="settings-success" role="status" aria-live="polite">{updateMessage}{updateProgress !== null ? ` ${updateProgress}%` : ''}</p>}
        {updateError && <p className="setup-error" role="alert">{updateError}</p>}
      </> : <div className="app-update-browser-note">
        <p>This browser dashboard can’t install desktop app updates. Open Academia OS from the installed desktop app to check for and install updates on this device.</p>
        <button className="secondary-button" type="button" disabled>Available in the desktop app</button>
      </div>}
    </SettingsSection>
    <EnhanceSetup playbooks={playbooks} savedPreferences={savedPreferences} onSaved={(record) => setSavedPreferences((current) => ({ ...current, [record.workflow_id]: record }))} onReset={(workflowId) => setSavedPreferences((current) => { const next = { ...current }; delete next[workflowId]; return next })} />
    <details className="advanced-card"><summary><span className="eyebrow">Advanced</span><strong>Technical details</strong></summary><p>Most users do not need these controls.</p><div className="advanced-grid"><Info label="Profile path" value={status?.profile || 'Unavailable'} /><Info label="Runtime path" value={stringAt(config, ['runtime', 'install_directory']) || 'Unavailable'} /><Info label="CLI version" value={status?.version || 'Unavailable'} /></div></details>
  </div>
}

function EnhanceSetup({ playbooks, savedPreferences, onSaved, onReset }: { playbooks: AgentSetupPlaybook[]; savedPreferences: SavedPreferences; onSaved: (record: WorkflowPreferenceRecord) => void; onReset: (workflowId: string) => void }) {
  const [selectedPlaybook, setSelectedPlaybook] = useState<AgentSetupPlaybook | null>(null)
  const selectedSaved = selectedPlaybook ? savedPreferences[selectedPlaybook.id] || null : null

  return <>
    <section className="agent-playbooks">
      <div className="agent-playbooks-heading"><div><p className="eyebrow">Agent setup playbooks</p><h3>Use an authorized agent when you’re ready</h3><p>Academia OS provides portable playbooks for useful academic workflows. Your authorized agent chooses the tools and owns the external implementation; Academia OS does not connect accounts or run these automations.</p></div><span className="setup-boundary-note">Student authorization stays required</span></div>
      {playbooks.length ? <div className="workflow-card-grid">{playbooks.map((playbook) => <WorkflowCard key={playbook.id} workflow={playbook} saved={savedPreferences[playbook.id] || null} onSaved={onSaved} onReset={onReset} onOpen={() => setSelectedPlaybook(playbook)} />)}</div> : <p className="muted-copy">Loading Agent Setup Playbooks…</p>}
    </section>
    {selectedPlaybook && <PlaybookPanel workflow={selectedPlaybook} saved={selectedSaved} onSaved={onSaved} onReset={onReset} onClose={() => setSelectedPlaybook(null)} />}
  </>
}

function WorkflowCard({ workflow, onOpen }: WorkflowCardProps & { onOpen: () => void }) {
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'error'>('idle')
  const agentPrompt = buildAgentPrompt(workflow)

  const copyPrompt = async () => {
    try {
      await copyText(agentPrompt)
      setCopyState('copied')
    } catch {
      setCopyState('error')
    }
  }

  return <article className="workflow-card">
    <button className="workflow-card-open" type="button" aria-haspopup="dialog" aria-label={`Open ${workflow.title} playbook`} onClick={onOpen}>
      <span className="workflow-card-open-copy"><span className={`workflow-level ${workflow.level}`}>{workflow.level}</span><strong>{workflow.title}</strong><small>{workflow.summary}</small></span><span className="workflow-card-open-link">View playbook <span aria-hidden="true">→</span></span>
    </button>
    <div className="workflow-card-meta"><span>Needs</span><strong>{workflow.requires.map(capabilityLabel).join(' · ')}</strong></div>
    <div className="workflow-prompt"><div className="workflow-prompt-heading"><span>Ask your AI agent</span><button className="quiet-button workflow-copy-button" type="button" onClick={() => void copyPrompt()}>{copyState === 'copied' ? 'Copied' : copyState === 'error' ? 'Copy unavailable' : 'Copy prompt'}</button></div><code>{agentPrompt}</code></div>
  </article>
}

function PlaybookPanel({ workflow, saved, onSaved, onReset, onClose }: WorkflowCardProps & { onClose: () => void }) {
  const [values, setValues] = useState<Record<string, unknown>>(() => mergePreferences(workflow, saved))
  const [customInstructions, setCustomInstructions] = useState(saved?.custom_instructions || '')
  const [externalSetupNotes, setExternalSetupNotes] = useState(saved?.external_setup_notes || '')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const titleId = `playbook-panel-title-${workflow.id}`

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setValues(mergePreferences(workflow, saved))
    setCustomInstructions(saved?.custom_instructions || '')
    setExternalSetupNotes(saved?.external_setup_notes || '')
  }, [workflow, saved])

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

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
      setError('Preferences were not reset: ' + String(reason))
    } finally { setBusy(false) }
  }


  return <div className="playbook-panel-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <section className="playbook-panel" role="dialog" tabIndex={-1} aria-modal="true" aria-labelledby={titleId}>
      <header className="playbook-panel-header"><div><p className="eyebrow">Agent Setup Playbook</p><h2 id={titleId}>{workflow.title}</h2><p>{workflow.summary}</p></div><button className="icon-button" type="button" aria-label="Close playbook panel" onClick={onClose}>×</button></header>
      <div className="playbook-panel-body">
        <section className="playbook-guide"><p className="eyebrow">Playbook guide</p><h5>Why it is useful</h5><p>{workflow.why_useful}</p><PlaybookList title="Suggested defaults" items={Object.entries(workflow.suggested_defaults).map(([key, value]) => `${labelFromKey(key)}: ${formatPreferenceValue(value)}`)} /><PlaybookList title="Agent implementation steps" items={workflow.setup_steps.map((step) => `${step.instruction}${step.student_approval_required ? ' (student approval required)' : ''}`)} /><PlaybookList title="Student choices" items={workflow.student_choices} /><PlaybookList title="Safety contract" items={workflow.safety_rules} /><PlaybookList title="Verification" items={workflow.verification_steps} /></section>
        <section className="playbook-preferences"><p className="eyebrow">My playbook preferences</p><h5>Saved locally for your agent</h5><p className="workflow-helper">Start from the playbook defaults, then save only the choices you want your authorized AI agent to use. Saving here does not create an external connection or automation.</p><div className="workflow-preference-fields">{Object.entries(workflow.suggested_defaults).map(([key, defaultValue]) => <PreferenceField key={key} name={key} defaultValue={defaultValue} value={values[key]} onChange={(value) => setValues((current) => ({ ...current, [key]: value }))} />)}</div><label className="workflow-text-field"><span>Custom instructions</span><textarea value={customInstructions} onChange={(event) => setCustomInstructions(event.target.value)} placeholder="Tell your agent how you want this playbook to behave." /></label><label className="workflow-text-field"><span>Optional notes for the implementing agent</span><textarea value={externalSetupNotes} onChange={(event) => setExternalSetupNotes(event.target.value)} placeholder="Maintenance notes for the agent; do not enter credentials or secrets." /></label><div className="workflow-save-row"><button className="primary-button" type="button" onClick={() => void save()} disabled={busy}>{busy ? 'Saving…' : 'Save my playbook preferences'}</button>{message && <span className="workflow-save-message" role="status">{message}</span>}{error && <span className="workflow-save-error" role="alert">{error}</span>}</div><div className="workflow-reset-row"><button className="secondary-button" type="button" onClick={() => void reset()} disabled={busy}>Reset to recommended defaults</button><small>Only resets Academia’s local preference record. It does not change external services, calendars, email, or automations.</small></div></section>
      </div>
    </section>
  </div>
}

function buildAgentPrompt(workflow: AgentSetupPlaybook): string { return `Use the “${workflow.title}” Agent Setup Playbook with my saved Academia preferences. Check your own tools, ask for any required authorization, and report exactly what you can configure.` }
async function copyText(value: string): Promise<void> { if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') { await navigator.clipboard.writeText(value); return } const textarea = document.createElement('textarea'); textarea.value = value; textarea.setAttribute('readonly', ''); textarea.style.position = 'fixed'; textarea.style.opacity = '0'; document.body.appendChild(textarea); textarea.select(); const copied = document.execCommand('copy'); textarea.remove(); if (!copied) throw new Error('Clipboard access is unavailable.') }
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

function formatUpdateDate(value: string): string { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) }
