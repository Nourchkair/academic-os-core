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

    fireEvent.click(await screen.findByRole('button', { name: 'Add API provider' }))
    fireEvent.change(screen.getByPlaceholderText('Paste the provider API key'), { target: { value: 'sk-test' } })
    fireEvent.click(screen.getByRole('button', { name: 'Test and connect' }))

    await waitFor(() => expect(api.addModelProvider).toHaveBeenCalledWith(expect.objectContaining({
      provider: 'openai',
      api_key: 'sk-test',
      base_url: 'https://api.openai.com/v1',
    })))
    expect(await screen.findByText('GPT Test')).toBeInTheDocument()
  })

  it('saves per-task model routing', async () => {
    vi.mocked(api.modelConnections).mockResolvedValue(connected)
    vi.mocked(api.setModelPreferences).mockResolvedValue({
      ...connected,
      preferences: { default: 'openai/gpt-test', fast: null, deep: null, vision: null, image: null },
    })
    render(<APIModelProvidersCard />)

    const defaultSelect = await screen.findByLabelText('Default chat')
    fireEvent.change(defaultSelect, { target: { value: 'openai/gpt-test' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save routing' }))
    await waitFor(() => expect(api.setModelPreferences).toHaveBeenCalledWith(expect.objectContaining({ default: 'openai/gpt-test' })))
  })
})
