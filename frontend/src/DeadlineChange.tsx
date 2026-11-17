import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from './lib/api'
import type { ChangeOperation, ChangeSet, Course, CourseworkHistoryRecord, KnowledgeTaskLink, Task } from './types'

type SourceKind = 'student_report' | 'professor_announcement'

type DeadlineChangeProps = {
  course: Course
  semester: string
  record: CourseworkHistoryRecord
  initialChangeset?: ChangeSet
  onClose: () => void
  onChanged: () => Promise<void>
}

export function DeadlineChangeDialog({ course, semester, record, initialChangeset, onClose, onChanged }: DeadlineChangeProps) {
  const [step, setStep] = useState<'form' | 'preview' | 'result'>(initialChangeset ? 'preview' : 'form')
  const [newDate, setNewDate] = useState('')
  const [sourceKind, setSourceKind] = useState<SourceKind>('student_report')
  const [sourceLabel, setSourceLabel] = useState('')
  const [note, setNote] = useState('')
  const [tasks, setTasks] = useState<Task[]>([])
  const [links, setLinks] = useState<KnowledgeTaskLink[]>([])
  const [candidateTaskIds, setCandidateTaskIds] = useState<string[]>([])
  const [newLinkIds, setNewLinkIds] = useState<string[]>([])
  const [changeset, setChangeset] = useState<ChangeSet | null>(initialChangeset ?? null)
  const [selectedOperationIds, setSelectedOperationIds] = useState<string[]>(initialChangeset ? initialChangeset.operations.filter((operation) => operation.required || operation.default_selected).map((operation) => operation.id) : [])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const assessmentId = `assessment:history:${record.id}`
  const initialAssessmentOperation = initialChangeset?.operations.find((operation) => operation.type === 'assessment.set_deadline')
  const currentDueDate = record.due_date ?? initialAssessmentOperation?.before ?? ''

  useEffect(() => {
    if (initialChangeset) return
    let active = true
    void Promise.all([api.tasks(semester), api.knowledgeLinks(course.id, semester)])
      .then(([taskPayload, linkPayload]) => {
        if (!active) return
        const existing = linkPayload.links.filter((link) => link.assessment_id === assessmentId && link.status === 'active')
        setLinks(existing)
        setTasks(taskPayload.tasks.filter((task) => task.user_task && (task.course === course.id || task.course === course.code) && task.due_date === currentDueDate && task.status !== 'done' && task.status !== 'cancelled'))
      })
      .catch((reason) => { if (active) setError(String(reason)) })
    return () => { active = false }
  }, [assessmentId, course.code, course.id, currentDueDate, initialChangeset, semester])

  const alreadyLinkedTaskIds = useMemo(() => new Set(links.map((link) => link.task_id)), [links])
  const candidateTasks = tasks.filter((task) => !alreadyLinkedTaskIds.has(task.task_id || task.id))
  const linkedTasks = tasks.filter((task) => alreadyLinkedTaskIds.has(task.task_id || task.id))
  const requiredOperations = changeset?.operations.filter((operation) => operation.required) ?? []
  const optionalOperations = changeset?.operations.filter((operation) => !operation.required) ?? []
  const reversible = changeset ? changeset.operations.every((operation) => operation.reversible || operation.status === 'skipped' || operation.status === 'reversed' || operation.status === 'already_reversed') : false
  const canRetry = Boolean(changeset && ['partially_applied', 'failed'].includes(changeset.status) && changeset.result.operation_results.some((operation) => ['failed', 'blocked'].includes(operation.status) && operation.error !== 'retry limit reached'))
  const selectedOptionalCount = optionalOperations.filter((operation) => selectedOperationIds.includes(operation.id)).length
  const skippedOptionalCount = optionalOperations.length - selectedOptionalCount
  const assessmentOperation = changeset?.operations.find((operation) => operation.type === 'assessment.set_deadline')
  const assessmentApplied = Boolean(changeset && ['verified', 'partially_applied'].includes(changeset.status) && assessmentOperation?.status === 'verified')
  const headerDue = assessmentApplied ? assessmentOperation?.after || currentDueDate : currentDueDate
  const headerDueLabel = assessmentApplied ? 'Now due' : 'Recorded due'

  const toggleCandidate = (taskId: string) => {
    setCandidateTaskIds((current) => current.includes(taskId) ? current.filter((item) => item !== taskId) : [...current, taskId])
  }

  const toggleOperation = (operation: ChangeOperation) => {
    if (operation.required) return
    setSelectedOperationIds((current) => current.includes(operation.id) ? current.filter((item) => item !== operation.id) : [...current, operation.id])
  }

  const preview = async () => {
    if (!newDate) { setError('Choose the new deadline first.'); return }
    if (newDate === currentDueDate) { setError('The new deadline is the same as the recorded deadline.'); return }
    setBusy(true); setError(null)
    const createdLinks: string[] = []
    try {
      for (const taskId of candidateTaskIds) {
        const link = await api.linkTaskToAssessment({ courseId: course.id, semester, assessmentId, taskId, mode: 'mirror_deadline' })
        createdLinks.push(link.id)
      }
      setNewLinkIds(createdLinks)
      const value = await api.proposeDeadlineChange({ courseId: course.id, semester, assessmentId, newDate, sourceKind, sourceLabel: sourceLabel.trim() || undefined, note: note.trim() || undefined })
      setChangeset(value)
      setSelectedOperationIds(value.operations.filter((operation) => operation.required || operation.default_selected).map((operation) => operation.id))
      setStep('preview')
    } catch (reason) {
      for (const linkId of createdLinks) {
        try { await api.pauseTaskLink(linkId, semester) } catch { /* preserve the original error */ }
      }
      setError(String(reason))
    } finally {
      setBusy(false)
    }
  }

  const approveAndApply = async () => {
    if (!changeset) return
    setBusy(true); setError(null)
    try {
      const approved = changeset.status === 'approved' ? changeset : await api.approveChangeSet(changeset.id, semester, selectedOperationIds)
      setChangeset(approved)
      const value = await api.executeChangeSet(changeset.id, semester)
      setChangeset(value)
      setStep('result')
      await onChanged()
    } catch (reason) {
      setError(String(reason))
    } finally {
      setBusy(false)
    }
  }

  const retry = async () => {
    if (!changeset) return
    setBusy(true); setError(null)
    try {
      const value = await api.retryChangeSet(changeset.id, semester)
      setChangeset(value)
      await onChanged()
    } catch (reason) {
      setError(String(reason))
    } finally {
      setBusy(false)
    }
  }

  const undo = async () => {
    if (!changeset) return
    setBusy(true); setError(null)
    try {
      const value = await api.reverseChangeSet(changeset.id, semester)
      setChangeset(value)
      await onChanged()
    } catch (reason) {
      setError(String(reason))
    } finally {
      setBusy(false)
    }
  }

  const cancel = useCallback(async () => {
    if (changeset && ['proposed', 'approved'].includes(changeset.status)) {
      try { await api.cancelChangeSet(changeset.id, semester) } catch { /* the dialog can still close */ }
    }
    const executed = Boolean(changeset && ['verified', 'partially_applied', 'failed', 'reverted', 'partially_reverted', 'reversal_conflict'].includes(changeset.status))
    if (!executed) {
      for (const linkId of newLinkIds) {
        try { await api.pauseTaskLink(linkId, semester) } catch { /* link may already be paused */ }
      }
    }
    onClose()
  }, [changeset, newLinkIds, onClose, semester])

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    return () => { previous?.focus() }
  }, [])

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) {
        event.preventDefault()
        void cancel()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [busy, cancel])

  return <div className="deadline-change-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) void cancel() }}>
    <section className="deadline-change-dialog" role="dialog" aria-modal="true" aria-labelledby="deadline-change-title">
      <header className="deadline-change-heading">
        <div><p className="eyebrow">Academic change preview</p><h2 id="deadline-change-title">{record.title}</h2><p>{headerDue ? `${headerDueLabel} ${formatDate(headerDue)}` : 'No recorded deadline'}</p></div>
        <button className="icon-button" type="button" aria-label="Close change preview" onClick={() => void cancel()} disabled={busy}>×</button>
      </header>

      {error && <p className="setup-error" role="alert">{error}</p>}

      {step === 'form' && <div className="deadline-change-form">
        <label><span>New deadline</span><input type="date" value={newDate} autoFocus onChange={(event) => setNewDate(event.target.value)} /></label>
        <label><span>Where did this come from?</span><select value={sourceKind} onChange={(event) => setSourceKind(event.target.value as SourceKind)}><option value="student_report">Student report</option><option value="professor_announcement">Professor announcement</option></select></label>
        <label><span>Reference <small>(optional)</small></span><input value={sourceLabel} onChange={(event) => setSourceLabel(event.target.value)} maxLength={200} placeholder="e.g. Announcement in class" /></label>
        <label className="deadline-change-wide"><span>Note <small>(optional)</small></span><textarea value={note} onChange={(event) => setNote(event.target.value)} rows={2} maxLength={1000} placeholder="What exactly changed?" /></label>

        <section className="deadline-change-links">
          <h3>Tasks with the same deadline</h3>
          {linkedTasks.length > 0 && <p className="deadline-change-hint">These tasks already mirror this deadline and will move with it.</p>}
          {linkedTasks.map((task) => <div className="deadline-change-task linked" key={task.task_id || task.id}><span>✓</span><div><strong>{task.title}</strong><small>Already linked · moves with the assessment</small></div></div>)}
          {candidateTasks.length > 0 ? <>
            <p className="deadline-change-hint">Choose any task that should stay synchronized. Unlinked tasks are not changed.</p>
            {candidateTasks.map((task) => <label className="deadline-change-task" key={task.task_id || task.id}><input type="checkbox" checked={candidateTaskIds.includes(task.task_id || task.id)} onChange={() => toggleCandidate(task.task_id || task.id)} /><div><strong>{task.title}</strong><small>{task.due_date ? `Due ${formatDate(task.due_date)}` : 'No due date'} · link and move with this change</small></div></label>)}
          </> : linkedTasks.length === 0 && <p className="deadline-change-hint">No open course tasks currently share this deadline. The assessment will still change.</p>}
        </section>

        <div className="deadline-change-actions"><button type="button" className="secondary-button" onClick={() => void cancel()} disabled={busy}>Cancel</button><button type="button" className="primary-button" onClick={() => void preview()} disabled={busy || !newDate}>{busy ? 'Preparing…' : 'Preview change'}</button></div>
      </div>}

      {step === 'preview' && changeset && <div className="deadline-change-preview">
        <div className="deadline-change-summary"><p className="eyebrow">Review before applying</p><h3>{changeset.title}</h3><p>{changeset.summary}</p><p className="deadline-change-selection-summary">Selected: the required assessment deadline{selectedOptionalCount ? ` plus ${selectedOptionalCount} mirrored task${selectedOptionalCount === 1 ? '' : 's'}` : ''}.{skippedOptionalCount ? ` ${skippedOptionalCount} mirrored task${skippedOptionalCount === 1 ? '' : 's'} will be skipped and the link paused.` : ''}</p></div>
        <div className="deadline-change-operation-list">
          {requiredOperations.map((operation) => <div className="deadline-change-operation required" key={operation.id}><div><span className="deadline-change-required">Required</span><strong>{operation.label || operation.type}</strong><small>{operation.target_title}</small></div><div className="deadline-change-values"><b>{formatValue(operation.before)}</b><span>→</span><b>{formatValue(operation.after)}</b></div></div>)}
          {optionalOperations.map((operation) => <label className="deadline-change-operation" key={operation.id}><input type="checkbox" checked={selectedOperationIds.includes(operation.id)} disabled={busy || changeset.status === 'approved'} onChange={() => toggleOperation(operation)} /><div><span className="deadline-change-optional">Optional</span><strong>{operation.label || operation.type}</strong><small>{operation.target_title}{operation.skip_effect === 'pause_link' ? ' · if skipped, this link pauses' : ''}</small></div><div className="deadline-change-values"><b>{formatValue(operation.before)}</b><span>→</span><b>{formatValue(operation.after)}</b></div></label>)}
        </div>
        <section className="deadline-change-evidence"><h4>Evidence</h4>{changeset.evidence?.length ? changeset.evidence.map((item) => <div className="deadline-change-evidence-row" key={String(item.id)}><strong>{String(item.source || 'Student report')}</strong><span>{String(item.source_kind || 'student_report').replaceAll('_', ' ')} · {String(item.verification || 'unverified')}</span>{item.excerpt ? <p>{String(item.excerpt)}</p> : null}</div>) : <p className="deadline-change-hint">Student report · unverified</p>}</section>
        {changeset.conflicts.map((conflict, index) => <div className="deadline-change-warning" key={String(conflict.id || index)}>{String(conflict.why || 'The proposed value differs from the recorded value.')}</div>)}
        {changeset.warnings.map((warning, index) => <div className="deadline-change-warning soft" key={`${warning}-${index}`}>{warning}</div>)}
        <p className="deadline-change-hint">Approval authorizes this local change. It does not make a student report a verified fact.</p>
        <div className="deadline-change-actions"><button type="button" className="secondary-button" onClick={() => void cancel()} disabled={busy}>Cancel</button><button type="button" className="primary-button" onClick={() => void approveAndApply()} disabled={busy || !selectedOperationIds.length}>{busy ? 'Applying…' : changeset.status === 'approved' ? 'Apply approved change' : 'Approve selected and apply'}</button></div>
      </div>}

      {step === 'result' && changeset && <div className="deadline-change-result">
        <div className={`deadline-change-result-banner status-${changeset.status}`}><p className="eyebrow">Result</p><h3>{resultTitle(changeset.status)}</h3><p>{resultMessage(changeset)}</p></div>
        <div className="deadline-change-operation-list">{changeset.result.operation_results.map((operation) => {
          return <div className={`deadline-change-operation result-${operation.status}`} key={operation.operation_id}>
            <div><strong>{operation.label || operation.type}</strong><small>{operation.target_title}</small>{operation.status === 'skipped' && operation.skip_effect_applied && <small className="deadline-change-link-state">Deadline link paused. The task stays independent until you link it again.</small>}</div>
            <div className="deadline-change-values"><b>{formatValue(operation.before)}</b><span>→</span><b>{formatValue(operation.after)}</b><em>{operation.status.replaceAll('_', ' ')}</em></div>
            {operation.error && <p className="deadline-change-error">{operation.error}</p>}
            {operation.projection_results?.some((projection) => !['verified', 'already_synced'].includes(String(projection.status))) && <p className="deadline-change-warning soft">An extracted source projection was left unchanged so its disagreement stays visible.</p>}
          </div>
        })}</div>
        {changeset.status === 'verified' && <p className="deadline-change-hint">Every approved operation was read back and verified. The evidence remains unverified until a source confirms it.</p>}
        {changeset.result.operation_results.some((operation) => operation.status === 'conflict') && <p className="deadline-change-warning">A record changed after this preview was created. Nothing was overwritten. Close this dialog and start a new change preview to use the current value.</p>}
        {canRetry && <button type="button" className="secondary-button" onClick={() => void retry()} disabled={busy}>{busy ? 'Retrying…' : 'Retry failed operations'}</button>}
        <div className="deadline-change-actions">{reversible && ['verified', 'partially_applied'].includes(changeset.status) && <button type="button" className="secondary-button" onClick={() => void undo()} disabled={busy}>{busy ? 'Please wait…' : 'Undo this change'}</button>}<button type="button" className="primary-button" onClick={() => void cancel()} disabled={busy}>Done</button></div>
      </div>}
    </section>
  </div>
}

function formatValue(value: string | null) { return value ? formatDate(value) : 'Not recorded' }
function formatDate(value: string) { const date = new Date(`${value.slice(0, 10)}T12:00:00`); return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) }
function resultTitle(status: string) { if (status === 'verified') return 'Change applied and verified'; if (status === 'partially_applied') return 'Part of the change needs attention'; if (status === 'failed') return 'No changes were applied'; if (status === 'reverted') return 'Change reversed'; if (status === 'partially_reverted') return 'Part of the change was reversed'; if (status === 'reversal_conflict') return 'Reversal needs review'; return status.replaceAll('_', ' ') }
function resultMessage(changeset: ChangeSet) { const failed = changeset.result.operation_results.filter((operation) => ['failed', 'blocked', 'conflict'].includes(operation.status)).length; const verified = changeset.result.operation_results.filter((operation) => operation.status === 'verified').length; const skipped = changeset.result.operation_results.filter((operation) => operation.status === 'skipped').length; if (changeset.status === 'verified') return `${verified} operation${verified === 1 ? '' : 's'} verified${skipped ? `, ${skipped} skipped` : ''}. Activity was recorded.`; if (changeset.status === 'reverted') return 'The reversible changes were restored. The original execution remains in the audit trail.'; if (changeset.status === 'partially_reverted') return 'The reversible changes were restored. A failed or irreversible operation remains for review.'; if (changeset.status === 'reversal_conflict') return 'A later edit changed one of these records, so the reversal stopped without overwriting it.'; if (failed) return `${verified} verified · ${failed} needing attention${skipped ? ` · ${skipped} skipped` : ''}.`; return changeset.result.summary || 'Review the operation results below.' }
