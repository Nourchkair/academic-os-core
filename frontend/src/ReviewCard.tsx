import { useEffect, useState } from 'react'
import type { Course, ReviewItem, TaskProposalAmendment } from './types'

type ReviewCardProps = {
  item: ReviewItem
  courses: Course[]
  busy: boolean
  onDecision: (decision: string) => Promise<void>
  onAmend?: (fields: TaskProposalAmendment) => Promise<void>
}

export function ReviewCard({ item, courses, busy, onDecision, onAmend }: ReviewCardProps) {
  const details = item.details
  const content = (() => {
    switch (item.kind) {
      case 'deadline_conflict': return <DeadlineConflict details={details} onDecision={onDecision} busy={busy} />
      case 'domain_conflict': return <DomainConflict details={details} onDecision={onDecision} busy={busy} />
      case 'source_verification':
      case 'reading_verification':
      case 'source_match': return <SourceVerification details={details} onDecision={onDecision} busy={busy} />
      case 'import_classification': return <ImportClassification details={details} courses={courses} onDecision={onDecision} busy={busy} />
      case 'course_identity_uncertainty': return <CourseUncertainty details={details} courses={courses} onDecision={onDecision} busy={busy} />
      case 'action_approval': return <ActionApproval details={details} courses={courses} onDecision={onDecision} onAmend={onAmend} busy={busy} />
      default: return <GenericReview details={details} onDecision={onDecision} busy={busy} />
    }
  })()

  return <article className="review-card">
    <div className="review-card-heading"><div><span className="review-kind">{labelForKind(item.kind)}</span><h3>{item.title}</h3><p>{item.course || 'Workspace'} · {item.priority} priority</p></div><span className="review-status">Needs your decision</span></div>
    {content}
    <details className="advanced-details"><summary>Advanced details</summary><pre>{JSON.stringify(details, null, 2)}</pre></details>
  </article>
}

function DeadlineConflict({ details, onDecision, busy }: DecisionProps) {
  const current = value(details, 'current', 'current_value', 'saved', 'saved_deadline')
  const next = value(details, 'new', 'new_value', 'proposed', 'new_deadline')
  const source = value(details, 'source', 'evidence', 'source_title') || 'Recorded academic evidence'
  const confidence = value(details, 'confidence') || 'unverified'
  return <div className="typed-review-content"><p className="review-question">Academia found two supported deadline values. Which one should remain saved?</p><div className="comparison-grid"><ComparisonCell label="Currently saved" value={current || 'Unknown'} /><ComparisonCell label="New evidence" value={next || 'Unknown'} emphasis /></div><EvidenceLine source={source} confidence={confidence} /><div className="decision-row"><button className="secondary-button" disabled={busy} onClick={() => void onDecision('keep_current')}>Keep {current || 'current date'}</button><button className="primary-button" disabled={busy} onClick={() => void onDecision('use_new')}>Use {next || 'new date'}</button></div><EffectNote text="Only the selected value will be proposed as the saved deadline. The original evidence remains preserved." /></div>
}

function DomainConflict({ details, onDecision, busy }: DecisionProps) {
  const field = humanize(value(details, 'field') || 'domain field')
  const current = value(details, 'current', 'before')
  const next = value(details, 'new', 'after')
  const source = value(details, 'source') || 'Recorded academic evidence'
  const confidence = value(details, 'confidence') || 'unverified'
  return <div className="typed-review-content"><p className="review-question">A new syllabus value conflicts with the saved {field.toLowerCase()}. Choose which value should remain in derived state.</p><div className="comparison-grid"><ComparisonCell label="Currently saved" value={current || 'Unknown'} /><ComparisonCell label="New evidence" value={next || 'Unknown'} emphasis /></div><EvidenceLine source={source} confidence={confidence} /><div className="decision-row"><button className="secondary-button" disabled={busy} onClick={() => void onDecision('keep_current')}>Keep {current || 'current value'}</button><button className="primary-button" disabled={busy} onClick={() => void onDecision('use_new')}>Use {next || 'new value'}</button></div><EffectNote text="The selected value is the only one proposed for the derived projection. Source files and both evidence records remain preserved." /></div>
}

function SourceVerification({ details, onDecision, busy }: DecisionProps) {
  const requested = record(details.requested) || record(details.expected) || {}
  const retrieved = record(details.retrieved) || record(details.actual) || {}
  const result = value(details, 'verification_result', 'result') || 'NOT RETRIEVED'
  const keys = Array.from(new Set([...Object.keys(requested), ...Object.keys(retrieved)])).filter((key) => key !== 'source_path')
  return <div className="typed-review-content"><p className="review-question">Compare the requested source against what was retrieved. Differing fields are highlighted.</p><div className="metadata-table"><div className="metadata-header"><strong>Requested</strong><strong>Retrieved</strong></div>{keys.map((key) => <div className={`metadata-row ${requested[key] !== undefined && retrieved[key] !== undefined && String(requested[key]).toLowerCase() !== String(retrieved[key]).toLowerCase() ? 'differs' : ''}`} key={key}><span>{humanize(key)}</span><span>{formatValue(requested[key])}</span><span>{formatValue(retrieved[key])}</span></div>)}</div><div className={`verification-badge ${verificationClass(result)}`}>{result}</div><div className="decision-row"><button className="primary-button" disabled={busy} onClick={() => void onDecision('accept_match')}>Keep this verification</button><button className="quiet-button" disabled={busy} onClick={() => void onDecision('keep_unverified')}>Keep unverified</button></div></div>
}

function ImportClassification({ details, courses, onDecision, busy }: DecisionProps & { courses: Course[] }) {
  const [selected, setSelected] = useState('')
  const filename = basename(value(details, 'filename', 'original_file') || 'Imported material')
  const proposedCourse = value(details, 'proposed_course', 'course')
  const proposedCategory = value(details, 'proposed_category', 'category') || 'Unknown'
  const proposedDestination = value(details, 'proposed_destination', 'destination') || 'General intake'
  const evidence = value(details, 'reason', 'evidence') || 'No reliable classification evidence was recorded.'
  const confidence = value(details, 'confidence') || 'unverified'
  return <div className="typed-review-content"><p className="review-question">Academia needs your help deciding where this copied file belongs. The original remains untouched.</p><div className="classification-grid"><InfoField label="Filename" value={filename} /><InfoField label="Proposed course" value={proposedCourse || 'Not identified'} /><InfoField label="Proposed category" value={proposedCategory} /><InfoField label="Proposed destination" value={proposedDestination} /><InfoField label="Evidence" value={evidence} /><InfoField label="Confidence" value={confidence} /></div><label className="setup-field"><span>Correct the course if needed</span><select value={selected} onChange={(event) => setSelected(event.target.value)}><option value="">Choose a course</option>{courses.map((course) => <option value={course.id} key={course.id}>{course.code} · {course.name}</option>)}</select></label><div className="decision-row"><button className="secondary-button" disabled={busy} onClick={() => void onDecision('keep_general_intake')}>Keep in general intake</button>{proposedCourse && <button className="secondary-button" disabled={busy} onClick={() => void onDecision('use_proposed_destination')}>Use proposed destination</button>}{selected && <button className="primary-button" disabled={busy} onClick={() => void onDecision(`choose_course:${selected}`)}>Save selected course</button>}</div><EffectNote text="This records your classification decision. Any later move remains a separate, visible action and never overwrites the original." /></div>
}

function CourseUncertainty({ details, courses, onDecision, busy }: DecisionProps & { courses: Course[] }) {
  const candidates = Array.isArray(details.candidates) ? details.candidates : []
  const [selected, setSelected] = useState('')
  const detected = value(details, 'detected_course_code', 'detected_course_title')
  const supplied = value(details, 'supplied_course')
  return <div className="typed-review-content"><p className="review-question">{detected ? 'The syllabus identity does not match the supplied course. Choose the correct context before extracting facts.' : 'Academia found more than one possible course. Choose one only if the evidence is clear.'}</p>{detected && <div className="classification-grid"><InfoField label="Detected in syllabus" value={detected} /><InfoField label="Supplied context" value={supplied || 'Unknown'} /><InfoField label="Source" value={value(details, 'source') || 'Unknown'} /><InfoField label="Confidence" value={value(details, 'confidence') || 'unverified'} /></div>}{candidates.length > 0 && <div className="candidate-review-list">{candidates.map((candidate, index) => { const item = record(candidate) || {}; const id = value(item, 'id', 'course_id') || courses[index]?.id || ''; return <label key={id || index} className="candidate-review"><input type="radio" name={`candidate-${String(details.id || 'course')}`} value={id} checked={selected === id} onChange={() => setSelected(id)} /><span><strong>{value(item, 'name', 'label') || 'Candidate course'}</strong><small>{value(item, 'reason', 'evidence') || 'No reason recorded'}</small></span></label> })}</div>}{detected && <label className="setup-field"><span>Correct course context</span><select value={selected} onChange={(event) => setSelected(event.target.value)}><option value="">Choose a course</option>{courses.map((course) => <option value={course.id} key={course.id}>{course.code} · {course.name}</option>)}</select></label>}<div className="decision-row"><button className="quiet-button" disabled={busy} onClick={() => void onDecision('keep_unassigned')}>Keep unassigned</button>{selected && <button className="primary-button" disabled={busy} onClick={() => void onDecision(`choose_course:${selected}`)}>{detected ? 'Record course correction' : 'Use selected course'}</button>}</div>{detected && <EffectNote text="Recording a course correction does not rerun extraction automatically. Re-run the syllabus preview with the corrected course context." />}</div>
}

function ActionApproval({ details, courses, onDecision, onAmend, busy }: DecisionProps & { courses: Course[]; onAmend?: (fields: TaskProposalAmendment) => Promise<void> }) {
  const proposal = record(details.proposal_details) || details
  const actionType = value(proposal, 'action_type') || value(details, 'action_type') || 'change'
  const before = value(proposal, 'before', 'current')
  const after = value(proposal, 'after', 'new', 'proposed')
  const failure = value(details, 'failure_reason', 'last_failure_reason')
  const effects = Array.isArray(proposal.effects) ? proposal.effects : []
  if (actionType === 'task_change') {
    return <TaskActionApproval proposal={proposal} before={before} after={after} effects={effects} courses={courses} onDecision={onDecision} onAmend={onAmend} busy={busy} />
  }
  const approveLabel = actionType.includes('calendar') ? 'Approve calendar change' : actionType.includes('file_move') ? 'Approve file move' : actionType.includes('configuration') ? 'Apply this setting' : 'Approve this change'
  const keepLabel = actionType.includes('calendar') ? 'Keep calendar unchanged' : actionType.includes('file_move') ? 'Keep files where they are' : 'Keep current data'
  return <div className="typed-review-content"><p className="review-question">This action is waiting for your approval. Nothing external happens from this screen alone.</p>{failure && <p className="setup-error" role="status">The previous execution failed: {failure}. A new approval is required before retrying.</p>}{before || after ? <div className="comparison-grid"><ComparisonCell label="Before" value={before || 'Unknown'} /><ComparisonCell label="After" value={after || 'Unknown'} emphasis /></div> : null}<div className="effect-list"><strong>This action will:</strong>{effects.length ? <ul>{effects.map((effect) => <li key={String(effect)}>{String(effect)}</li>)}</ul> : <ul><li>record your decision</li><li>preserve the previous source and activity history</li><li>wait for the approved action to be executed and verified</li></ul>}</div><div className="decision-row"><button className="secondary-button" disabled={busy} onClick={() => void onDecision('reject_action')}>{keepLabel}</button><button className="primary-button" disabled={busy} onClick={() => void onDecision('approve_action')}>{approveLabel}</button></div></div>
}

function TaskActionApproval({ proposal, before, after, effects, courses, onDecision, onAmend, busy }: {
  proposal: Record<string, unknown>
  before: string
  after: string
  effects: unknown[]
  courses: Course[]
  onDecision: (decision: string) => Promise<void>
  onAmend?: (fields: TaskProposalAmendment) => Promise<void>
  busy: boolean
}) {
  const task = record(proposal.task_after) || {}
  const initialTitle = value(task, 'title')
  const initialCourse = value(task, 'course_id')
  const initialDueDate = value(task, 'due_date')
  const initialDueTime = value(task, 'due_time')
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(initialTitle)
  const [courseId, setCourseId] = useState(initialCourse)
  const [dueDate, setDueDate] = useState(initialDueDate)
  const [dueTime, setDueTime] = useState(initialDueTime)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    if (editing) return
    setTitle(initialTitle)
    setCourseId(initialCourse)
    setDueDate(initialDueDate)
    setDueTime(initialDueTime)
  }, [initialTitle, initialCourse, initialDueDate, initialDueTime, editing])
  const save = async () => {
    if (!onAmend || !title.trim() || saving) return
    setSaving(true)
    setError('')
    try {
      await onAmend({ title: title.trim(), course_id: courseId || null, due_date: dueDate || null, due_time: dueDate && dueTime ? dueTime : null })
      setEditing(false)
    } catch (reason) {
      setError(`Could not update this proposal. ${String(reason)}`)
    } finally {
      setSaving(false)
    }
  }
  const approveLabel = value(proposal, 'action') === 'create' ? 'Add this task' : 'Apply task update'
  return <div className="typed-review-content">
    <p className="review-question">This personal-task proposal is waiting for your decision. You can edit the exact fields before approving it.</p>
    <div className="comparison-grid"><ComparisonCell label="Before" value={before || 'No personal task'} /><ComparisonCell label="After" value={after || 'Task proposal'} emphasis /></div>
    <div className="effect-list"><strong>This action will:</strong>{effects.length ? <ul>{effects.map((effect) => <li key={String(effect)}>{String(effect)}</li>)}</ul> : <ul><li>write only the approved personal task</li><li>preserve other tasks and unrelated Markdown</li><li>record the change in Activity</li></ul>}</div>
    {onAmend && <div className="task-proposal-edit-row"><button type="button" className="secondary-button" disabled={busy || saving} onClick={() => setEditing((current) => !current)}>{editing ? 'Close editor' : 'Edit proposal'}</button></div>}
    {editing && <div className="coursework-editor task-proposal-editor">
      <div className="coursework-editor-grid">
        <label className="history-title-field"><span>Task</span><input value={title} onChange={(event) => setTitle(event.target.value)} maxLength={300} /></label>
        <label><span>Course <small>Optional</small></span><select value={courseId} onChange={(event) => setCourseId(event.target.value)}><option value="">Semester-wide</option>{courses.map((course) => <option value={course.id} key={course.id}>{course.code} · {course.name}</option>)}</select></label>
        <label><span>Due date <small>Optional</small></span><input type="date" value={dueDate} onChange={(event) => { setDueDate(event.target.value); if (!event.target.value) setDueTime('') }} /></label>
        <label><span>Due time <small>Optional</small></span><input type="time" value={dueTime} onChange={(event) => setDueTime(event.target.value)} disabled={!dueDate} /></label>
      </div>
      {error && <p className="task-grade-error" role="alert">{error}</p>}
      <div className="coursework-editor-actions">
        <button type="button" className="secondary-button" onClick={() => setEditing(false)} disabled={saving}>Cancel</button>
        <button type="button" className="primary-button" onClick={() => void save()} disabled={saving || !title.trim() || !(dueDate || !dueTime)}>{saving ? 'Saving…' : 'Save proposal'}</button>
      </div>
    </div>}
    {!editing && error && <p className="task-grade-error" role="alert">{error}</p>}
    <div className="decision-row"><button className="secondary-button" disabled={busy || saving} onClick={() => void onDecision('reject_action')}>Keep task unchanged</button><button className="primary-button" disabled={busy || saving} onClick={() => void onDecision('approve_action')}>{approveLabel}</button></div>
  </div>
}

function GenericReview({ details, onDecision, busy }: DecisionProps) {
  const entries = Object.entries(details).filter(([key]) => !['proposal_details'].includes(key))
  return <div className="typed-review-content"><p className="review-question">Academia needs a human decision because the evidence is incomplete or an action requires approval.</p><div className="human-details">{entries.slice(0, 6).map(([key, item]) => <InfoField key={key} label={humanize(key)} value={formatValue(item)} />)}</div><div className="decision-row"><button className="secondary-button" disabled={busy} onClick={() => void onDecision('dismiss')}>Dismiss this item</button><button className="primary-button" disabled={busy} onClick={() => void onDecision('confirm')}>Confirm this information</button></div></div>
}

type DecisionProps = { details: Record<string, unknown>; busy: boolean; onDecision: (decision: string) => Promise<void> }

function ComparisonCell({ label, value: item, emphasis = false }: { label: string; value: string; emphasis?: boolean }) { return <div className={`comparison-cell ${emphasis ? 'emphasis' : ''}`}><span>{label}</span><strong>{item}</strong></div> }
function EvidenceLine({ source, confidence }: { source: string; confidence: string }) { return <div className="evidence-line"><span>Source · {source}</span><b>{confidence}</b></div> }
function EffectNote({ text }: { text: string }) { return <p className="effect-note">{text}</p> }
function InfoField({ label, value: item }: { label: string; value: string }) { return <div className="info-field"><span>{label}</span><strong>{item}</strong></div> }
function record(valueToRead: unknown): Record<string, unknown> | null { return valueToRead && typeof valueToRead === 'object' && !Array.isArray(valueToRead) ? valueToRead as Record<string, unknown> : null }
function value(details: Record<string, unknown>, ...keys: string[]): string { for (const key of keys) { const item = details[key]; if (item !== undefined && item !== null && String(item).trim()) return String(item) } return '' }
function formatValue(item: unknown): string { if (item === undefined || item === null || item === '') return 'Unknown / not retrieved'; if (typeof item === 'object') return JSON.stringify(item); return String(item) }
function humanize(key: string): string { return key.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase()) }
function basename(path: string): string { return path.split(/[\\/]/).pop() || path }
function verificationClass(result: string): string { const valueToRead = result.toLowerCase(); return valueToRead.includes('exact') ? 'exact' : valueToRead.includes('probable') ? 'probable' : valueToRead.includes('mismatch') ? 'mismatch' : 'not-retrieved' }
function labelForKind(kind: string): string { return ({ deadline_conflict: 'Deadline conflict', source_verification: 'Source verification', reading_verification: 'Reading verification', source_match: 'Source verification', import_classification: 'Imported file', course_identity_uncertainty: 'Course identity', action_approval: 'Action approval' } as Record<string, string>)[kind] || humanize(kind) }
