import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { AssistantAccountCard } from './AssistantAccountCard'
import { api } from './lib/api'
import type { AccountStatus } from './types'

vi.mock('./lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./lib/api')>()
  return {
    ...actual,
    isTauriEnvironment: () => false,
    api: {
      ...actual.api,
      accountStatus: vi.fn(),
      accountLogin: vi.fn(),
      accountLoginCancel: vi.fn(),
      accountLogout: vi.fn(),
    },
  }
})

const signedOut: AccountStatus = {
  provider: 'codex',
  available: true,
  authenticated: false,
  status: 'signed_out',
  account: null,
  notice: 'Sign in to Codex with ChatGPT.',
}

const awaiting: AccountStatus = {
  ...signedOut,
  status: 'awaiting_user',
  login_id: 'login-1',
  verification_url: 'https://example.test/device',
  user_code: 'ABCD-EFGH',
}

const signedIn: AccountStatus = {
  ...signedOut,
  authenticated: true,
  status: 'signed_in',
  account: { email: 'student@example.edu', plan_type: 'plus', workspace_name: 'Personal' },
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('AssistantAccountCard', () => {
  it('starts the device-code flow and shows the one-time code', async () => {
    vi.mocked(api.accountStatus).mockResolvedValue(signedOut)
    vi.mocked(api.accountLogin).mockResolvedValue(awaiting)
    render(<AssistantAccountCard />)

    fireEvent.click(await screen.findByRole('button', { name: 'Sign in with ChatGPT' }))
    await waitFor(() => expect(api.accountLogin).toHaveBeenCalled())
    expect(await screen.findByText('ABCD-EFGH')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Open verification page/ })).toHaveAttribute('href', 'https://example.test/device')
  })

  it('shows the signed-in account and signs out', async () => {
    vi.mocked(api.accountStatus).mockResolvedValue(signedIn)
    vi.mocked(api.accountLogout).mockResolvedValue(signedOut)
    render(<AssistantAccountCard />)

    expect(await screen.findByText('student@example.edu')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    await waitFor(() => expect(api.accountLogout).toHaveBeenCalled())
    expect(await screen.findByRole('button', { name: 'Sign in with ChatGPT' })).toBeInTheDocument()
  })
})
