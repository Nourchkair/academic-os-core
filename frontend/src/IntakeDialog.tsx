import { useEffect, useState } from 'react'
import { DeadlineChangeDialog } from './DeadlineChange'
import { api } from './lib/api'
import type { ChangeSet, Course, CourseworkHistoryRecord, IntakeCandidate, IntakePasteResult, LibraryItem } from './types'

type IntakeDialogProps = {
  course: Course
  semester: string
  onClose: () => void
  onChanged: () => Promise<void>
}

type ActiveReview = {
  candidate: IntakeCandidate
  changeset: ChangeSet
}

export function IntakeDialog({ course, semester, onClose, onChanged }: IntakeDialogProps) {
  const [text, setText] = useState('')
  const [sourceKind, setSourceKind] = useState<'student_report' | 'professor_announcement'>('student_report')
  const [result, setResult] = useState<IntakePasteResult | null>(null)
  const [candidates, setCandidates] = useState<IntakeCandidate[]>([])
  const [documents, setDocuments] = useState<LibraryItem[]>([])
  const [selectedDocument, setSelectedDocument] = useState('')
  const [selectedAssessments, setSelectedAssessments] = useState<Record<string, string>>({})
  const [activeReview, setActiveReview] = useState<ActiveReview | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refreshCandidates = async () => {
    const value = await api.intakeList(semester, { courseId: course.id })
    setCandidates(value.candidates)
  }

  useEffect(() => {
    let active = true
    void Promise.all([
      api.intakeList(semester, { courseId: course.id }),
      api.library({ courseId: course.id, semester }),
    ])
      .then(([candidateValue, libraryValue]) => {
        if (!active) return
        setCandidates(candidateValue.candidates)
        setDocuments(libraryValue.filter((item) => !item.source_note && ['.pdf', '.docx', '.pptx', '.md', '.txt'].includes(item.extension.toLowerCase())))
      })
      .catch((reason) => { if (active) setError(String(reason)) })
    return () => { active = false }
  }, [course.id, semester])

  if (activeReview) {
    const assessmentOperation = activeReview.changeset.operations.find((operation) => operation.type === 'assessment.set_deadline')
    const record: CourseworkHistoryRecord = {
      id: '',
      kind: 'other',
      title: assessmentOperation?.target_title || activeReview.candidate.entity_title || 'Assessment',
      status: 'planned',
      due_date: assessmentOperation?.before || null,
      record_basis: 'legacy',
      status_history: [],
      artifact_paths: [],
      created_at: '',
      updated_at: '',
      actor: 'user',
    }
    return <DeadlineChangeDialog
      course={course}
      semester={semester}
      record={record}
      initialChangeset={activeReview.changeset}
      onClose={() => { setActiveReview(null); void refreshCandidates() }}
      onChanged={async () => { await onChanged(); await refreshCandidates() }}
    />
  }

  const submit = async () => {
    if (!text.trim()) { setError('Paste the announcement first.'); return }
    setBusy(true); setError(null)
    try {
      const value = await api.intakePaste({ courseId: course.id, semester, text, sourceKind })
      setResult(value)
      setSelectedAssessments({})
      await refreshCandidates()
      void onChanged()
    } catch (reason) {
      setError(String(reason))
    } finally {
      setBusy(false)
    }
  }

  const scanDocument = async () => {
    if (!selectedDocument) { setError('Choose a course document first.'); return }
    setBusy(true); setError(null)
    try {
      const value = await api.intakeDocument({ courseId: course.id, semester, source: selectedDocument })
      setResult(value)
      setSelectedAssessments({})
      await refreshCandidates()
      void onChanged()
    } catch (reason) {
      setError(String(reason))
    } finally {
      setBusy(false)
    }
  }

  const replaceCandidate = (candidate: IntakeCandidate) => {
    setCandidates((current) => current.map((item) => item.id === candidate.id ? candidate : item))
    setResult((current) => current ? { ...current, candidates: current.candidates.map((item) => item.id === candidate.id ? candidate : item) } : current)
  }

  const resolve = async (candidate: IntakeCandidate) => {
    const assessmentId = selectedAssessments[candidate.id]
    if (!assessmentId) { setError('Choose the matching assessment first.'); return }
    setBusy(true); setError(null)
    try {
      const value = await api.intakeResolve(candidate.id, semester, { courseId: course.id, assessmentId })
      replaceCandidate(value.candidate)
      void onChanged()
    } catch (reason) {
      setError(String(reason))
    } finally {
      setBusy(false)
    }
  }

  const prepare = async (candidate: IntakeCandidate) => {
    setBusy(true); setError(null)
    try {
      const changeset = await api.intakePropose(candidate.id, semester)
      await refreshCandidates()
      setActiveReview({ candidate: { ...candidate, status: 'proposed', proposed_change_id: changeset.id }, changeset })
      void onChanged()
    } catch (reason) {
      setError(String(reason))
    } finally {
      setBusy(false)
    }
  }

  const openProposed = async (candidate: IntakeCandidate) => {
    setBusy(true); setError(null)
    try {
      const value = await api.intakeShow(candidate.id, semester)
      if (!value.changeset) throw new Error('The proposed ChangeSet could not be loaded.')
      if (['cancelled', 'superseded'].includes(value.changeset.status)) {
        const changeset = await api.intakePropose(candidate.id, semester)
        await refreshCandidates()
        setActiveReview({ candidate: value.candidate, changeset })
        void onChanged()
        return
      }
      setActiveReview({ candidate: value.candidate, changeset: value.changeset })
    } catch (reason) {
      setError(String(reason))
    } finally {
      setBusy(false)
    }
  }

  const dismiss = async (candidate: IntakeCandidate) => {
    setBusy(true); setError(null)
    try {
      const value = await api.intakeReject(candidate.id, semester)
      replaceCandidate(value.candidate)
      void onChanged()
    } catch (reason) {
      setError(String(reason))
    } finally {
      setBusy(false)
    }
  }

  return <div className="deadline-change-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose() }}>
    <section className="intake-dialog" role="dialog" aria-modal="true" aria-labelledby="intake-title">
      <header className="deadline-change-heading">
        <div><p className="eyebrow">Academic intake</p><h2 id="intake-title">Paste an announcement</h2><p>{course.name} · the exact text is preserved before anything is proposed.</p></div>
        <button className="icon-button" type="button" aria-label="Close intake" onClick={onClose} disabled={busy}>×</button>
      </header>

      {error && <p className="setup-error" role="alert">{error}</p>}

      <div className="intake-form">
        <label><span>Announcement text</span><textarea value={text} onChange={(event) => setText(event.target.value)} rows={5} maxLength={20000} placeholder="Paste the professor's announcement or your note about what changed." autoFocus /></label>
        <label><span>Where did this come from?</span><select value={sourceKind} onChange={(event) => setSourceKind(event.target.value as 'student_report' | 'professor_announcement')}><option value="student_report">Student report</option><option value="professor_announcement">Professor announcement</option></select></label>
        <div className="intake-form-actions"><button type="button" className="secondary-button" onClick={onClose} disabled={busy}>Close</button><button type="button" className="primary-button" onClick={() => void submit()} disabled={busy || !text.trim()}>{busy ? 'Reading…' : 'Find deadline changes'}</button></div>
      </div>

      <div className="intake-document-form">
        <div><p className="eyebrow">Imported document</p><p>Scan a document already in this course. The original is preserved.</p></div>
        {documents.length ? <div className="intake-document-actions"><select aria-label="Course document" value={selectedDocument} onChange={(event) => setSelectedDocument(event.target.value)}><option value="">Choose document…</option>{documents.map((item) => <option value={item.relative_path} key={item.id}>{item.name}</option>)}</select><button type="button" className="secondary-button" onClick={() => void scanDocument()} disabled={busy || !selectedDocument}>{busy ? 'Scanning…' : 'Scan document'}</button></div> : <p className="intake-empty">No supported document is in this course yet. Import a PDF, DOCX, PPTX, Markdown, or text file first.</p>}
      </div>

      {result && <div className="intake-source-block">
        <div className="intake-source"><p className="eyebrow">Preserved source</p><code>{result.intake.source_path}</code><details className="intake-source-text"><summary>Original text</summary><p>{result.intake.text}</p></details></div>
        {result.warnings.map((warning, index) => <p className="deadline-change-warning soft" key={`${warning}-${index}`}>{warning}</p>)}
        {!result.candidates.length && <p className="intake-empty">No deadline-change candidate was recognized. The source note is preserved; you can still edit the record in History.</p>}
      </div>}

      <div className="intake-results">
        <div className="intake-inbox-heading"><div><p className="eyebrow">Candidate inbox</p><h3>{candidates.length} candidate{candidates.length === 1 ? '' : 's'}</h3></div><span>Preserved sources remain readable in the course inbox.</span></div>
        {!candidates.length && <p className="intake-empty">No intake candidates yet. Paste an announcement above to create one.</p>}
        {candidates.map((candidate) => <IntakeCandidateCard
          key={candidate.id}
          candidate={candidate}
          course={course}
          busy={busy}
          selectedAssessment={selectedAssessments[candidate.id] || ''}
          onSelectAssessment={(assessmentId) => setSelectedAssessments((current) => ({ ...current, [candidate.id]: assessmentId }))}
          onResolve={() => void resolve(candidate)}
          onPrepare={() => void prepare(candidate)}
          onOpen={() => void openProposed(candidate)}
          onDismiss={() => void dismiss(candidate)}
        />)}
      </div>
    </section>
  </div>
}

type CandidateCardProps = {
  candidate: IntakeCandidate
  course: Course
  busy: boolean
  selectedAssessment: string
  onSelectAssessment: (assessmentId: string) => void
  onResolve: () => void
  onPrepare: () => void
  onOpen: () => void
  onDismiss: () => void
}

function IntakeCandidateCard({ candidate, course, busy, selectedAssessment, onSelectAssessment, onResolve, onPrepare, onOpen, onDismiss }: CandidateCardProps) {
  const displayStatus = candidate.display_status || candidate.status
  const actions = ['proposed', 'applied', 'needs_attention', 'reverted']
  const optionList = candidate.available_assessments || []
  return <article className={`intake-candidate status-${displayStatus}`} key={candidate.id}>
    <div className="intake-candidate-heading"><div><span className="intake-status">{statusLabel(displayStatus)}</span><h3>{candidate.entity_title || 'Assessment title not recognized'}</h3></div><strong>{candidate.value ? formatDate(candidate.value) : 'No date'}</strong></div>
    {candidate.source_excerpt && <blockquote>{candidate.source_excerpt}</blockquote>}
    {candidate.warnings.map((warning, index) => <p className="intake-warning" key={`${warning}-${index}`}>{warning.replaceAll('_', ' ')}</p>)}

    {candidate.status === 'resolved' && <div className="intake-candidate-resolution"><p><strong>{String(candidate.resolution.assessment_title || 'Resolved assessment')}</strong>{candidate.resolution.current_due_date ? ` · currently due ${formatDate(String(candidate.resolution.current_due_date))}` : ''}</p><div className="intake-candidate-actions"><button type="button" className="secondary-button" onClick={onDismiss} disabled={busy}>Dismiss</button><button type="button" className="primary-button" onClick={onPrepare} disabled={busy}>{busy ? 'Preparing…' : 'Prepare change review'}</button></div></div>}

    {actions.includes(displayStatus) && <div className="intake-candidate-resolution"><p>{displayStatus === 'proposed' ? 'This candidate has a reviewable ChangeSet.' : displayStatus === 'applied' ? 'The linked ChangeSet is applied and verified.' : displayStatus === 'reverted' ? 'The linked change was reversed.' : 'The linked change needs attention.'}</p><div className="intake-candidate-actions"><button type="button" className="primary-button" onClick={onOpen} disabled={busy}>{displayStatus === 'proposed' ? 'Open change review' : 'Open result'}</button></div></div>}

    {displayStatus === 'cancelled' && <div className="intake-candidate-resolution"><p>The linked review was cancelled. The source note is still preserved.</p><div className="intake-candidate-actions"><button type="button" className="primary-button" onClick={onPrepare} disabled={busy}>Prepare new review</button></div></div>}

    {displayStatus === 'needs_entity' && <div className="intake-candidate-resolution"><p>Choose the exact assessment in {course.code}.</p><div className="intake-candidate-actions"><select value={selectedAssessment} onChange={(event) => onSelectAssessment(event.target.value)}><option value="">Choose assessment…</option>{optionList.map((option) => <option value={option.id} key={option.id}>{option.title}{option.due_date ? ` · due ${formatDate(option.due_date)}` : ''}</option>)}</select><button type="button" className="primary-button" onClick={onResolve} disabled={busy || !selectedAssessment}>Use this assessment</button></div></div>}

    {displayStatus === 'no_change' && <p className="intake-empty">The extracted date already matches the current record.</p>}
    {displayStatus === 'needs_confirmation' && <p className="intake-empty">More than one possible date was found. Edit the announcement or create the change in History.</p>}
    {displayStatus === 'needs_course' && <p className="intake-empty">The course could not be resolved. Reopen intake from the correct course page.</p>}
    {displayStatus === 'rejected' && <p className="intake-empty">This candidate was dismissed. The source note remains preserved.</p>}
  </article>
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    resolved: 'Ready to review',
    proposed: 'Proposed',
    applied: 'Applied',
    reverted: 'Reverted',
    needs_attention: 'Needs attention',
    cancelled: 'Cancelled',
    needs_entity: 'Needs assessment',
    needs_course: 'Needs course',
    needs_confirmation: 'Needs a decision',
    no_change: 'Already matches',
    rejected: 'Dismissed',
    candidate: 'Candidate',
  }
  return labels[status] || status.replaceAll('_', ' ')
}

function formatDate(value: string) {
  const date = new Date(`${value.slice(0, 10)}T12:00:00`)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}
