import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import { api } from './lib/api'
import { AssistantAccountCard } from './AssistantAccountCard'
import type { AccountStatus, ModelConnectionsPayload, ModelProviderCatalogEntry, ModelRole } from './types'

const roleLabels: Array<{ id: ModelRole; label: string; detail: string }> = [
  { id: 'default', label: 'Default model', detail: 'Used for new chats' },
  { id: 'fast', label: 'Fast', detail: 'Quick summaries and side work' },
  { id: 'deep', label: 'Deep', detail: 'Hard reasoning and planning' },
  { id: 'vision', label: 'Visual', detail: 'Images and screenshots' },
  { id: 'image', label: 'Image generation', detail: 'Create images' },
]

const emptyRouting: Record<ModelRole, string | null> = { default: null, fast: null, deep: null, vision: null, image: null }

export function APIModelProvidersCard() {
  const [payload, setPayload] = useState<ModelConnectionsPayload | null>(null)
  const [account, setAccount] = useState<AccountStatus | null>(null)
  const [showChatGPT, setShowChatGPT] = useState(false)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [selectedProvider, setSelectedProvider] = useState<ModelProviderCatalogEntry | null>(null)
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [name, setName] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [routing, setRouting] = useState<Record<ModelRole, string | null>>(emptyRouting)

  const load = useCallback(async () => {
    try {
      const value = await api.modelConnections()
      setPayload(value)
      setRouting(value.preferences)
      setError('')
    } catch (reason) {
      setError(`Model providers could not be loaded. ${String(reason)}`)
    }
  }, [])

  useEffect(() => { void load() }, [load])
  useEffect(() => { void api.accountStatus().then(setAccount).catch(() => setAccount(null)) }, [])
  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(''), 2500)
    return () => window.clearTimeout(timer)
  }, [notice])

  const catalog = payload?.catalog ?? []
  const providers = payload?.providers ?? []
  const apiRows = catalog.filter((entry) => entry.kind === 'api')
  const localRows = catalog.filter((entry) => entry.kind === 'local')
  const modelOptions = useMemo(() => providers
    .filter((provider) => provider.enabled && provider.status === 'connected')
    .flatMap((provider) => provider.models.map((model) => ({ value: `${provider.id}/${model.id}`, label: `${provider.name} · ${model.name}` }))), [providers])

  const chooseProvider = (provider: ModelProviderCatalogEntry) => {
    setSelectedProvider(provider)
    setPickerOpen(false)
    setApiKey('')
    setBaseUrl(provider.default_base_url)
    setName('')
    setError('')
  }

  const closeSetup = () => {
    setSelectedProvider(null)
    setApiKey('')
    setBaseUrl('')
    setName('')
    setError('')
  }

  const connectProvider = async () => {
    if (!selectedProvider) return
    setBusy('connect')
    setError('')
    try {
      const value = await api.addModelProvider({
        provider: selectedProvider.id,
        api_key: apiKey.trim(),
        base_url: baseUrl.trim() || selectedProvider.default_base_url,
        name: name.trim(),
      })
      setPayload(value)
      setRouting(value.preferences)
      setNotice(`${selectedProvider.name} connected.`)
      closeSetup()
    } catch (reason) {
      setError(`Could not connect ${selectedProvider.name}. ${String(reason)}`)
    } finally {
      setBusy('')
    }
  }

  const act = async (provider: string, action: 'test' | 'enable' | 'disable' | 'remove') => {
    setBusy(`${action}:${provider}`)
    setError('')
    try {
      let value: ModelConnectionsPayload
      if (action === 'test') value = await api.testModelProvider(provider)
      else if (action === 'remove') value = await api.removeModelProvider(provider)
      else value = await api.setModelProviderEnabled(provider, action === 'enable')
      setPayload(value)
      setRouting(value.preferences)
      if (action === 'remove') setExpanded(null)
      if (action === 'test') setNotice('Connection is healthy.')
    } catch (reason) {
      setError(`The provider could not be updated. ${String(reason)}`)
    } finally {
      setBusy('')
    }
  }

  const changeRouting = async (role: ModelRole, value: string) => {
    const next = { ...routing, [role]: value || null }
    setRouting(next)
    setBusy(`route:${role}`)
    setError('')
    try {
      const updated = await api.setModelPreferences({ [role]: next[role] })
      setPayload(updated)
      setRouting(updated.preferences)
      setNotice('Routing saved.')
    } catch (reason) {
      setRouting(routing)
      setError(`Routing could not be saved. ${String(reason)}`)
    } finally {
      setBusy('')
    }
  }

  const signedIn = Boolean(account?.authenticated && account.status === 'signed_in')
  return <div className="ai-models-panel">
    {error && <p className="setup-error" role="alert">{error}</p>}
    {notice && <p className="settings-success" role="status">{notice}</p>}

    <section className="connection-block">
      <div className="connection-block-heading"><span>Providers</span></div>
      <div className="provider-list">
        <article className="provider-row">
          <span className="provider-mark">◎</span>
          <div className="provider-copy"><strong>ChatGPT</strong><small>Subscription{account?.account?.email ? ` · ${account.account.email}` : ''}</small></div>
          <span className={`provider-state ${signedIn ? 'connected' : ''}`}>{signedIn ? 'Connected' : account ? 'Not connected' : 'Checking…'}</span>
          <button type="button" className="quiet-button" onClick={() => setShowChatGPT((value) => !value)}>{signedIn ? 'Manage' : 'Connect'}</button>
        </article>
        {showChatGPT && <div className="provider-expand"><AssistantAccountCard /></div>}

        {providers.map((provider) => <Fragment key={provider.id}>
          <article className={`provider-row ${provider.status === 'error' ? 'error' : ''}`}>
            <span className="provider-mark">{(provider.name || provider.id).slice(0, 1).toUpperCase()}</span>
            <div className="provider-copy"><strong>{provider.name}</strong><small>{provider.kind === 'local' ? 'Local' : 'API'} · {provider.models.length} models</small></div>
            <span className={`provider-state ${provider.enabled && provider.status === 'connected' ? 'connected' : ''}`}>{provider.status === 'error' ? 'Error' : provider.enabled ? 'Connected' : 'Disabled'}</span>
            <button type="button" className="quiet-button" aria-label={`Manage ${provider.name}`} onClick={() => setExpanded((value) => value === provider.id ? null : provider.id)}>{expanded === provider.id ? 'Close' : 'Manage'}</button>
          </article>
          {expanded === provider.id && <div className="provider-expand">
            <div className="provider-expand-actions">
              <span className="provider-url">{provider.base_url}</span>
              <button type="button" className="secondary-button" disabled={Boolean(busy)} onClick={() => void act(provider.id, 'test')}>{busy === `test:${provider.id}` ? 'Testing…' : 'Test'}</button>
              <button type="button" className="secondary-button" disabled={Boolean(busy)} onClick={() => void act(provider.id, provider.enabled ? 'disable' : 'enable')}>{provider.enabled ? 'Disable' : 'Enable'}</button>
              <button type="button" className="quiet-button" disabled={Boolean(busy)} onClick={() => void act(provider.id, 'remove')}>Remove</button>
            </div>
            {provider.error && <p className="setup-error" role="alert">{provider.error}</p>}
            <div className="provider-model-chips">{provider.models.slice(0, 10).map((model) => <span key={model.id}>{model.name}</span>)}{provider.models.length > 10 && <span>+{provider.models.length - 10}</span>}</div>
          </div>}
        </Fragment>)}

        <button type="button" className="provider-connect-row" aria-label="Connect a provider" onClick={() => { setPickerOpen(true); setError('') }}><span className="provider-plus">＋</span><span>Connect</span></button>
      </div>
    </section>

    {pickerOpen && <div className="connection-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setPickerOpen(false) }}>
      <section className="connection-dialog" role="dialog" aria-modal="true" aria-labelledby="provider-picker-title">
        <header><div><h3 id="provider-picker-title">Connect a provider</h3><p>Choose a provider to add.</p></div><button type="button" className="quiet-button" onClick={() => setPickerOpen(false)} aria-label="Close provider picker">×</button></header>
        <div className="provider-picker-group"><span>Subscription</span><button type="button" className="provider-picker-row" aria-label="Connect ChatGPT" onClick={() => { setShowChatGPT(true); setPickerOpen(false) }}><span className="provider-mark">◎</span><span><strong>ChatGPT</strong><small>Subscription</small></span></button></div>
        <div className="provider-picker-group"><span>API</span>{apiRows.map((entry) => <button type="button" className="provider-picker-row" aria-label={`Connect ${entry.name}`} key={entry.id} onClick={() => chooseProvider(entry)}><span className="provider-mark">{entry.name.slice(0, 1)}</span><span><strong>{entry.name}</strong><small>API key</small></span></button>)}</div>
        <div className="provider-picker-group"><span>Local</span>{localRows.map((entry) => <button type="button" className="provider-picker-row" aria-label={`Connect ${entry.name}`} key={entry.id} onClick={() => chooseProvider(entry)}><span className="provider-mark">{entry.name.slice(0, 1)}</span><span><strong>{entry.name}</strong><small>No API key</small></span></button>)}</div>
        <button type="button" className="provider-picker-row custom" onClick={() => { const custom = catalog.find((entry) => entry.id === 'custom'); if (custom) chooseProvider(custom) }}><span className="provider-plus">＋</span><span><strong>Add custom provider</strong><small>OpenAI-compatible endpoint</small></span></button>
      </section>
    </div>}

    {selectedProvider && <div className="connection-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeSetup() }}>
      <section className="connection-dialog setup-dialog" role="dialog" aria-modal="true" aria-labelledby="provider-setup-title">
        <header><div><p className="eyebrow">{selectedProvider.kind === 'local' ? 'Local provider' : 'API provider'}</p><h3 id="provider-setup-title">Connect with {selectedProvider.name}</h3><p>{selectedProvider.docs}</p></div><button type="button" className="quiet-button" onClick={closeSetup} aria-label="Close provider setup">×</button></header>
        <div className="setup-dialog-fields">
          {selectedProvider.kind !== 'local' && <label><span>API key</span><input type="password" autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="Paste the provider API key" autoFocus /></label>}
          <details className="advanced-provider"><summary>Advanced</summary>
            <label><span>Base URL</span><input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder={selectedProvider.default_base_url || 'https://provider.example/v1'} /></label>
            {selectedProvider.id === 'custom' && <label><span>Display name</span><input value={name} maxLength={120} onChange={(event) => setName(event.target.value)} placeholder="Custom provider" /></label>}
          </details>
        </div>
        <div className="setup-dialog-actions">
          <button type="button" className="secondary-button" onClick={closeSetup} disabled={busy === 'connect'}>Cancel</button>
          <button type="button" className="primary-button" disabled={busy === 'connect' || (selectedProvider.kind !== 'local' && !apiKey.trim())} onClick={() => void connectProvider()}>{busy === 'connect' ? 'Connecting…' : 'Connect'}</button>
        </div>
      </section>
    </div>}

    <section className="connection-block">
      <div className="connection-block-heading"><span>Task models</span><small>Used by API-backed chat</small></div>
      <div className="model-route-list">
        {roleLabels.map((role) => <div className="model-route-row" key={role.id}>
          <div><strong>{role.label}</strong><small>{role.detail}</small></div>
          <select aria-label={role.label} value={routing[role.id] ?? ''} disabled={!modelOptions.length || busy === `route:${role.id}`} onChange={(event) => void changeRouting(role.id, event.target.value)}>
            <option value="">Not set</option>
            {modelOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </div>)}
      </div>
      {!modelOptions.length && <p className="connection-help-line">Add an API provider to choose task models. API keys stay in Keychain; subscription requests never fall back to API billing.</p>}
    </section>
  </div>
}
