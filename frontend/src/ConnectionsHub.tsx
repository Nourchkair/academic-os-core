import { useState } from 'react'
import { APIModelProvidersCard } from './APIModelProvidersCard'
import { AssistantAccountCard } from './AssistantAccountCard'
import { GoogleConnectorCard } from './GoogleConnectorCard'
import { MCPConnectionsCard } from './MCPConnectionsCard'

type ConnectionsTab = 'models' | 'apps' | 'tools'

const tabs: Array<{ id: ConnectionsTab; label: string; description: string }> = [
  { id: 'models', label: 'AI models', description: 'Subscription and API model providers' },
  { id: 'apps', label: 'Apps', description: 'Google and other academic services' },
  { id: 'tools', label: 'MCP tools', description: 'Optional external tool servers' },
]

export function ConnectionsHub({ onOpenReview }: { onOpenReview: (reviewId: string) => void }) {
  const [tab, setTab] = useState<ConnectionsTab>('models')
  return <div className="connections-hub">
    <nav className="connections-tabs" role="tablist" aria-label="Connection types">
      {tabs.map((entry) => <button
        key={entry.id}
        type="button"
        role="tab"
        aria-selected={tab === entry.id}
        className={tab === entry.id ? 'active' : ''}
        onClick={() => setTab(entry.id)}
      >
        <strong>{entry.label}</strong>
        <small>{entry.description}</small>
      </button>)}
    </nav>

    {tab === 'models' && <div className="connections-panel" role="tabpanel" aria-label="AI models">
      <section className="connection-group">
        <header>
          <div><p className="eyebrow">Subscription</p><h4>Use an existing model plan</h4></div>
          <span className="connection-type">No API key</span>
        </header>
        <AssistantAccountCard />
      </section>
      <section className="connection-group">
        <header>
          <div><p className="eyebrow">API</p><h4>Add a provider API key</h4></div>
          <span className="connection-type">Your provider account</span>
        </header>
        <APIModelProvidersCard />
      </section>
    </div>}

    {tab === 'apps' && <div className="connections-panel" role="tabpanel" aria-label="Apps">
      <section className="connection-group">
        <header>
          <div><p className="eyebrow">Google</p><h4>Gmail and Google Calendar</h4></div>
          <span className="connection-type">OAuth app</span>
        </header>
        <GoogleConnectorCard onOpenReview={onOpenReview} />
      </section>
      <p className="account-note">Future app connections will use the same model: explicit consent, least-privilege scopes, and local credentials. No app starts connected automatically.</p>
    </div>}

    {tab === 'tools' && <div className="connections-panel" role="tabpanel" aria-label="MCP tools">
      <section className="connection-group">
        <header>
          <div><p className="eyebrow">MCP</p><h4>Optional external tool servers</h4></div>
          <span className="connection-type">Read-only grants</span>
        </header>
        <MCPConnectionsCard />
      </section>
    </div>}
  </div>
}
