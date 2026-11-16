import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { GoogleConnectorCard } from './GoogleConnectorCard'
import { api } from './lib/api'
import type { GoogleConnectorStatus } from './types'

vi.mock('./lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./lib/api')>()
  return {
    ...actual,
    isTauriEnvironment: () => false,
    api: {
      ...actual.api,
      googleConnectorStatus: vi.fn(),
      googleConnectorAuthStatus: vi.fn(),
      beginGoogleAuthorization: vi.fn(),
      finishGoogleAuthorization: vi.fn(),
      cancelGoogleAuthorization: vi.fn(),
      disconnectGoogleConnector: vi.fn(),
      setupGoogleConnector: vi.fn(),
      googleCalendarEvents: vi.fn(),
      proposeGoogleCalendarCreate: vi.fn(),
      proposeGoogleCalendarUpdate: vi.fn(),
    },
  }
})

const base: GoogleConnectorStatus = {
  schema_version: 1,
  client_id: null,
  scopes: ['https://www.googleapis.com/auth/gmail.readonly'],
  auth_status: 'not_configured',
  account_email: null,
  authorization_url: null,
  error: null,
  created_at: '2026-11-12T00:00:00Z',
  updated_at: '2026-11-12T00:00:00Z',
  last_checked_at: null,
}

const configured: GoogleConnectorStatus = { ...base, client_id: 'client-id.apps.googleusercontent.com', auth_status: 'configured' }
const authorized: GoogleConnectorStatus = { ...configured, auth_status: 'authorized', account_email: 'student@example.edu' }

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  vi.restoreAllMocks()
})

describe('GoogleConnectorCard', () => {
  it('asks for the local client JSON when Google is not configured', async () => {
    vi.mocked(api.googleConnectorStatus).mockResolvedValue(base)
    render(<GoogleConnectorCard onOpenReview={vi.fn()} />)
    expect(await screen.findByText(/Import the Google OAuth Desktop client JSON/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Import Google client JSON' })).toBeInTheDocument()
  })

  it('starts authorization and shows the pending state', async () => {
    vi.mocked(api.googleConnectorStatus).mockResolvedValue(configured)
    vi.mocked(api.beginGoogleAuthorization).mockResolvedValue({
      authorization_url: 'https://accounts.google.com/test',
      auth_status: 'pending',
      redirect_uri: 'http://127.0.0.1:1234',
      expires_in: 180,
      connection: { ...configured, auth_status: 'pending', authorization_url: 'https://accounts.google.com/test' },
    })
    const opened = vi.spyOn(window, 'open').mockReturnValue(null)
    render(<GoogleConnectorCard onOpenReview={vi.fn()} />)

    fireEvent.click(await screen.findByRole('button', { name: 'Connect Google' }))
    await waitFor(() => expect(api.beginGoogleAuthorization).toHaveBeenCalled())
    expect(opened).toHaveBeenCalledWith('https://accounts.google.com/test', '_blank', 'noopener,noreferrer')
    expect(await screen.findByText(/Complete the Google sign-in/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Cancel sign-in' })).toBeInTheDocument()
  })

  it('shows the connected account and disconnects', async () => {
    vi.mocked(api.googleConnectorStatus).mockResolvedValue(authorized)
    vi.mocked(api.googleCalendarEvents).mockResolvedValue({ time_min: '', time_max: '', count: 0, events: [] })
    vi.mocked(api.disconnectGoogleConnector).mockResolvedValue({ ...configured, error: 'Google account disconnected.' })
    render(<GoogleConnectorCard onOpenReview={vi.fn()} />)

    expect(await screen.findByText('student@example.edu')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Disconnect' }))
    await waitFor(() => expect(api.disconnectGoogleConnector).toHaveBeenCalled())
    expect(await screen.findByRole('button', { name: 'Connect Google' })).toBeInTheDocument()
  })

  it('creates a duplicate-checked calendar Review proposal instead of writing directly', async () => {
    vi.mocked(api.googleConnectorStatus).mockResolvedValue(authorized)
    vi.mocked(api.googleCalendarEvents).mockResolvedValue({ time_min: '', time_max: '', count: 0, events: [] })
    vi.mocked(api.proposeGoogleCalendarCreate).mockResolvedValue({
      proposal: { id: 'proposal-1' },
      review: { id: 'review-calendar-1' } as never,
      next_step: 'Review first',
    })
    const onOpenReview = vi.fn()
    render(<GoogleConnectorCard onOpenReview={onOpenReview} />)

    fireEvent.click(await screen.findByRole('button', { name: 'Propose calendar event' }))
    fireEvent.change(screen.getByLabelText('Event title'), { target: { value: 'Study block' } })
    fireEvent.change(screen.getByLabelText('Start'), { target: { value: '2027-02-10T14:00' } })
    fireEvent.change(screen.getByLabelText('End'), { target: { value: '2027-02-10T15:00' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add to Review' }))

    await waitFor(() => expect(api.proposeGoogleCalendarCreate).toHaveBeenCalledWith(expect.objectContaining({
      summary: 'Study block',
      start: expect.stringMatching(/Z$/),
      end: expect.stringMatching(/Z$/),
    })))
    expect(onOpenReview).toHaveBeenCalledWith('review-calendar-1')
  })
})
