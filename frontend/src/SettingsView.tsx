import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api } from './lib/api'
import type { SettingsPreview, StatusPayload } from './types'

type SettingsViewProps = { status: StatusPayload | null; onSaved: () => Promise<void> }
type Draft = {
  name: string
  institution: string
  program: string
  timezone: string
  root: string
  semester: string
  manualImport: boolean
  watchedFolders: string
  browserEnabled: boolean
  allowedSites: string
}

type ObjectValue = Record<string, unknown>

export function SettingsView({ status, onSaved }: SettingsViewProps) {
  const [config, setConfig] = useState<ObjectValue | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [preview, setPreview] = useState<SettingsPreview | null>(null)
  const [capabilities, setCapabilities] = useState<Record<string, unknown> | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const loadSettings = useCallback(async () => {
    try {
      const value = await api.settings()
      setConfig(value)
      setDraft(toDraft(value, status))
    } catch (reason) {
      setError(`Settings could not be loaded: ${String(reason)}`)
    }
  }, [status])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadSettings()
    void api.capabilities().then(setCapabilities).catch(() => setCapabilities(null))
  }, [loadSettings])

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

  const hermesStatus = status?.agents.hermes?.dedicated_adapter === 'available' ? 'Optional adapter detected' : 'No dedicated adapter needed'

  return <div className="page-stack"><PageIntro eyebrow="Control" title="Settings" subtitle="Academia OS manages local workspace policy. Your AI assistant, browser session, and scheduler remain yours to choose and authorize." />
    {error && <p className="setup-error" role="alert">{error}</p>}
    {message && <p className="settings-success" role="status">{message}</p>}
    {draft ? <>
      <SettingsSection title="Profile" description="These details personalize the local profile; they are not sent anywhere."><div className="settings-grid"><Field label="Name" value={draft.name} onChange={(value) => update('name', value)} /><Field label="Institution" value={draft.institution} onChange={(value) => update('institution', value)} /><Field label="Program or faculty" value={draft.program} onChange={(value) => update('program', value)} /><Field label="Time zone" value={draft.timezone} onChange={(value) => update('timezone', value)} /></div></SettingsSection>
      <SettingsSection title="Workspace" description="Changing the root or semester is structural. Academia OS will not move files as part of this settings change."><div className="settings-grid"><Field label="Academic root" value={draft.root} onChange={(value) => update('root', value)} /><Field label="Active semester" value={draft.semester} onChange={(value) => update('semester', value)} /></div><p className="settings-note">Current workspace: {status?.workspace.academic_root || 'not connected'} · {status?.workspace.workspace_exists ? 'healthy enough to read' : 'not found'}</p></SettingsSection>
      <SettingsSection title="Sources & imports" description="Manual import is the safest default. Watched folders are one-shot scans when you ask for them; Academia OS does not claim persistent monitoring."><label className="check-row"><input type="checkbox" checked={draft.manualImport} onChange={(event) => update('manualImport', event.target.checked)} /><span><strong>Allow manual imports</strong><small>Copy selected files into a visible 00_INBOX destination.</small></span></label><label className="setup-field"><span>Watched folders, one per line</span><textarea value={draft.watchedFolders} onChange={(event) => update('watchedFolders', event.target.value)} placeholder="~/Downloads" /></label></SettingsSection>
      <SettingsSection title="Agent access (optional)" description="There is no built-in AI to connect. Any agent you choose owns its model, credentials, local tool permissions, browser session, and schedule."><div className="policy-card"><strong>Use the local interface when you choose an agent</strong><p>Codex, Hermes, Claude, ChatGPT/Work, or another authorized tool can use the neutral <code>academia --json</code> interface. Academia OS does not need to know which model you use.</p></div><AgentSetting name="Local Academia CLI/API" status="Available without an agent connection" /><AgentSetting name="Hermes" status={hermesStatus} /><AgentSetting name="Codex / Claude / ChatGPT/Work" status="Generic-compatible; no dedicated connection required" /></SettingsSection>
      <SettingsSection title="External access guard" description="This is not a browser launcher or an AI connection. It is an off-by-default safety policy that optional adapters must obey before requesting read-only school-site access."><label className="check-row"><input type="checkbox" checked={draft.browserEnabled} onChange={(event) => update('browserEnabled', event.target.checked)} /><span><strong>Allow an optional browser adapter to request read-only access</strong><small>Keep this off unless you intentionally configure an adapter. Passwords, MFA codes, cookies, and hidden session tokens are never handled.</small></span></label><label className="setup-field"><span>Allowed sites</span><input value={draft.allowedSites} onChange={(event) => update('allowedSites', event.target.value)} placeholder="brightspace.example.edu, library.example.edu" /></label><p className="settings-note">The agent still needs separate operating-system permission and user-controlled authentication. This core guard prevents an adapter from treating access as implicit.</p></SettingsSection>
      <SettingsSection title="Automation ownership" description="Academia OS does not run a background daemon. Recurring work belongs to the agent or scheduler you explicitly choose."><div className="policy-card"><strong>No schedule is being enabled here</strong><p>Daily briefs, inbox processing, and recurring prompts are executed by an external agent or scheduler when you configure one. The core only exposes safe commands and records the resulting activity.</p></div><AgentSetting name="Academia OS core" status="No background daemon" /><AgentSetting name="External agent / scheduler" status="Owns timing, credentials, and execution" /></SettingsSection>
      <section className="settings-actions"><button className="secondary-button" onClick={() => void previewChanges()} disabled={busy}>{busy ? 'Preparing…' : 'Preview changes'}</button>{preview && <button className="primary-button" onClick={() => void applyChanges()} disabled={busy}>{structuralPreview ? 'Approve and apply structural changes' : 'Apply settings'}</button>}</section>
      {preview && <SettingsPreviewCard preview={preview} />}
    </> : <div className="loading-card">Loading your local settings…</div>}
    <details className="advanced-card"><summary><span className="eyebrow">Advanced</span><strong>Technical details</strong></summary><p>Most users do not need these controls.</p><div className="advanced-grid"><Info label="Profile path" value={status?.profile || 'Unavailable'} /><Info label="Runtime path" value={stringAt(config, ['runtime', 'install_directory']) || 'Unavailable'} /><Info label="CLI version" value={status?.version || 'Unavailable'} /></div>{capabilities && <pre>{JSON.stringify(capabilities, null, 2)}</pre>}</details>
  </div>
}

function SettingsPreviewCard({ preview }: { preview: SettingsPreview }) { return <section className="settings-preview"><p className="eyebrow">Review before saving</p><h3>{preview.changes.length} change{preview.changes.length === 1 ? '' : 's'} found</h3>{preview.changes.map((change) => <div className="settings-change" key={change.key}><div><strong>{change.key}</strong>{change.structural && <span className="structural-badge">Structural</span>}</div><span>{format(change.before)} → {format(change.after)}</span><small>{change.structural ? 'May affect workspace paths or projections; explicit approval is required.' : 'Local profile setting only.'}</small></div>)}{preview.changes.length === 0 && <p className="muted-copy">No settings would change.</p>}</section> }
function SettingsSection({ title, description, children }: { title: string; description: string; children: ReactNode }) { return <section className="settings-section"><div><p className="eyebrow">Settings</p><h3>{title}</h3><p>{description}</p></div>{children}</section> }
function AgentSetting({ name, status }: { name: string; status: string }) { return <div className="agent-setting"><strong>{name}</strong><span>{status}</span></div> }
function Field({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) { return <label className="setup-field"><span>{label}</span><input value={value} onChange={(event) => onChange(event.target.value)} /></label> }
function Info({ label, value }: { label: string; value: string }) { return <div className="info-field"><span>{label}</span><strong>{value}</strong></div> }
function PageIntro({ eyebrow, title, subtitle }: { eyebrow: string; title: string; subtitle: string }) { return <section className="page-intro"><p className="eyebrow">{eyebrow}</p><h2>{title}</h2><p>{subtitle}</p></section> }
function toDraft(config: ObjectValue, status: StatusPayload | null): Draft { return { name: stringAt(config, ['student', 'name']), institution: stringAt(config, ['student', 'institution']), program: stringAt(config, ['student', 'program']), timezone: stringAt(config, ['academic', 'timezone']) || 'UTC', root: stringAt(config, ['academic', 'root_directory']) || status?.workspace.academic_root || '', semester: stringAt(config, ['academic', 'semester']) || status?.workspace.semester || '', manualImport: booleanAt(config, ['acquisition', 'manual_import_enabled'], true), watchedFolders: arrayAt(config, ['acquisition', 'watched_folders']).join('\n'), browserEnabled: booleanAt(config, ['browser', 'access_enabled'], false), allowedSites: arrayAt(config, ['browser', 'allowed_sites']).join(', ') } }
function toUpdates(draft: Draft): Record<string, unknown> { return { 'student.name': draft.name, 'student.institution': draft.institution, 'student.program': draft.program, 'academic.timezone': draft.timezone, 'academic.root_directory': draft.root, 'academic.semester': draft.semester, 'acquisition.manual_import_enabled': draft.manualImport, 'acquisition.watched_folders': draft.watchedFolders.split('\n').map((value) => value.trim()).filter(Boolean), 'browser.access_enabled': draft.browserEnabled, 'browser.allowed_sites': draft.allowedSites.split(',').map((value) => value.trim()).filter(Boolean) } }
function valueAt(config: ObjectValue, path: string[]): unknown { let current: unknown = config; for (const part of path) { if (!current || typeof current !== 'object') return undefined; current = (current as ObjectValue)[part] } return current }
function stringAt(config: ObjectValue | null, path: string[]): string { const value = config ? valueAt(config, path) : undefined; return typeof value === 'string' ? value : '' }
function booleanAt(config: ObjectValue, path: string[], fallback: boolean): boolean { const value = valueAt(config, path); return typeof value === 'boolean' ? value : fallback }
function arrayAt(config: ObjectValue, path: string[]): string[] { const value = valueAt(config, path); return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [] }
function format(value: unknown): string { if (value === undefined || value === null || value === '') return 'Unknown'; return typeof value === 'object' ? JSON.stringify(value) : String(value) }
