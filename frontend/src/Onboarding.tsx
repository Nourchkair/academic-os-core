import { useEffect, useState } from 'react'
import { api } from './lib/api'
import type { AttachmentResult, WorkspaceCandidate, WorkspaceCreationResult, WorkspaceInspection } from './types'

type SetupProps = {
  candidates: WorkspaceCandidate[]
  onComplete: () => Promise<void>
  onMigration?: () => Promise<void>
}

type SetupForm = {
  name: string
  institution: string
  program: string
  timezone: string
  semester: string
  workspacePath: string
}

type SetupPreview = AttachmentResult | WorkspaceCreationResult

const steps = ['Welcome', 'Profile', 'Workspace', 'Semester', 'Sources', 'Interface note', 'Review setup', 'Ready']

export function Onboarding({ candidates, onComplete, onMigration }: SetupProps) {
  const [step, setStep] = useState(0)
  const [workspaceMode, setWorkspaceMode] = useState<'new' | 'existing'>(candidates.length ? 'existing' : 'new')
  const [form, setForm] = useState<SetupForm>({
    name: '',
    institution: '',
    program: '',
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
    semester: '',
    workspacePath: candidates[0]?.path || '~/Documents/Academia OS',
  })
  const [inspection, setInspection] = useState<WorkspaceInspection | null>(null)
  const [preview, setPreview] = useState<SetupPreview | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const update = (key: keyof SetupForm, value: string) => setForm((current) => ({ ...current, [key]: value }))

  // Semester labels come from the core calendar policy; this browser shell never reimplements term rules.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { void api.semester(form.timezone).then((result) => { if (!form.semester) update('semester', result.semester) }).catch(() => undefined) }, [form.timezone])

  const selectedCandidate = candidates.find((candidate) => candidate.path === form.workspacePath)

  const inspect = async () => {
    if (!form.workspacePath.trim()) return
    try {
      setBusy(true)
      setError(null)
      const result = await api.workspaceInspect(form.workspacePath.trim())
      setInspection(result)
      if (!form.semester) update('semester', result.suggested_semester)
    } catch (reason) {
      setError(`I could not inspect that folder yet: ${String(reason)}`)
      setInspection(null)
    } finally {
      setBusy(false)
    }
  }

  const preparePreview = async () => {
    try {
      setBusy(true)
      setError(null)
      const input = { path: form.workspacePath.trim(), name: form.name, institution: form.institution, program: form.program, timezone: form.timezone, semester: form.semester }
      const result = workspaceMode === 'existing' ? await api.workspaceAttach({ ...input, apply: false }) : await api.workspaceCreate({ ...input, apply: false })
      setPreview(result)
    } catch (reason) {
      setError(`I could not prepare that setup yet: ${String(reason)}`)
    } finally {
      setBusy(false)
    }
  }

  const applySetup = async () => {
    try {
      setBusy(true)
      setError(null)
      const input = { path: form.workspacePath.trim(), name: form.name, institution: form.institution, program: form.program, timezone: form.timezone, semester: form.semester, apply: true }
      const result = workspaceMode === 'existing' ? await api.workspaceAttach(input) : await api.workspaceCreate(input)
      setPreview(result)
      setStep(7)
    } catch (reason) {
      setError(`Setup was not applied: ${String(reason)}`)
    } finally {
      setBusy(false)
    }
  }

  const next = async () => {
    setError(null)
    if (step === 1 && (!form.name.trim() || !form.institution.trim())) {
      setError('Add your name and institution so Academia OS can create a trustworthy local profile.')
      return
    }
    if (step === 2) {
      if (!form.workspacePath.trim()) {
        setError('Choose where your academic workspace should live.')
        return
      }
      if (workspaceMode === 'existing') {
        if (!inspection) {
          await inspect()
          return
        }
        if (!inspection.recognized) {
          setError('That folder does not have the expected Academia OS markers. Choose another folder or start a fresh workspace.')
          return
        }
      }
    }
    if (step === 3 && !/^(Winter|Spring|Summer|Fall) \d{4}$/.test(form.semester)) {
      setError('Choose a specific semester using a term name and four-digit year.')
      return
    }
    if (step === 5) {
      setStep(6)
      return
    }
    if (step === 6) {
      if (preview) await applySetup()
      else await preparePreview()
      return
    }
    setStep((current) => Math.min(current + 1, steps.length - 1))
  }

  const back = () => {
    setError(null)
    setStep((current) => Math.max(current - 1, 0))
  }

  return <main className="onboarding-shell">
    <div className="onboarding-brand"><div className="brand-mark">A</div><strong>Academia <span>OS</span></strong></div>
    <div className="onboarding-progress" aria-label="Setup progress">{steps.map((label, index) => <span className={index <= step ? 'complete' : ''} key={label}>{index + 1}</span>)}</div>
    <section className="onboarding-card">
      <p className="eyebrow">{steps[step]}</p>
      {step === 0 && <Welcome />}
      {step === 1 && <Profile form={form} update={update} />}
      {step === 2 && <Workspace form={form} update={update} mode={workspaceMode} setMode={(value) => { setWorkspaceMode(value); setInspection(null); setPreview(null) }} candidates={candidates} selectedCandidate={selectedCandidate} inspection={inspection} onInspect={() => void inspect()} busy={busy} />}
      {step === 3 && <Semester form={form} update={update} inspection={inspection} />}
      {step === 4 && <Sources />}
      {step === 5 && <InterfaceNote />}
      {step === 6 && <ReviewSetup form={form} mode={workspaceMode} inspection={inspection} preview={preview} onRefresh={() => void preparePreview()} busy={busy} />}
      {step === 7 && <Ready form={form} mode={workspaceMode} preview={preview} onOpen={onComplete} onMigration={onMigration} />}
      {error && <p className="setup-error" role="alert">{error}</p>}
      {step < 7 && <div className="onboarding-actions"><button className="quiet-button" onClick={back} disabled={step === 0 || busy}>Back</button><button className="primary-button" onClick={() => void next()} disabled={busy}>{busy ? 'Checking…' : step === 0 ? 'Begin setup' : step === 6 ? 'Review and continue' : 'Continue'}</button></div>}
    </section>
    <p className="onboarding-footnote">Your academic files stay on this computer. Academia OS never needs your password or MFA code.</p>
  </main>
}

function Welcome() {
  return <div className="setup-content"><div className="setup-hero-mark">✦</div><h1>Your academic workspace, made understandable.</h1><p>Academia OS organizes your school files locally, keeps original material readable, and gives you one calm place to see what needs attention. Compatible AI assistants are optional.</p><div className="setup-benefits"><span>Originals stay preserved</span><span>Uncertainty stays visible</span><span>Works without an AI agent</span></div></div>
}

function Profile({ form, update }: { form: SetupForm; update: (key: keyof SetupForm, value: string) => void }) {
  return <div className="setup-content"><h1>Tell us about you</h1><p>This personalizes the workspace without sending your academic files anywhere.</p><div className="setup-form-grid"><Field label="Your name" value={form.name} onChange={(value) => update('name', value)} placeholder="Alex" /><Field label="University or institution" value={form.institution} onChange={(value) => update('institution', value)} placeholder="Your university" /><Field label="Program or faculty (optional)" value={form.program} onChange={(value) => update('program', value)} placeholder="Political science" /><Field label="Time zone" value={form.timezone} onChange={(value) => update('timezone', value)} placeholder="America/Toronto" /></div></div>
}

function Workspace({ form, update, mode, setMode, candidates, selectedCandidate, inspection, onInspect, busy }: { form: SetupForm; update: (key: keyof SetupForm, value: string) => void; mode: 'new' | 'existing'; setMode: (value: 'new' | 'existing') => void; candidates: WorkspaceCandidate[]; selectedCandidate?: WorkspaceCandidate; inspection: WorkspaceInspection | null; onInspect: () => void; busy: boolean }) {
  return <div className="setup-content"><h1>Where should school files live?</h1><p>Choose a fresh location or safely connect an existing Academia-style workspace. We inspect first and do not move or rewrite academic files.</p><div className="mode-switch"><button className={mode === 'new' ? 'selected' : ''} onClick={() => setMode('new')}><strong>Start fresh</strong><span>Create a new structured workspace.</span></button><button className={mode === 'existing' ? 'selected' : ''} onClick={() => setMode('existing')}><strong>Use an existing workspace</strong><span>Inspect a folder you already organized.</span></button></div><label className="setup-field"><span>Workspace location</span><input value={form.workspacePath} onChange={(event) => update('workspacePath', event.target.value)} placeholder="~/Documents/Academia OS" /></label>{mode === 'existing' && candidates.length > 0 && <div className="candidate-list"><span className="field-caption">Likely folders found on this computer</span>{candidates.slice(0, 5).map((candidate) => <button className={selectedCandidate?.path === candidate.path ? 'candidate selected' : 'candidate'} key={candidate.path} onClick={() => update('workspacePath', candidate.path)}>{candidate.path}<small>{candidate.reasons.join(' · ')}</small></button>)}</div>}{mode === 'existing' && <button className="secondary-button" onClick={onInspect} disabled={busy}>{busy ? 'Inspecting…' : 'Inspect this workspace'}</button>}{inspection && <InspectionSummary inspection={inspection} />}{mode === 'new' && <p className="setup-note">The location must be empty. Academia OS will create the folder structure only after you review and confirm it.</p>}</div>
}

function InspectionSummary({ inspection }: { inspection: WorkspaceInspection }) {
  return <div className={`inspection-summary ${inspection.recognized ? 'safe' : 'warning'}`}><strong>{inspection.recognized ? 'Workspace recognized' : 'Needs another folder'}</strong><span>{inspection.semester_count} semester{inspection.semester_count === 1 ? '' : 's'} · {inspection.course_count} course{inspection.course_count === 1 ? '' : 's'} · {inspection.file_count} readable file{inspection.file_count === 1 ? '' : 's'}</span>{inspection.anomalies.length > 0 && <small>{inspection.anomalies.length} structure note{inspection.anomalies.length === 1 ? '' : 's'} will remain visible for review.</small>}</div>
}

function Semester({ form, update, inspection }: { form: SetupForm; update: (key: keyof SetupForm, value: string) => void; inspection: WorkspaceInspection | null }) {
  return <div className="setup-content"><h1>Which semester are you organizing?</h1><p>Academia OS chooses a real semester label instead of saving an ambiguous “Current Semester.” You can adjust it if your workspace is ahead or behind.</p><Field label="Semester" value={form.semester || inspection?.suggested_semester || ''} onChange={(value) => update('semester', value)} placeholder="e.g. Fall 2027" /><div className="setup-note">Current suggestion: <strong>{inspection?.suggested_semester || form.semester || 'Resolve from the local calendar'}</strong></div></div>
}

function Sources() {
  return <div className="setup-content"><h1>How will material arrive?</h1><p>Importing is always available from the + workspace action. Academia OS keeps the choice explicit and local instead of turning intake preferences into another setting.</p><div className="choice-list"><div className="choice-card selected"><span className="choice-icon">↓</span><div><strong>Import files manually</strong><small>Choose PDFs, documents, slides, or notes whenever you receive them from the + button.</small></div><b>Available</b></div><div className="choice-card"><span className="choice-icon">◫</span><div><strong>Run a one-shot folder scan</strong><small>Ask Academia OS or an authorized external agent to scan a configured folder when you choose.</small></div><b>Optional</b></div></div><p className="setup-note">No persistent monitoring is enabled here. External agents, browser sessions, and recurring schedules are not configured in this app.</p></div>
}

function InterfaceNote() {
  return <div className="setup-content"><h1>Use your own tools when you choose</h1><p>Academia OS is the local workspace and safety layer. It does not connect an AI model, browser session, or scheduler here.</p><div className="agent-choice"><div><strong>Neutral local interface</strong><span>Codex, Hermes, Claude, ChatGPT/Work, or another authorized tool can use the CLI/API and AGENTS.md.</span></div><em>Available</em></div><div className="agent-choice muted"><div><strong>Nothing is connected by this setup</strong><span>No agent credentials, browser session, or recurring job is created during onboarding.</span></div><em>Safe default</em></div></div>
}

function ReviewSetup({ form, mode, inspection, preview, onRefresh, busy }: { form: SetupForm; mode: 'new' | 'existing'; inspection: WorkspaceInspection | null; preview: SetupPreview | null; onRefresh: () => void; busy: boolean }) {
  return <div className="setup-content"><h1>Review your setup</h1><p>Nothing is changed until you confirm. Review the location and the safety boundary first.</p><div className="setup-summary"><SummaryRow label="Workspace" value={form.workspacePath} /><SummaryRow label="Mode" value={mode === 'new' ? 'Create a new workspace' : 'Attach existing workspace'} /><SummaryRow label="Semester" value={form.semester} /><SummaryRow label="Profile" value={`${form.name} · ${form.institution}`} /></div>{inspection && <InspectionSummary inspection={inspection} />}{preview && <div className="preview-banner"><strong>{preview.applied ? 'Setup applied' : 'Ready for your confirmation'}</strong><span>{preview.academic_files_changed ? 'The workspace was initialized from the reusable template.' : 'Academic files will not be moved, renamed, or rewritten.'}</span></div>}{!preview && <button className="secondary-button" onClick={onRefresh} disabled={busy}>{busy ? 'Preparing…' : 'Prepare setup summary'}</button>}</div>
}

function Ready({ form, mode, preview, onOpen, onMigration }: { form: SetupForm; mode: 'new' | 'existing'; preview: SetupPreview | null; onOpen: () => Promise<void>; onMigration?: () => Promise<void> }) {
  return <div className="setup-content ready-content"><div className="ready-mark">✓</div><h1>You’re ready to begin</h1><p>{mode === 'new' ? 'Your local workspace has been created.' : 'Your existing workspace is connected without changing its academic files.'}</p><div className="setup-summary"><SummaryRow label="Workspace" value={form.workspacePath} /><SummaryRow label="Semester" value={form.semester} /><SummaryRow label="Next step" value="Import your first course material" /></div><button className="primary-button" onClick={() => void onOpen()}>Open Academia OS</button>{onMigration && <button className="secondary-button onboarding-migration-button" onClick={() => void onMigration()}>Bring in older material <span>↗</span></button>}{preview && 'backup_profile' in preview && preview.backup_profile ? <small className="setup-note">Your previous local profile was preserved as a backup.</small> : null}</div>
}

function Field({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (value: string) => void; placeholder: string }) {
  return <label className="setup-field"><span>{label}</span><input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} /></label>
}

function SummaryRow({ label, value }: { label: string; value: string }) { return <div><span>{label}</span><strong>{value}</strong></div> }
