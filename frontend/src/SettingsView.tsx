import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api, isTauriEnvironment } from './lib/api'
import { ConnectionsHub } from './ConnectionsHub'
import type { SettingsPreview, StatusPayload } from './types'
import type { Update } from '@tauri-apps/plugin-updater'

type SettingsViewProps = { status: StatusPayload | null; onSaved: () => Promise<void>; onOpenReview: (reviewId: string) => void }
type Draft = {
  name: string
  institution: string
  program: string
  timezone: string
  root: string
  semester: string
}
type ObjectValue = Record<string, unknown>
export function SettingsView({ status, onSaved, onOpenReview }: SettingsViewProps) {
  const [config, setConfig] = useState<ObjectValue | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [preview, setPreview] = useState<SettingsPreview | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
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

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadSettings()
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
    <SettingsSection title="Connections" description="Choose how Academia reaches AI models, academic apps, and optional external tools. Each connection is explicit and can be removed locally.">
      <ConnectionsHub onOpenReview={onOpenReview} />
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
        <details className="advanced-card"><summary><span className="eyebrow">Advanced</span><strong>Technical details</strong></summary><p>Most users do not need these controls.</p><div className="advanced-grid"><Info label="Profile path" value={status?.profile || 'Unavailable'} /><Info label="Runtime path" value={stringAt(config, ['runtime', 'install_directory']) || 'Unavailable'} /><Info label="CLI version" value={status?.version || 'Unavailable'} /></div></details>
  </div>
}

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
