import { ReviewView } from './ReviewView'
import { isPendingIntakeCandidate } from './lib/intake'
import type { ActivityEvent, Course, IntakeCandidate, ReviewItem, TaskProposalAmendment } from './types'

type ChangesViewProps = {
  reviews: ReviewItem[]
  intakeCandidates: IntakeCandidate[]
  courses: Course[]
  activity: ActivityEvent[]
  busy: boolean
  error: string
  focusId?: string | null
  onFocusConsumed?: () => void
  onDecision: (itemId: string, decision: string) => Promise<void>
  onExecute: (itemId: string) => Promise<void>
  onAmend?: (itemId: string, fields: TaskProposalAmendment) => Promise<void>
  onOpenIntake: (candidate: IntakeCandidate) => void
}

export function ChangesView({ reviews, intakeCandidates, courses, activity, busy, error, focusId, onFocusConsumed, onDecision, onExecute, onAmend, onOpenIntake }: ChangesViewProps) {
  const pendingIntake = intakeCandidates.filter(isPendingIntakeCandidate)
  const openReviews = reviews.filter((item) => item.status === 'open')
  return <div className="page-stack changes-workspace">
    <section className="page-intro"><p className="eyebrow">Attention inbox</p><h2>Changes & approvals</h2><p>Review proposed academic changes, intake candidates, and actions waiting for a decision. Nothing is applied without your approval.</p></section>

    <div className="changes-summary">
      <div><strong>{openReviews.length}</strong><span>review decision{openReviews.length === 1 ? '' : 's'}</span></div>
      <div><strong>{pendingIntake.length}</strong><span>intake candidate{pendingIntake.length === 1 ? '' : 's'}</span></div>
      <div><strong>{reviews.filter((item) => item.status === 'approved' && item.action_proposal_id).length}</strong><span>approved action{reviews.filter((item) => item.status === 'approved' && item.action_proposal_id).length === 1 ? '' : 's'} to execute</span></div>
    </div>

    <section className="changes-intake" aria-label="Intake candidates">
      <div className="review-section-heading"><div><p className="eyebrow">Candidate facts</p><h3>Intake waiting for you</h3></div><span className="review-count-badge">{pendingIntake.length}</span></div>
      {pendingIntake.map((candidate) => <IntakeChangeCard key={candidate.id} candidate={candidate} course={courses.find((course) => course.id === candidate.course_id)} onOpen={() => onOpenIntake(candidate)} />)}
      {!pendingIntake.length && <p className="changes-empty">No intake candidates are waiting. Paste an announcement or scan a document from a course.</p>}
    </section>

    <ReviewView items={reviews} courses={courses} activity={activity} busy={busy} error={error} focusId={focusId} onFocusConsumed={onFocusConsumed} onDecision={onDecision} onExecute={onExecute} onAmend={onAmend} showIntro={false} />
  </div>
}

function IntakeChangeCard({ candidate, course, onOpen }: { candidate: IntakeCandidate; course?: Course; onOpen: () => void }) {
  const status = candidate.display_status || candidate.status
  return <article className={`changes-intake-card status-${status}`}>
    <div className="changes-intake-main"><span className="review-kind">{statusLabel(status)}</span><h3>{candidate.entity_title || 'Assessment to choose'}</h3><p>{course?.name || candidate.course_id || 'Course not resolved'}{candidate.value ? ` · proposed ${formatDate(candidate.value)}` : ''}</p>{candidate.source_excerpt && <blockquote>{candidate.source_excerpt}</blockquote>}</div>
    <button type="button" className="secondary-button" onClick={onOpen}>Open course intake <span>→</span></button>
  </article>
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    resolved: 'Ready to review',
    needs_entity: 'Choose assessment',
    needs_course: 'Choose course',
    needs_confirmation: 'Needs a decision',
    proposed: 'Change proposed',
    needs_attention: 'Needs attention',
    cancelled: 'Cancelled',
  }
  return labels[status] || status.replaceAll('_', ' ')
}

function formatDate(value: string) {
  const date = new Date(`${value.slice(0, 10)}T12:00:00`)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}
