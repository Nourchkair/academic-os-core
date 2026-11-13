import { useCallback, useEffect, useRef, useState } from 'react'
import { open } from '@tauri-apps/plugin-dialog'
import { api, isTauriEnvironment } from './lib/api'
import type { GoogleCalendarEvent, GoogleConnectorStatus } from './types'

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

type CalendarDraft = { summary: string; start: string; end: string; location: string; description: string }

function localDateTime(value: string | undefined) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const offset = date.getTimezoneOffset() * 60_000
  return new Date(date.getTime() - offset).toISOString().slice(0, 16)
}

function rfc3339(value: string) {
  const date = new Date(value)
  if (!value || Number.isNaN(date.getTime())) throw new Error('Enter a valid start and end time.')
  return date.toISOString()
}

function notifyGoogleStatusChanged() {
  window.dispatchEvent(new Event('academia-google-connection-changed'))
}

function newCalendarDraft(): CalendarDraft {
  const start = new Date()
  start.setMinutes(0, 0, 0)
  start.setHours(start.getHours() + 1)
  const end = new Date(start.getTime() + 60 * 60 * 1000)
  return { summary: '', start: localDateTime(start.toISOString()), end: localDateTime(end.toISOString()), location: '', description: '' }
}

export function GoogleConnectorCard({ onOpenReview }: { onOpenReview: (reviewId: string) => void }) {
  const [status, setStatus] = useState<GoogleConnectorStatus | null>(null)
  const [events, setEvents] = useState<GoogleCalendarEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [eventLoading, setEventLoading] = useState(false)
  const [calendarFormOpen, setCalendarFormOpen] = useState(false)
  const [editingEvent, setEditingEvent] = useState<string | null>(null)
  const [calendarDraft, setCalendarDraft] = useState<CalendarDraft>(newCalendarDraft)
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

  const loadEvents = useCallback(async () => {
    setEventLoading(true)
    try {
      const value = await api.googleCalendarEvents(14)
      setEvents(value.events)
    } catch (reason) {
      setError(`Upcoming Google Calendar events could not be loaded. ${String(reason)}`)
    } finally {
      setEventLoading(false)
    }
  }, [])

  useEffect(() => {
    if (status?.auth_status === 'authorized') void loadEvents()
    else setEvents([])
  }, [loadEvents, status?.auth_status])

  useEffect(() => {
    if (!pending && status?.auth_status !== 'pending') return
    const timer = window.setInterval(() => {
      void api.googleConnectorAuthStatus().then((value) => {
        setStatus(value.connection)
        if (value.auth_status !== 'pending') {
          setPending(false)
          if (value.auth_status === 'error') setError(value.error || 'Google sign-in failed.')
          notifyGoogleStatusChanged()
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
          notifyGoogleStatusChanged()
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
      setEvents([])
      setNotice('Google account disconnected.')
      notifyGoogleStatusChanged()
    } catch (reason) {
      setError(`The Google account could not be disconnected. ${String(reason)}`)
    } finally {
      setBusy(false)
    }
  }

  const beginCreate = () => {
    setEditingEvent(null)
    setCalendarDraft(newCalendarDraft())
    setCalendarFormOpen(true)
    setError('')
    setNotice('')
  }

  const beginEdit = (event: GoogleCalendarEvent) => {
    if (!event.id || !event.start.dateTime || !event.end.dateTime) {
      setError('Only timed calendar events can be edited from Academia OS.')
      return
    }
    setEditingEvent(event.id)
    setCalendarDraft({
      summary: event.summary || '',
      start: localDateTime(event.start.dateTime),
      end: localDateTime(event.end.dateTime),
      location: event.location || '',
      description: event.description || '',
    })
    setCalendarFormOpen(true)
    setError('')
    setNotice('')
  }

  const submitCalendarProposal = async () => {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const start = rfc3339(calendarDraft.start)
      const end = rfc3339(calendarDraft.end)
      if (new Date(end).getTime() <= new Date(start).getTime()) throw new Error('The end time must be after the start time.')
      const proposal = editingEvent
        ? await api.proposeGoogleCalendarUpdate(editingEvent, {
            summary: calendarDraft.summary.trim(),
            start,
            end,
            location: calendarDraft.location.trim(),
            description: calendarDraft.description.trim(),
          })
        : await api.proposeGoogleCalendarCreate({
            summary: calendarDraft.summary.trim(),
            start,
            end,
            location: calendarDraft.location.trim(),
            description: calendarDraft.description.trim(),
          })
      setCalendarFormOpen(false)
      setNotice('Nothing has changed yet. Review the exact event proposal, approve it, then execute it as a separate step.')
      onOpenReview(proposal.review.id)
    } catch (reason) {
      setError(`Calendar proposal could not be prepared. ${String(reason)}`)
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
    {authorized && <>
      <p className="account-note">Gmail reads are read-only. Calendar create/edit is available only through duplicate-checked Review proposals; nothing changes in Google until you approve and separately execute the action, which is then verified against Google.</p>
      {notice && <p className="account-note" role="status">{notice}</p>}
      <div className="google-calendar-heading">
        <div><strong>Upcoming primary-calendar events</strong><small>Next 14 days · read-only list</small></div>
        <button type="button" className="secondary-button" disabled={eventLoading || busy} onClick={() => void loadEvents()}>{eventLoading ? 'Refreshing…' : 'Refresh'}</button>
      </div>
      {eventLoading ? <p className="account-note" role="status">Loading calendar events…</p> : events.length ? <div className="google-calendar-event-list">
        {events.map((event) => <article className="google-calendar-event" key={event.id}>
          <div>
            <strong>{event.summary || 'Untitled event'}</strong>
            <small>{event.start.dateTime ? new Date(event.start.dateTime).toLocaleString() : event.start.date || 'Unknown start'}{event.end.dateTime ? ` – ${new Date(event.end.dateTime).toLocaleTimeString()}` : ''}</small>
            {event.location && <small>{event.location}</small>}
          </div>
          <button type="button" className="quiet-button" disabled={busy} onClick={() => beginEdit(event)}>Propose edit</button>
        </article>)}
      </div> : <p className="account-note">No upcoming events were returned.</p>}
      {!calendarFormOpen && <button type="button" className="secondary-button" disabled={busy} onClick={beginCreate}>Propose calendar event</button>}
      {calendarFormOpen && <div className="coursework-editor google-calendar-form">
        <strong>{editingEvent ? 'Propose an event edit' : 'Propose a calendar event'}</strong>
        <p className="account-note">This only creates a Review item. Google Calendar will not change unless you approve it and separately execute the approved action.</p>
        <div className="coursework-editor-grid">
          <label className="history-title-field"><span>Event title</span><input maxLength={1024} value={calendarDraft.summary} onChange={(event) => setCalendarDraft((current) => ({ ...current, summary: event.target.value }))} /></label>
          <label><span>Start</span><input type="datetime-local" value={calendarDraft.start} onChange={(event) => setCalendarDraft((current) => ({ ...current, start: event.target.value }))} /></label>
          <label><span>End</span><input type="datetime-local" value={calendarDraft.end} onChange={(event) => setCalendarDraft((current) => ({ ...current, end: event.target.value }))} /></label>
          <label><span>Location <small>Optional</small></span><input maxLength={1024} value={calendarDraft.location} onChange={(event) => setCalendarDraft((current) => ({ ...current, location: event.target.value }))} /></label>
          <label className="history-wide-field"><span>Description <small>Optional</small></span><textarea maxLength={8192} rows={3} value={calendarDraft.description} onChange={(event) => setCalendarDraft((current) => ({ ...current, description: event.target.value }))} /></label>
        </div>
        <div className="coursework-editor-actions">
          <button type="button" className="secondary-button" disabled={busy} onClick={() => setCalendarFormOpen(false)}>Cancel</button>
          <button type="button" className="primary-button" disabled={busy || !calendarDraft.summary.trim() || !calendarDraft.start || !calendarDraft.end} onClick={() => void submitCalendarProposal()}>{busy ? 'Checking duplicates…' : 'Add to Review'}</button>
        </div>
      </div>}
    </>}
    {!authorized && !waiting && configured && <p className="account-note">{status.error || 'Google is configured. Connect the test account to read Gmail and Calendar.'}</p>}
    {error && <p className="account-note account-error" role="alert">{error}</p>}
    <p className="account-privacy">Google tokens stay in the macOS Keychain. Academia does not store your Google password, and it never sends school-account messages or submits coursework. If macOS asks for a password once, it means your Mac login password, not your Google password.</p>
  </div>
}
