import { useState } from 'react'
import { APIModelProvidersCard } from './APIModelProvidersCard'
import { GoogleConnectorCard } from './GoogleConnectorCard'
import { MCPConnectionsCard } from './MCPConnectionsCard'
import { NotionConnectorCard } from './NotionConnectorCard'

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
      <APIModelProvidersCard />
    </div>}

    {tab === 'apps' && <div className="connections-panel" role="tabpanel" aria-label="Apps">
      <section className="connection-group">
        <header>
          <div><p className="eyebrow">Google</p><h4>Gmail and Google Calendar</h4></div>
          <span className="connection-type">OAuth app</span>
        </header>
        <GoogleConnectorCard onOpenReview={onOpenReview} />
      </section>
      <section className="connection-group">
        <header>
          <div><p className="eyebrow">Notion</p><h4>Read-only Notion pages</h4></div>
          <span className="connection-type">Integration token</span>
        </header>
        <NotionConnectorCard />
      </section>
      <p className="account-note">App connections use explicit consent and local credentials.</p>
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
