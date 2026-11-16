import { useCallback, useEffect, useState } from 'react'
import { api } from './lib/api'
import type { NotionPage, NotionPageContent, NotionStatus } from './types'

export function NotionConnectorCard() {
  const [status, setStatus] = useState<NotionStatus | null>(null)
  const [token, setToken] = useState('')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [query, setQuery] = useState('')
  const [pages, setPages] = useState<NotionPage[]>([])
  const [selected, setSelected] = useState<NotionPageContent | null>(null)

  const load = useCallback(async () => {
    try {
      setStatus(await api.notionStatus())
      setError('')
    } catch (reason) {
      setError(`The Notion connection could not be loaded. ${String(reason)}`)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const connect = async () => {
    setBusy('connect')
    setError('')
    setNotice('')
    try {
      setStatus(await api.connectNotion(token.trim()))
      window.dispatchEvent(new Event('academia-notion-connection-changed'))
      setToken('')
      setNotice('Notion connected. Only pages shared with the integration can be read.')
    } catch (reason) {
      setError(`Notion could not be connected. ${String(reason)}`)
    } finally {
      setBusy('')
    }
  }

  const test = async () => {
    setBusy('test')
    setError('')
    setNotice('')
    try {
      setStatus(await api.testNotion())
      window.dispatchEvent(new Event('academia-notion-connection-changed'))
      setNotice('Notion token is valid.')
    } catch (reason) {
      setError(`Notion could not be tested. ${String(reason)}`)
    } finally {
      setBusy('')
    }
  }

  const disconnect = async () => {
    setBusy('disconnect')
    setError('')
    try {
      setStatus(await api.disconnectNotion())
      window.dispatchEvent(new Event('academia-notion-connection-changed'))
      setPages([])
      setSelected(null)
      setNotice('Notion disconnected and its local token removed.')
    } catch (reason) {
      setError(`Notion could not be disconnected. ${String(reason)}`)
    } finally {
      setBusy('')
    }
  }

  const search = async () => {
    setBusy('search')
    setError('')
    setNotice('')
    try {
      const value = await api.searchNotion(query.trim(), 10)
      setPages(value.pages)
      if (!value.pages.length) setNotice('No pages were returned. Share a page with the Notion integration first.')
    } catch (reason) {
      setError(`Notion search failed. ${String(reason)}`)
    } finally {
      setBusy('')
    }
  }

  const read = async (page: NotionPage) => {
    setBusy(`read:${page.id}`)
    setError('')
    try {
      setSelected(await api.readNotionPage(page.id))
    } catch (reason) {
      setError(`The Notion page could not be read. ${String(reason)}`)
    } finally {
      setBusy('')
    }
  }

  const connected = status?.auth_status === 'connected'
  return <div className="notion-connector-card">
    {error && <p className="setup-error" role="alert">{error}</p>}
    {notice && <p className="settings-success" role="status">{notice}</p>}
    {!connected && <div className="coursework-editor api-model-form">
      <p className="account-note">Read-only pages shared with a Notion integration.</p>
      <label><span>Integration token</span><input type="password" autoComplete="off" value={token} onChange={(event) => setToken(event.target.value)} placeholder="Paste the internal integration token" /></label>
      <div className="coursework-editor-actions">
        <button type="button" className="primary-button" disabled={busy === 'connect' || !token.trim()} onClick={() => void connect()}>{busy === 'connect' ? 'Validating…' : 'Connect Notion'}</button>
      </div>
      <details className="connection-details"><summary>How to get a token</summary><div className="connection-details-body"><p className="account-note">Create an internal Notion integration, share the pages you want Academia to read, then paste its token. Academia cannot edit or create Notion content.</p></div></details>
    </div>}
    {connected && <>
      <div className="notion-heading">
        <div><span className="mcp-status available enabled">Connected</span><strong>{status?.account_name || 'Notion integration'}</strong><small>Read-only pages shared with the integration</small></div>
        <div className="api-model-provider-actions">
          <button type="button" className="secondary-button" disabled={Boolean(busy)} onClick={() => void test()}>{busy === 'test' ? 'Testing…' : 'Test'}</button>
          <button type="button" className="quiet-button" disabled={Boolean(busy)} onClick={() => void disconnect()}>Disconnect</button>
        </div>
      </div>
      <div className="notion-search-row">
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search Notion pages" aria-label="Search Notion pages" />
        <button type="button" className="secondary-button" disabled={busy === 'search'} onClick={() => void search()}>{busy === 'search' ? 'Searching…' : 'Search'}</button>
      </div>
      {pages.length > 0 && <div className="notion-page-list">{pages.map((page) => <button type="button" className="notion-page-row" key={page.id} disabled={Boolean(busy)} onClick={() => void read(page)}><strong>{page.title}</strong><small>{page.last_edited_time ? new Date(page.last_edited_time).toLocaleString() : 'Notion page'}</small></button>)}</div>}
      {selected && <div className="notion-page-preview"><header><strong>Notion page preview</strong><button type="button" className="quiet-button" onClick={() => setSelected(null)}>Close</button></header><pre>{selected.text || 'No readable text blocks were returned.'}</pre>{selected.truncated && <small>The page preview was truncated.</small>}</div>}
    </>}
    <p className="account-privacy">The Notion token stays in the macOS Keychain. Academia only reads pages explicitly shared with the integration.</p>
  </div>
}
