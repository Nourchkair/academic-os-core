import { useCallback, useEffect, useState } from 'react'
import { api, isTauriEnvironment } from './lib/api'
import type { AccountStatus } from './types'

export function AssistantAccountCard() {
  const [account, setAccount] = useState<AccountStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [error, setError] = useState('')
  const native = isTauriEnvironment()

  const load = useCallback(async () => {
    try {
      setAccount(await api.accountStatus())
      setError('')
    } catch (reason) {
      setError(`ChatGPT sign-in status could not be loaded. ${String(reason)}`)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (native || !account || !['starting', 'awaiting_user'].includes(account.status)) return
    const timer = window.setInterval(() => { void load() }, 2000)
    return () => window.clearInterval(timer)
  }, [account, load, native])

  const act = async (action: 'login' | 'cancel' | 'logout') => {
    if (action === 'cancel') setCancelling(true)
    else setBusy(true)
    setError('')
    try {
      if (action === 'login') {
        const next = await api.accountLogin(setAccount)
        setAccount(next)
      } else {
        const next = action === 'cancel' ? await api.accountLoginCancel() : await api.accountLogout()
        setAccount(next)
      }
    } catch (reason) {
      setError(`ChatGPT sign-in could not be updated. ${String(reason)}`)
    } finally {
      if (action === 'cancel') setCancelling(false)
      else setBusy(false)
    }
  }

  if (!account) {
    return <div className="account-card"><p className="account-note">{error || 'Checking ChatGPT sign-in…'}</p></div>
  }

  const signedIn = account.authenticated && account.status === 'signed_in'
  const awaiting = account.status === 'awaiting_user' || account.status === 'starting'
  return <div className="account-card">
    <div className="account-heading">
      <div>
        <span className={`account-badge ${signedIn ? 'connected' : 'disconnected'}`}>{signedIn ? 'Connected' : account.available ? 'Not connected' : 'Unavailable'}</span>
        <strong>{signedIn ? account.account?.email || 'ChatGPT account' : 'Sign in with ChatGPT'}</strong>
      </div>
      {signedIn && <button type="button" className="secondary-button" disabled={busy} onClick={() => void act('logout')}>{busy ? 'Working…' : 'Sign out'}</button>}
      {!signedIn && !awaiting && <button type="button" className="primary-button" disabled={busy || !account.available} onClick={() => void act('login')}>{busy ? 'Starting…' : 'Sign in with ChatGPT'}</button>}
    </div>
    {signedIn && <p className="account-note">{account.account?.plan_type ? `${account.account.plan_type} plan` : 'ChatGPT plan'}{account.account?.workspace_name ? ` · ${account.account.workspace_name}` : ''}. Requests use your ChatGPT/Codex plan allowance; Academia does not fall back to API billing.</p>}
    {awaiting && <div className="account-login">
      <p>Open the verification page and enter this one-time code:</p>
      <div className="account-code"><code>{account.user_code || 'Waiting for Codex…'}</code>{account.verification_url && <a href={account.verification_url} target="_blank" rel="noopener noreferrer">Open verification page ↗</a>}</div>
      <button type="button" className="secondary-button" disabled={cancelling} onClick={() => void act('cancel')}>{cancelling ? 'Cancelling…' : 'Cancel sign-in'}</button>
    </div>}
    {!signedIn && !awaiting && <p className="account-note">{account.error || account.notice || 'Academia starts the official Codex device-code flow. It never reads or stores your credentials.'}</p>}
    {account.status === 'failed' && account.error && <p className="account-note account-error">{account.error}</p>}
    {error && <p className="account-note account-error" role="alert">{error}</p>}
    <p className="account-privacy">Credentials stay in the official Codex credential store. Academia only receives the account summary and sign-in status.</p>
  </div>
}
