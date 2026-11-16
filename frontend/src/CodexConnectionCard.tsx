import { useEffect, useState } from 'react'
import { api } from './lib/api'
import type { CodexConnectionStatus } from './types'

const actionOptions = [
  { id: 'tasks', label: 'Tasks', hint: 'Create, update, complete, and reopen personal tasks.' },
  { id: 'history', label: 'Grades & coursework history', hint: 'Record and update coursework, scores, percentages, and letter grades.' },
  { id: 'study', label: 'Study sets & practice', hint: 'Create cited study material and record the student’s actual answers and ratings.' },
  { id: 'imports', label: 'File imports', hint: 'Copy local files into a recognized class inbox and start processing.' },
  { id: 'downloads', label: 'Browser downloads', hint: 'Download a source through Codex’s browser, stage it, and import it.' },
] as const

const structuralOptions = [
  { id: 'files', label: 'File moves & trash', hint: 'Move, trash, and restore academic files with verification.' },
  { id: 'calendar', label: 'Calendar changes', hint: 'Create or update calendar events with duplicate checks.' },
  { id: 'structure', label: 'Courses, semesters & settings', hint: 'Create courses or semesters and change local settings.' },
] as const

const defaultActions = actionOptions.map((option) => option.id)

export function CodexConnectionCard() {
  const [status, setStatus] = useState<CodexConnectionStatus | null>(null)
  const [selected, setSelected] = useState<string[]>([...defaultActions])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const applyStatus = (value: CodexConnectionStatus) => {
    setStatus(value)
    if (value.connected && value.allow_actions.length) setSelected(value.allow_actions)
  }

  useEffect(() => {
    let active = true
    void api.codexConnection()
      .then((value) => { if (active) applyStatus(value) })
      .catch((reason) => { if (active) setError(`The Codex connection could not be read. ${String(reason)}`) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  const toggle = (id: string) => {
    setSelected((current) => current.includes(id) ? current.filter((value) => value !== id) : [...current, id])
    setMessage('')
    setError('')
  }

  const connect = async () => {
    if (!selected.length) {
      setError('Select at least one routine action category.')
      return
    }
    setBusy('connect')
    setError('')
    setMessage('')
    try {
      const value = await api.connectCodex(selected)
      applyStatus(value)
      setMessage(
        value.codex_installed
          ? 'Codex is connected. Quit and reopen Codex, then start a new session.'
          : 'The Codex configuration was written. Install the Codex CLI, then restart it.',
      )
    } catch (reason) {
      setError(`Codex could not be connected. ${String(reason)}`)
    } finally {
      setBusy('')
    }
  }

  const disconnect = async () => {
    setBusy('disconnect')
    setError('')
    setMessage('')
    try {
      const value = await api.disconnectCodex()
      applyStatus(value)
      setMessage('The Academia entry was removed from Codex. Restart Codex to finish disconnecting.')
    } catch (reason) {
      setError(`Codex could not be disconnected. ${String(reason)}`)
    } finally {
      setBusy('')
    }
  }

  return <section className="codex-connect-card">
    <div className="codex-connect-status">
      <div>
        <p className="eyebrow">Local MCP</p>
        <h4>{status?.connected ? 'Codex is connected' : 'Connect Codex'}</h4>
        <p>Let Codex on this Mac read your Academia courses and sources, then take the routine actions you allow. No terminal or manual config editing.</p>
      </div>
      <span className={`codex-connect-badge ${status?.connected ? 'connected' : ''}`}>{loading ? 'Checking…' : status?.connected ? 'Connected' : 'Not connected'}</span>
    </div>

    {status?.connected && !status.matches_current_install && <p className="codex-connect-warning">The existing Codex entry points at a different Academia install. Update it to use this app.</p>}
    {status && !status.codex_installed && <p className="codex-connect-warning">The Codex CLI was not found on this Mac. The configuration will still be written.</p>}

    <div className="codex-connect-options">
      {actionOptions.map((option) => <label className="codex-option" key={option.id}>
        <input type="checkbox" checked={selected.includes(option.id)} onChange={() => toggle(option.id)} />
        <span><strong>{option.label}</strong><small>{option.hint}</small></span>
      </label>)}
    </div>

    <details className="codex-connect-advanced">
      <summary>Allow structural changes too <small>Optional</small></summary>
      <p>These actions can move or remove academic files or change your workspace. Leave them off unless you trust Codex to do this without a Review item.</p>
      <div className="codex-connect-options">
        {structuralOptions.map((option) => <label className="codex-option" key={option.id}>
          <input type="checkbox" checked={selected.includes(option.id)} onChange={() => toggle(option.id)} />
          <span><strong>{option.label}</strong><small>{option.hint}</small></span>
        </label>)}
      </div>
    </details>

    <p className="codex-connect-note">Academia edits only its own <code>mcp_servers.academia</code> entry. A timestamped backup of the Codex config is kept, and Review decision/execution tools stay hidden from Codex.</p>

    {status && <p className="codex-connect-path">Config: <code>{status.config_path}</code>{status.backup_path ? ` · Backup: ${status.backup_path}` : ''}</p>}
    {message && <p className="codex-connect-message" role="status">{message}</p>}
    {error && <p className="setup-error" role="alert">{error}</p>}

    <div className="codex-connect-actions">
      <button type="button" className="primary-button" onClick={() => void connect()} disabled={Boolean(busy) || loading || !selected.length}>
        {busy === 'connect' ? 'Connecting…' : status?.connected ? 'Update Codex connection' : 'Connect Codex'}
      </button>
      {status?.connected && <button type="button" className="secondary-button" onClick={() => void disconnect()} disabled={Boolean(busy)}>{busy === 'disconnect' ? 'Disconnecting…' : 'Disconnect'}</button>}
    </div>
  </section>
}
