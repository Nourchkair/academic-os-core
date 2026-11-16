import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { NotionConnectorCard } from './NotionConnectorCard'
import { api } from './lib/api'
import type { NotionStatus } from './types'

vi.mock('./lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./lib/api')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      notionStatus: vi.fn(),
      connectNotion: vi.fn(),
      testNotion: vi.fn(),
      disconnectNotion: vi.fn(),
      searchNotion: vi.fn(),
      readNotionPage: vi.fn(),
    },
  }
})

const disconnected: NotionStatus = {
  schema_version: 1,
  auth_status: 'not_configured',
  account_name: null,
  error: null,
  last_checked_at: null,
  created_at: '2026-11-13T00:00:00Z',
  updated_at: '2026-11-13T00:00:00Z',
}

const connected: NotionStatus = { ...disconnected, auth_status: 'connected', account_name: 'Student Workspace' }

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('NotionConnectorCard', () => {
  it('connects with an integration token', async () => {
    vi.mocked(api.notionStatus).mockResolvedValue(disconnected)
    vi.mocked(api.connectNotion).mockResolvedValue(connected)
    render(<NotionConnectorCard />)

    fireEvent.change(await screen.findByPlaceholderText('Paste the internal integration token'), { target: { value: 'notion-token' } })
    fireEvent.click(screen.getByRole('button', { name: 'Connect Notion' }))
    await waitFor(() => expect(api.connectNotion).toHaveBeenCalledWith('notion-token'))
    expect(await screen.findByText('Student Workspace')).toBeInTheDocument()
  })

  it('searches and reads a shared page', async () => {
    vi.mocked(api.notionStatus).mockResolvedValue(connected)
    vi.mocked(api.searchNotion).mockResolvedValue({ query: 'POL', count: 1, pages: [{ id: 'page-1', object: 'page', title: 'POL 2103 Notes', url: null, last_edited_time: null, archived: false }] })
    vi.mocked(api.readNotionPage).mockResolvedValue({ page_id: 'page-1', text: 'Week 4 notes', block_count: 2, truncated: false })
    render(<NotionConnectorCard />)

    fireEvent.change(await screen.findByLabelText('Search Notion pages'), { target: { value: 'POL' } })
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))
    fireEvent.click(await screen.findByRole('button', { name: /POL 2103 Notes/ }))
    await waitFor(() => expect(api.readNotionPage).toHaveBeenCalledWith('page-1'))
    expect(await screen.findByText('Week 4 notes')).toBeInTheDocument()
  })
})
