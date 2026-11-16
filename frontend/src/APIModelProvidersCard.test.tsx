import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { APIModelProvidersCard } from './APIModelProvidersCard'
import { api } from './lib/api'
import type { ModelConnectionsPayload } from './types'

vi.mock('./lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./lib/api')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      modelConnections: vi.fn(),
      addModelProvider: vi.fn(),
      testModelProvider: vi.fn(),
      removeModelProvider: vi.fn(),
      setModelProviderEnabled: vi.fn(),
      setModelPreferences: vi.fn(),
    },
  }
})

const catalog: ModelConnectionsPayload['catalog'] = [{
  id: 'openai',
  name: 'OpenAI',
  kind: 'api',
  default_base_url: 'https://api.openai.com/v1',
  auth: 'bearer',
  models_path: '/models',
  docs: 'Create an API key at platform.openai.com.',
}]

const empty: ModelConnectionsPayload = {
  providers: [],
  preferences: { default: null, fast: null, deep: null, vision: null, image: null },
  catalog,
}

const connected: ModelConnectionsPayload = {
  ...empty,
  providers: [{
    id: 'openai',
    name: 'OpenAI',
    kind: 'api',
    base_url: 'https://api.openai.com/v1',
    auth: 'configured',
    status: 'connected',
    enabled: true,
    models: [{ id: 'gpt-test', name: 'GPT Test', capabilities: ['chat'] }],
    last_checked_at: '2026-11-13T00:00:00Z',
    error: null,
    created_at: '2026-11-13T00:00:00Z',
    updated_at: '2026-11-13T00:00:00Z',
  }],
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('APIModelProvidersCard', () => {
  it('adds a provider after testing the key and shows the discovered models', async () => {
    vi.mocked(api.modelConnections).mockResolvedValue(empty)
    vi.mocked(api.addModelProvider).mockResolvedValue(connected)
    render(<APIModelProvidersCard />)

    fireEvent.click(await screen.findByRole('button', { name: 'Connect a provider' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Connect OpenAI' }))
    fireEvent.change(await screen.findByPlaceholderText('Paste the provider API key'), { target: { value: 'sk-test' } })
    const setup = screen.getByRole('dialog', { name: /Connect with OpenAI/ })
    fireEvent.click(setup.querySelector('button.primary-button') as HTMLElement)

    await waitFor(() => expect(api.addModelProvider).toHaveBeenCalledWith(expect.objectContaining({
      provider: 'openai',
      api_key: 'sk-test',
      base_url: 'https://api.openai.com/v1',
    })))
    fireEvent.click(await screen.findByRole('button', { name: 'Manage OpenAI' }))
    expect(await screen.findByText('GPT Test')).toBeInTheDocument()
  })

  it('filters the provider picker', async () => {
    vi.mocked(api.modelConnections).mockResolvedValue({
      ...empty,
      catalog: [
        ...catalog,
        { id: 'xai', name: 'xAI (Grok)', kind: 'api', default_base_url: 'https://api.x.ai/v1', auth: 'bearer', models_path: '/models', docs: '' },
        { id: 'opencode-zen', name: 'OpenCode Zen', kind: 'api', default_base_url: 'https://opencode.ai/zen/v1', auth: 'bearer', models_path: '/models', docs: '' },
        { id: 'opencode-go', name: 'OpenCode Go', kind: 'api', default_base_url: 'https://opencode.ai/zen/go/v1', auth: 'bearer', models_path: '/models', docs: '' },
      ],
    })
    render(<APIModelProvidersCard />)

    fireEvent.click(await screen.findByRole('button', { name: 'Connect a provider' }))
    expect(await screen.findByRole('button', { name: 'Connect OpenAI' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Connect OpenCode Go' })).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Search providers'), { target: { value: 'grok' } })
    expect(await screen.findByRole('button', { name: 'Connect xAI (Grok)' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Connect OpenAI' })).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Search providers'), { target: { value: 'zzz' } })
    expect(await screen.findByText(/No provider matches/)).toBeInTheDocument()
  })

  it('saves per-task model routing', async () => {
    vi.mocked(api.modelConnections).mockResolvedValue(connected)
    vi.mocked(api.setModelPreferences).mockResolvedValue({
      ...connected,
      preferences: { default: 'openai/gpt-test', fast: null, deep: null, vision: null, image: null },
    })
    render(<APIModelProvidersCard />)

    const defaultSelect = await screen.findByLabelText('Default model')
    fireEvent.change(defaultSelect, { target: { value: 'openai/gpt-test' } })
    await waitFor(() => expect(api.setModelPreferences).toHaveBeenCalledWith({ default: 'openai/gpt-test' }))
  })
})
