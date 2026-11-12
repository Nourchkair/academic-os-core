import { useCallback, useEffect, useRef, useState } from 'react'
import { open } from '@tauri-apps/plugin-dialog'
import { api, isTauriEnvironment } from './lib/api'
import type { GoogleConnectorStatus } from './types'

function readClientJson(text: string): { client_id: string; client_secret: string } {
  let value: unknown
  try {
    value = JSON.parse(text)
  } catch {
    throw new Error('That file is not valid JSON.')
  }
  if (!value || typeof value !== 'object') throw new Error('That file is not a Google OAuth client JSON file.')
  const record = value as Record<string, unknown>
  const client = (record.installed || record.web) as Record<string, unknown> | undefined
  if (!client || typeof client.client_id !== 'string' || typeof client.client_secret !== 'string') {
    throw new Error('The file does not contain an installed Google OAuth client id and secret.')
  }
  return { client_id: client.client_id, client_secret: client.client_secret }
}

export function GoogleConnectorCard() {
  const [status, setStatus] = useState<GoogleConnectorStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)
  const native = isTauriEnvironment()

  const load = useCallback(async () => {
    try {
      const value = await api.googleConnectorStatus()
      setStatus(value)
      if (value.auth_status === 'pending') setPending(true)
      setError('')
    } catch (reason) {
      setError(`The Google connection could not be loaded. ${String(reason)}`)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  useEffect(() => {
    if (!pending && status?.auth_status !== 'pending') return
    const timer = window.setInterval(() => {
      void api.googleConnectorAuthStatus().then((value) => {
        setStatus(value.connection)
        if (value.auth_status !== 'pending') {
          setPending(false)
          if (value.auth_status === 'error') setError(value.error || 'Google sign-in failed.')
        }
      }).catch(() => undefined)
    }, 2000)
    return () => window.clearInterval(timer)
  }, [pending, status?.auth_status])

  const importClient = async () => {
    setError('')
    try {
      if (native) {
        const path = await open({ multiple: false, filters: [{ name: 'Google OAuth client', extensions: ['json'] }] })
        if (!path || Array.isArray(path)) return
        setBusy(true)
        setStatus(await api.setupGoogleConnectorFromPath(path))
      } else {
        fileInputRef.current?.click()
      }
    } catch (reason) {
      setError(`The Google client JSON could not be imported. ${String(reason)}`)
    } finally {
      setBusy(false)
    }
  }

  const importSelectedFile = async (file: File | undefined) => {
    if (!file) return
    setBusy(true)
    setError('')
    try {
      const client = readClientJson(await file.text())
      setStatus(await api.setupGoogleConnector(client))
    } catch (reason) {
      setError(`The Google client JSON could not be imported. ${String(reason)}`)
    } finally {
      setBusy(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const connect = async () => {
    setBusy(true)
    setError('')
    try {
      if (native) {
        setPending(true)
        void api.finishGoogleAuthorization().then((value) => {
          setStatus(value)
          setPending(false)
          if (value.auth_status === 'error') setError(value.error || 'Google sign-in failed.')
        }).catch((reason) => {
          setPending(false)
          setError(`Google sign-in could not start. ${String(reason)}`)
        })
      } else {
        const started = await api.beginGoogleAuthorization()
        setStatus(started.connection)
        setPending(true)
        window.open(started.authorization_url, '_blank', 'noopener,noreferrer')
      }
    } catch (reason) {
      setError(`Google sign-in could not start. ${String(reason)}`)
    } finally {
      setBusy(false)
    }
  }

  const cancel = async () => {
    setBusy(true)
    setError('')
    try {
      setStatus(await api.cancelGoogleAuthorization())
      setPending(false)
    } catch (reason) {
      setError(`Google sign-in could not be cancelled. ${String(reason)}`)
    } finally {
      setBusy(false)
    }
  }

  const disconnect = async () => {
    setBusy(true)
    setError('')
    try {
      setStatus(await api.disconnectGoogleConnector())
    } catch (reason) {
      setError(`The Google account could not be disconnected. ${String(reason)}`)
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <p className="account-note" role="status">Checking the Google connection…</p>
  if (!status) return <p className="account-note account-error" role="alert">{error || 'The Google connection is unavailable.'}</p>

  const configured = status.auth_status !== 'not_configured'
  const authorized = status.auth_status === 'authorized'
  const waiting = pending || status.auth_status === 'pending'
  return <div className="account-card google-connector-card">
    <div className="account-heading">
      <div>
        <span className={`account-badge ${authorized ? 'connected' : 'disconnected'}`}>{authorized ? 'Connected' : configured ? 'Not connected' : 'Not configured'}</span>
        <strong>{authorized ? status.account_email || 'Google account' : 'Google account'}</strong>
      </div>
      {authorized && <button type="button" className="secondary-button" disabled={busy} onClick={() => void disconnect()}>{busy ? 'Working…' : 'Disconnect'}</button>}
      {!authorized && !waiting && configured && <button type="button" className="primary-button" disabled={busy} onClick={() => void connect()}>{busy ? 'Starting…' : 'Connect Google'}</button>}
    </div>
    {!configured && <>
      <p className="account-note">Import the Google OAuth Desktop client JSON once on this device. The app stores the client id and secret in the system credential store, never in the academic workspace.</p>
      <div className="settings-actions">
        <button type="button" className="secondary-button" disabled={busy} onClick={() => void importClient()}>{busy ? 'Importing…' : native ? 'Choose Google client JSON' : 'Import Google client JSON'}</button>
        <input ref={fileInputRef} className="chat-file-input" type="file" accept="application/json,.json" onChange={(event) => void importSelectedFile(event.target.files?.[0])} />
      </div>
    </>}
    {waiting && <div className="account-login">
      <p>Complete the Google sign-in in the browser window, then return here.</p>
      {status.authorization_url && <a href={status.authorization_url} target="_blank" rel="noopener noreferrer">Open Google sign-in ↗</a>}
      <button type="button" className="secondary-button" disabled={busy} onClick={() => void cancel()}>{busy ? 'Cancelling…' : 'Cancel sign-in'}</button>
    </div>}
    {authorized && <p className="account-note">Gmail read-only and Calendar read-only access are connected. Calendar writes will require Review approval before any event is created or changed.</p>}
    {!authorized && !waiting && configured && <p className="account-note">{status.error || 'Google is configured. Connect the test account to read Gmail and Calendar.'}</p>}
    {error && <p className="account-note account-error" role="alert">{error}</p>}
    <p className="account-privacy">Google tokens stay in the macOS Keychain. Academia does not store your Google password, and it never sends school-account messages or submits coursework.</p>
  </div>
}
