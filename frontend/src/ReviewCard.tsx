import { useState } from 'react'
import type { Course, ReviewItem } from './types'

type ReviewCardProps = {
  item: ReviewItem
  courses: Course[]
  busy: boolean
  onDecision: (decision: string) => Promise<void>
}

export function ReviewCard({ item, courses, busy, onDecision }: ReviewCardProps) {
  const details = item.details
  const content = (() => {
    switch (item.kind) {
      case 'deadline_conflict': return <DeadlineConflict details={details} onDecision={onDecision} busy={busy} />
      case 'source_verification':
      case 'reading_verification':
      case 'source_match': return <SourceVerification details={details} onDecision={onDecision} busy={busy} />
      case 'import_classification': return <ImportClassification details={details} courses={courses} onDecision={onDecision} busy={busy} />
      case 'course_identity_uncertainty': return <CourseUncertainty details={details} courses={courses} onDecision={onDecision} busy={busy} />
      case 'action_approval': return <ActionApproval details={details} onDecision={onDecision} busy={busy} />
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
  return <div className="typed-review-content"><p className="review-question">Academia found more than one possible course. Choose one only if the evidence is clear.</p><div className="candidate-review-list">{candidates.map((candidate, index) => { const item = record(candidate) || {}; const id = value(item, 'id', 'course_id') || courses[index]?.id || ''; return <label key={id || index} className="candidate-review"><input type="radio" name={`candidate-${String(details.id || 'course')}`} value={id} checked={selected === id} onChange={() => setSelected(id)} /><span><strong>{value(item, 'name', 'label') || 'Candidate course'}</strong><small>{value(item, 'reason', 'evidence') || 'No reason recorded'}</small></span></label> })}</div><div className="decision-row"><button className="quiet-button" disabled={busy} onClick={() => void onDecision('keep_unassigned')}>Keep unassigned</button>{selected && <button className="primary-button" disabled={busy} onClick={() => void onDecision(`choose_course:${selected}`)}>Use selected course</button>}</div></div>
}

function ActionApproval({ details, onDecision, busy }: DecisionProps) {
  const proposal = record(details.proposal_details) || details
  const actionType = value(proposal, 'action_type') || value(details, 'action_type') || 'change'
  const before = value(proposal, 'before', 'current')
  const after = value(proposal, 'after', 'new', 'proposed')
  const effects = Array.isArray(proposal.effects) ? proposal.effects : []
  const approveLabel = actionType.includes('calendar') ? 'Approve calendar change' : actionType.includes('file_move') ? 'Approve file move' : actionType.includes('configuration') ? 'Apply this setting' : 'Approve this change'
  const keepLabel = actionType.includes('calendar') ? 'Keep calendar unchanged' : actionType.includes('file_move') ? 'Keep files where they are' : 'Keep current data'
  return <div className="typed-review-content"><p className="review-question">This action is waiting for your approval. Nothing external happens from this screen alone.</p>{before || after ? <div className="comparison-grid"><ComparisonCell label="Before" value={before || 'Unknown'} /><ComparisonCell label="After" value={after || 'Unknown'} emphasis /></div> : null}<div className="effect-list"><strong>This action will:</strong>{effects.length ? <ul>{effects.map((effect) => <li key={String(effect)}>{String(effect)}</li>)}</ul> : <ul><li>record your decision</li><li>preserve the previous source and activity history</li><li>wait for the approved action to be executed and verified</li></ul>}</div><div className="decision-row"><button className="secondary-button" disabled={busy} onClick={() => void onDecision('reject_action')}>{keepLabel}</button><button className="primary-button" disabled={busy} onClick={() => void onDecision('approve_action')}>{approveLabel}</button></div></div>
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
