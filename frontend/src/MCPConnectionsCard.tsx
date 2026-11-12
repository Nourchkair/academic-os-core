import { useCallback, useEffect, useState } from 'react'
import { api, isTauriEnvironment } from './lib/api'
import type { MCPConnection } from './types'

type AddDraft = { mode: 'local' | 'remote'; name: string; command: string; url: string; args: string; cwd: string }

const emptyDraft: AddDraft = { mode: 'local', name: '', command: '', url: '', args: '', cwd: '' }

export function MCPConnectionsCard() {
  const [connections, setConnections] = useState<MCPConnection[]>([])
  const [loading, setLoading] = useState(true)
  const [adding, setAdding] = useState(false)
  const [draft, setDraft] = useState<AddDraft>(emptyDraft)
  const [grants, setGrants] = useState<Record<string, string[]>>({})
  const [busy, setBusy] = useState('')
  const [pendingAuth, setPendingAuth] = useState<string | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const value = await api.mcpConnections()
      setConnections(value)
      setGrants(Object.fromEntries(value.map((connection) => [connection.id, connection.granted_tools])))
      setError('')
    } catch (reason) {
      setError(`MCP connections could not be loaded. ${String(reason)}`)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  useEffect(() => {
    if (!pendingAuth) return
    const timer = window.setInterval(() => {
      void api.mcpOAuthStatus(pendingAuth).then((status) => {
        replace(status.connection)
        if (status.auth_status !== 'pending') setPendingAuth(null)
      }).catch(() => undefined)
    }, 2000)
    return () => window.clearInterval(timer)
  }, [pendingAuth])

  const replace = (connection: MCPConnection) => {
    setConnections((current) => current.map((item) => item.id === connection.id ? connection : item))
    setGrants((current) => ({ ...current, [connection.id]: connection.granted_tools }))
  }

  const add = async () => {
    if (!draft.name.trim()) return
    if (draft.mode === 'local' && !draft.command.trim()) return
    if (draft.mode === 'remote' && !draft.url.trim()) return
    setBusy('add')
    setError('')
    try {
      let connection: MCPConnection
      if (draft.mode === 'remote') {
        connection = await api.addRemoteMCPConnection({ name: draft.name.trim(), url: draft.url.trim() })
      } else {
        const args = draft.args.split('\n').map((value) => value.trim()).filter(Boolean)
        connection = await api.addMCPConnection({ name: draft.name.trim(), command: draft.command.trim(), args, cwd: draft.cwd.trim() || null })
      }
      setConnections((current) => [...current, connection])
      setGrants((current) => ({ ...current, [connection.id]: [] }))
      setDraft(emptyDraft)
      setAdding(false)
    } catch (reason) {
      setError(`The MCP connection could not be added. ${String(reason)}`)
    } finally {
      setBusy('')
    }
  }

  const act = async (id: string, action: 'inspect' | 'enable' | 'disable' | 'disconnect' | 'trust') => {
    setBusy(`${action}:${id}`)
    setError('')
    try {
      if (action === 'inspect') replace(await api.inspectMCPConnection(id))
      else if (action === 'enable') replace(await api.enableMCPConnection(id))
      else if (action === 'disable') replace(await api.disableMCPConnection(id))
      else if (action === 'trust') replace(await api.trustMCPConnection(id))
      else {
        await api.disconnectMCPConnection(id)
        setConnections((current) => current.filter((item) => item.id !== id))
      }
    } catch (reason) {
      setError(`The MCP connection could not be updated. ${String(reason)}`)
    } finally {
      setBusy('')
    }
  }

  const beginAuthorization = async (id: string) => {
    setBusy(`auth:${id}`)
    setError('')
    try {
      if (isTauriEnvironment()) {
        setPendingAuth(id)
        setConnections((current) => current.map((item) => item.id === id ? { ...item, auth_status: 'pending' } : item))
        void api.authorizeMCPConnection(id).then((status) => {
          if ('connection' in status) replace(status.connection)
        }).catch((reason) => {
          setPendingAuth(null)
          setError(`MCP authorization could not complete. ${String(reason)}`)
        })
        return
      }
      const started = await api.authorizeMCPConnection(id)
      if ('authorization_url' in started && started.authorization_url) {
        window.open(started.authorization_url, '_blank', 'noopener,noreferrer')
        setPendingAuth(id)
        setConnections((current) => current.map((item) => item.id === id ? { ...item, auth_status: 'pending' } : item))
      } else if ('connection' in started) {
        replace(started.connection)
      }
    } catch (reason) {
      setError(`MCP authorization could not start. ${String(reason)}`)
    } finally {
      setBusy('')
    }
  }

  const cancelAuthorization = async (id: string) => {
    setBusy(`auth-cancel:${id}`)
    try {
      const status = await api.cancelMCPAuthorization(id)
      replace(status.connection)
      setPendingAuth(null)
    } catch (reason) {
      setError(`MCP authorization could not be cancelled. ${String(reason)}`)
    } finally {
      setBusy('')
    }
  }

  const saveGrants = async (id: string) => {
    setBusy(`grant:${id}`)
    setError('')
    try {
      replace(await api.grantMCPConnection(id, grants[id] || []))
    } catch (reason) {
      setError(`The read-only grants could not be saved. ${String(reason)}`)
    } finally {
      setBusy('')
    }
  }

  return <div className="mcp-connections">
    <div className="mcp-connections-heading">
      <p>Connect a local stdio or remote HTTPS MCP server. Academia inspects the server's declared tools, and only tools marked read-only can be granted. Remote servers must be explicitly trusted. No credentials are stored in the academic workspace.</p>
      <button type="button" className="secondary-button" onClick={() => setAdding((value) => !value)}>{adding ? 'Close form' : 'Add connection'}</button>
    </div>
    {error && <p className="setup-error" role="alert">{error}</p>}
    {adding && <div className="coursework-editor mcp-add-form">
      <div className="mcp-mode-switch">
        <button type="button" className={draft.mode === 'local' ? 'active' : ''} onClick={() => setDraft((current) => ({ ...current, mode: 'local' }))}>Local stdio</button>
        <button type="button" className={draft.mode === 'remote' ? 'active' : ''} onClick={() => setDraft((current) => ({ ...current, mode: 'remote' }))}>Remote HTTPS</button>
      </div>
      <div className="coursework-editor-grid">
        <label className="history-title-field"><span>Name</span><input value={draft.name} maxLength={120} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} placeholder="e.g. Local research notes" /></label>
        {draft.mode === 'local' ? <>
          <label><span>Command</span><input value={draft.command} maxLength={1000} onChange={(event) => setDraft((current) => ({ ...current, command: event.target.value }))} placeholder="/path/to/mcp-server" /></label>
          <label><span>Working directory <small>Optional</small></span><input value={draft.cwd} onChange={(event) => setDraft((current) => ({ ...current, cwd: event.target.value }))} /></label>
          <label className="history-wide-field"><span>Arguments <small>One per line</small></span><textarea value={draft.args} rows={3} onChange={(event) => setDraft((current) => ({ ...current, args: event.target.value }))} /></label>
        </> : <label className="history-wide-field"><span>Remote MCP URL</span><input value={draft.url} maxLength={2000} onChange={(event) => setDraft((current) => ({ ...current, url: event.target.value }))} placeholder="https://example.com/mcp" /></label>}
      </div>
      <div className="coursework-editor-actions">
        <button type="button" className="secondary-button" onClick={() => { setAdding(false); setDraft(emptyDraft) }} disabled={busy === 'add'}>Cancel</button>
        <button type="button" className="primary-button" onClick={() => void add()} disabled={busy === 'add' || !draft.name.trim() || (draft.mode === 'local' ? !draft.command.trim() : !draft.url.trim())}>{busy === 'add' ? 'Adding…' : 'Add connection'}</button>
      </div>
    </div>}
    {loading ? <p className="account-note" role="status">Loading local MCP connections…</p> : connections.length === 0 && !adding ? <p className="account-note">No external MCP connections configured. Adding one does not connect it until you inspect its tools and grant read-only access.</p> : <div className="mcp-connection-list">
      {connections.map((connection) => {
        const selected = grants[connection.id] || []
        const remote = connection.transport === 'http'
        const needsAuthorization = remote && connection.auth.type === 'oauth' && connection.auth_status !== 'authorized'
        const trusted = !remote || connection.trust === 'remote_trusted'
        return <article className="mcp-connection-card" key={connection.id}>
          <header>
            <div>
              <span className={`mcp-status ${connection.status}${connection.enabled ? ' enabled' : ''}`}>{connection.enabled ? 'Enabled' : connection.status === 'available' ? 'Inspected' : connection.status === 'error' ? 'Error' : 'Unchecked'}</span>
              <strong>{connection.name}</strong>
              <small>{connection.server_info?.name ? `${connection.server_info.name}${connection.server_info.version ? ` ${connection.server_info.version}` : ''}` : remote ? 'Remote HTTPS server' : 'Local stdio server'} · {connection.scope === 'read_only' ? 'Read-only scope' : connection.scope}{remote ? ` · ${trusted ? 'Trusted' : 'Untrusted'} remote` : ' · Local'}</small>
            </div>
            <div className="mcp-connection-actions">
              {needsAuthorization && connection.auth_status !== 'pending' && <button type="button" className="primary-button" onClick={() => void beginAuthorization(connection.id)} disabled={Boolean(busy)}>{busy === `auth:${connection.id}` ? 'Starting…' : 'Authorize'}</button>}
              {connection.auth_status === 'pending' && <button type="button" className="secondary-button" onClick={() => void cancelAuthorization(connection.id)} disabled={Boolean(busy)}>Cancel authorization</button>}
              {remote && connection.status === 'available' && !trusted && <button type="button" className="secondary-button" onClick={() => void act(connection.id, 'trust')} disabled={Boolean(busy)}>Trust server declarations</button>}
              <button type="button" className="secondary-button" onClick={() => void act(connection.id, 'inspect')} disabled={Boolean(busy) || needsAuthorization}>{busy === `inspect:${connection.id}` ? 'Inspecting…' : 'Inspect tools'}</button>
              {connection.enabled ? <button type="button" className="secondary-button" onClick={() => void act(connection.id, 'disable')} disabled={Boolean(busy)}>Disable</button> : <button type="button" className="primary-button" onClick={() => void act(connection.id, 'enable')} disabled={Boolean(busy) || !connection.granted_tools.length || !trusted}>Enable</button>}
              <button type="button" className="quiet-button" onClick={() => void act(connection.id, 'disconnect')} disabled={Boolean(busy)}>Disconnect</button>
            </div>
          </header>
          <code className="mcp-command">{remote ? connection.url : [connection.command, ...connection.args].join(' ')}</code>
          {remote && <p className="mcp-auth-line">Authorization · {connection.auth_status === 'authorized' ? 'Signed in; tokens are in the system credential store' : connection.auth_status === 'pending' ? 'Waiting for the browser sign-in' : connection.auth_status === 'error' ? 'Authorization failed' : 'Not connected'}</p>}
          {connection.error && <p className="setup-error" role="alert">{connection.error}</p>}
          {connection.status === 'available' && <div className="mcp-tools">
            <p>Server-declared tools. Only read-only tools are eligible.{remote && !trusted ? ' Trust this remote server before granting its tools.' : ''}</p>
            {connection.tools.map((tool) => <label className={`mcp-tool ${tool.read_only ? '' : 'not-grantable'}`} key={tool.name}>
              <input type="checkbox" checked={selected.includes(tool.name)} disabled={!tool.read_only || !trusted || Boolean(busy)} onChange={(event) => setGrants((current) => ({ ...current, [connection.id]: event.target.checked ? [...selected, tool.name] : selected.filter((name) => name !== tool.name) }))} />
              <span><strong>{tool.name}</strong><small>{tool.description || 'No description provided.'}</small></span>
              <em>{tool.read_only ? 'Read-only' : 'Not grantable · write'}</em>
            </label>)}
            <div className="mcp-grant-actions"><button type="button" className="secondary-button" onClick={() => void saveGrants(connection.id)} disabled={Boolean(busy) || !trusted}>{busy === `grant:${connection.id}` ? 'Saving…' : 'Save read-only grants'}</button></div>
          </div>}
        </article>
      })}
    </div>}
  </div>
}
