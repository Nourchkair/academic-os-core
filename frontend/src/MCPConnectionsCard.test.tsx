import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MCPConnectionsCard } from './MCPConnectionsCard'
import { api } from './lib/api'
import type { MCPConnection } from './types'

vi.mock('./lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./lib/api')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      mcpConnections: vi.fn(),
      addMCPConnection: vi.fn(),
      addRemoteMCPConnection: vi.fn(),
      authorizeMCPConnection: vi.fn(),
      mcpOAuthStatus: vi.fn(),
      cancelMCPAuthorization: vi.fn(),
      trustMCPConnection: vi.fn(),
      inspectMCPConnection: vi.fn(),
      grantMCPConnection: vi.fn(),
      enableMCPConnection: vi.fn(),
      disableMCPConnection: vi.fn(),
      disconnectMCPConnection: vi.fn(),
    },
  }
})

const unchecked: MCPConnection = {
  id: 'one',
  name: 'Fake Research',
  transport: 'stdio',
  scope: 'read_only',
  trust: 'local',
  command: '/usr/bin/fake-server',
  url: null,
  args: [],
  cwd: null,
  auth: { type: 'none' },
  auth_status: 'none',
  enabled: false,
  status: 'unchecked',
  server_info: null,
  tools: [],
  granted_tools: [],
  created_at: '2026-11-12T00:00:00Z',
  updated_at: '2026-11-12T00:00:00Z',
}

const inspected: MCPConnection = {
  ...unchecked,
  status: 'available',
  server_info: { name: 'Fake Research', version: '1.0' },
  tools: [
    { name: 'search_notes', description: 'Search notes.', read_only: true, destructive: false, open_world: false },
    { name: 'write_note', description: 'Write notes.', read_only: false, destructive: true, open_world: false },
  ],
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('MCPConnectionsCard', () => {
  it('shows an empty state without claiming a connection', async () => {
    vi.mocked(api.mcpConnections).mockResolvedValue([])
    render(<MCPConnectionsCard />)
    expect(await screen.findByText(/No external MCP connections configured/)).toBeInTheDocument()
  })

  it('inspects tools and saves only read-only grants', async () => {
    vi.mocked(api.mcpConnections).mockResolvedValue([unchecked])
    vi.mocked(api.inspectMCPConnection).mockResolvedValue(inspected)
    vi.mocked(api.grantMCPConnection).mockResolvedValue({ ...inspected, granted_tools: ['search_notes'], enabled: true })
    render(<MCPConnectionsCard />)

    fireEvent.click(await screen.findByRole('button', { name: 'Inspect tools' }))
    await waitFor(() => expect(api.inspectMCPConnection).toHaveBeenCalledWith('one'))
    expect(await screen.findByText('search_notes')).toBeInTheDocument()
    expect(screen.getByText('Not grantable · write')).toBeInTheDocument()

    fireEvent.click(screen.getAllByRole('checkbox')[0])
    fireEvent.click(screen.getByRole('button', { name: 'Save read-only grants' }))
    await waitFor(() => expect(api.grantMCPConnection).toHaveBeenCalledWith('one', ['search_notes']))
  })

  it('requires an explicit trust decision before granting remote tools', async () => {
    const remote: MCPConnection = {
      ...unchecked,
      id: 'remote',
      name: 'Remote Research',
      transport: 'http',
      trust: 'remote_unverified',
      command: null,
      url: 'https://research.example.test/mcp',
      status: 'available',
      server_info: { name: 'Remote Research', version: '1.0' },
      tools: inspected.tools,
    }
    vi.mocked(api.mcpConnections).mockResolvedValue([remote])
    vi.mocked(api.trustMCPConnection).mockResolvedValue({ ...remote, trust: 'remote_trusted' })
    render(<MCPConnectionsCard />)

    expect(await screen.findByText(/Untrusted remote/)).toBeInTheDocument()
    expect(screen.getAllByRole('checkbox')[0]).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Trust server declarations' }))
    await waitFor(() => expect(api.trustMCPConnection).toHaveBeenCalledWith('remote'))
    await waitFor(() => expect(screen.getAllByRole('checkbox')[0]).not.toBeDisabled())
  })
})
