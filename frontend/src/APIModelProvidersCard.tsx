import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from './lib/api'
import type { ModelConnectionsPayload, ModelProviderCatalogEntry, ModelRole } from './types'

type Draft = { provider: string; api_key: string; base_url: string; name: string }

const roleLabels: Array<{ id: ModelRole; label: string }> = [
  { id: 'default', label: 'Default chat' },
  { id: 'fast', label: 'Fast' },
  { id: 'deep', label: 'Deep reasoning' },
  { id: 'vision', label: 'Vision' },
  { id: 'image', label: 'Image generation' },
]

const emptyDraft: Draft = { provider: 'openai', api_key: '', base_url: '', name: '' }

export function APIModelProvidersCard() {
  const [payload, setPayload] = useState<ModelConnectionsPayload | null>(null)
  const [draft, setDraft] = useState<Draft>(emptyDraft)
  const [adding, setAdding] = useState(false)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [routing, setRouting] = useState<Record<ModelRole, string | null>>({ default: null, fast: null, deep: null, vision: null, image: null })

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

  const catalog = payload?.catalog ?? []
  const selected = catalog.find((entry) => entry.id === draft.provider) ?? catalog[0]
  const configured = payload?.providers ?? []
  const modelOptions = useMemo(() => configured
    .filter((provider) => provider.enabled && provider.status === 'connected')
    .flatMap((provider) => provider.models.map((model) => ({ value: `${provider.id}/${model.id}`, label: `${provider.name} · ${model.name}` }))), [configured])

  const chooseProvider = (provider: ModelProviderCatalogEntry) => {
    setDraft({ provider: provider.id, api_key: '', base_url: provider.default_base_url, name: '' })
    setAdding(true)
    setError('')
    setNotice('')
  }

  const addProvider = async () => {
    if (!selected) return
    setBusy('add')
    setError('')
    setNotice('')
    try {
      const value = await api.addModelProvider({
        provider: selected.id,
        api_key: draft.api_key.trim(),
        base_url: draft.base_url.trim() || selected.default_base_url,
        name: draft.name.trim(),
      })
      setPayload(value)
      setRouting(value.preferences)
      setAdding(false)
      setDraft(emptyDraft)
      setNotice(`${selected.name} connected. Its models are ready for routing.`)
    } catch (reason) {
      setError(`The provider could not be connected. ${String(reason)}`)
    } finally {
      setBusy('')
    }
  }

  const act = async (provider: string, action: 'test' | 'enable' | 'disable' | 'remove') => {
    setBusy(`${action}:${provider}`)
    setError('')
    setNotice('')
    try {
      let value: ModelConnectionsPayload
      if (action === 'test') value = await api.testModelProvider(provider)
      else if (action === 'remove') value = await api.removeModelProvider(provider)
      else value = await api.setModelProviderEnabled(provider, action === 'enable')
      setPayload(value)
      setRouting(value.preferences)
    } catch (reason) {
      setError(`The provider could not be updated. ${String(reason)}`)
    } finally {
      setBusy('')
    }
  }

  const saveRouting = async () => {
    setBusy('routing')
    setError('')
    setNotice('')
    try {
      const value = await api.setModelPreferences(routing)
      setPayload(value)
      setRouting(value.preferences)
      setNotice('Model routing saved.')
    } catch (reason) {
      setError(`Model routing could not be saved. ${String(reason)}`)
    } finally {
      setBusy('')
    }
  }

  return <div className="api-model-card">
    {error && <p className="setup-error" role="alert">{error}</p>}
    {notice && <p className="settings-success" role="status">{notice}</p>}

    {!adding && <div className="api-model-add-row">
      <p>Add an API key to use that provider&apos;s models. Keys stay in the macOS Keychain and are never written to the workspace.</p>
      <button type="button" className="primary-button" disabled={Boolean(busy)} onClick={() => chooseProvider(catalog[0] ?? { id: 'openai', name: 'OpenAI', kind: 'api', default_base_url: '', auth: '', models_path: '', docs: '' })}>Add API provider</button>
    </div>}

    {adding && selected && <div className="coursework-editor api-model-form">
      <div className="api-model-provider-grid">
        <label><span>Provider</span><select value={draft.provider} onChange={(event) => { const next = catalog.find((entry) => entry.id === event.target.value); if (next) chooseProvider(next) }}>{catalog.map((entry) => <option key={entry.id} value={entry.id}>{entry.name}</option>)}</select></label>
        {selected.kind !== 'local' && <label><span>API key</span><input type="password" autoComplete="off" value={draft.api_key} onChange={(event) => setDraft((current) => ({ ...current, api_key: event.target.value }))} placeholder="Paste the provider API key" /></label>}
        {(selected.id === 'custom' || selected.kind === 'local' || selected.id === 'openai' || selected.id === 'anthropic' || selected.id === 'gemini') && <label className="history-wide-field"><span>Base URL {selected.kind === 'local' ? <small>Local server</small> : <small>Optional override</small>}</span><input value={draft.base_url} onChange={(event) => setDraft((current) => ({ ...current, base_url: event.target.value }))} placeholder={selected.default_base_url || 'https://provider.example/v1'} /></label>}
        {selected.id === 'custom' && <label><span>Display name <small>Optional</small></span><input value={draft.name} maxLength={120} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} /></label>}
      </div>
      <p className="account-note">{selected.docs}</p>
      <div className="coursework-editor-actions">
        <button type="button" className="secondary-button" disabled={busy === 'add'} onClick={() => { setAdding(false); setDraft(emptyDraft); setError('') }}>Cancel</button>
        <button type="button" className="primary-button" disabled={busy === 'add' || (selected.kind !== 'local' && !draft.api_key.trim()) || !(draft.base_url.trim() || selected.default_base_url)} onClick={() => void addProvider()}>{busy === 'add' ? 'Testing connection…' : 'Test and connect'}</button>
      </div>
    </div>}

    {configured.length > 0 && <div className="api-model-provider-list">
      {configured.map((provider) => <article className={`api-model-provider ${provider.status} ${provider.enabled ? '' : 'disabled'}`} key={provider.id}>
        <header>
          <div>
            <span className={`mcp-status ${provider.status}${provider.enabled ? ' enabled' : ''}`}>{provider.status === 'error' ? 'Error' : provider.enabled ? 'Connected' : 'Disabled'}</span>
            <strong>{provider.name}</strong>
            <small>{provider.kind === 'local' ? 'Local server' : 'API'} · {provider.models.length} model{provider.models.length === 1 ? '' : 's'} · {provider.base_url}</small>
          </div>
          <div className="api-model-provider-actions">
            <button type="button" className="secondary-button" disabled={Boolean(busy)} onClick={() => void act(provider.id, 'test')}>{busy === `test:${provider.id}` ? 'Testing…' : 'Test'}</button>
            <button type="button" className="secondary-button" disabled={Boolean(busy)} onClick={() => void act(provider.id, provider.enabled ? 'disable' : 'enable')}>{provider.enabled ? 'Disable' : 'Enable'}</button>
            <button type="button" className="quiet-button" disabled={Boolean(busy)} onClick={() => void act(provider.id, 'remove')}>Remove</button>
          </div>
        </header>
        {provider.error && <p className="setup-error" role="alert">{provider.error}</p>}
        <div className="api-model-chips">{provider.models.slice(0, 8).map((model) => <span key={model.id}>{model.name}</span>)}{provider.models.length > 8 && <span>+{provider.models.length - 8} more</span>}</div>
      </article>)}
    </div>}

    <section className="api-model-routing">
      <div className="api-model-routing-heading">
        <div><p className="eyebrow">Task routing</p><h4>Choose which model each task should use</h4></div>
        <button type="button" className="secondary-button" disabled={Boolean(busy) || !modelOptions.length} onClick={() => void saveRouting()}>{busy === 'routing' ? 'Saving…' : 'Save routing'}</button>
      </div>
      <div className="api-model-routing-grid">
        {roleLabels.map((role) => <label key={role.id}><span>{role.label}</span><select value={routing[role.id] ?? ''} disabled={!modelOptions.length} onChange={(event) => setRouting((current) => ({ ...current, [role.id]: event.target.value || null }))}><option value="">Not set</option>{modelOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>)}
      </div>
      <p className="account-note">Model routing is used by API-backed Study chat. Subscription ChatGPT routing stays with Codex. Academia will never silently switch from a subscription to API billing.</p>
    </section>
    <p className="account-privacy">API keys are stored in the macOS Keychain by the local Academia sidecar. If macOS asks for a password once, it means your Mac login password, not your provider API key.</p>
  </div>
}
