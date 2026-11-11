import { ReviewCard } from './ReviewCard'
import type { ActivityEvent, Course, ReviewItem } from './types'

type ReviewViewProps = {
  items: ReviewItem[]
  courses: Course[]
  activity: ActivityEvent[]
  busy: boolean
  error: string
  onDecision: (itemId: string, decision: string) => Promise<void>
  onExecute: (itemId: string) => Promise<void>
}

const actionLabels: Record<string, string> = {
  file_copy: 'File import',
  file_move: 'File move',
  domain_change: 'Academic record change',
  calendar_change: 'Calendar change',
  configuration_change: 'Settings change',
}

export function ReviewView({ items, courses, activity, busy, error, onDecision, onExecute }: ReviewViewProps) {
  const open = items.filter((item) => item.status === 'open')
  const approved = items.filter((item) => item.status === 'approved' && item.action_proposal_id)
  const timeline = activity.filter((event) => event.event_type.startsWith('action.') || event.event_type.startsWith('review.')).slice(0, 16)

  return <div className="page-stack review-workspace">
    <section className="page-intro">
      <p className="eyebrow">Human authority</p>
      <h2>Review & approvals</h2>
      <p>Nothing changes until you decide. Approved actions are executed separately, verified against the local workspace, and recorded in the timeline.</p>
    </section>

    {error && <p className="setup-error" role="alert">{error}</p>}

    <div className="review-workspace-layout">
      <section className="review-workspace-main" aria-label="Review decisions">
        <div className="review-section-heading">
          <div><p className="eyebrow">Waiting for you</p><h3>{open.length} open decision{open.length === 1 ? '' : 's'}</h3></div>
          <span className="review-count-badge">{open.length}</span>
        </div>
        {open.map((item) => <ReviewCard key={item.id} item={item} courses={courses} busy={busy} onDecision={(decision) => onDecision(item.id, decision)} />)}
        {!open.length && <ReviewEmpty title="No decisions waiting" body="When Academia finds conflicting evidence or an action needs approval, it appears here. Reading, studying, and local organization do not require a decision." />}

        {approved.length > 0 && <div className="approved-action-section">
          <div className="review-section-heading"><div><p className="eyebrow">Separate execution step</p><h3>{approved.length} approved action{approved.length === 1 ? '' : 's'} ready to execute</h3></div></div>
          {approved.map((item) => <ApprovedActionCard key={item.id} item={item} busy={busy} onExecute={() => onExecute(item.id)} />)}
        </div>}
      </section>

      <aside className="approval-timeline-panel" aria-label="Approval timeline">
        <div className="review-section-heading compact"><div><p className="eyebrow">Audit trail</p><h3>Approval timeline</h3></div></div>
        <p className="timeline-intro">Proposals, decisions, executions, verification, and failures are recorded locally.</p>
        {timeline.length > 0 ? <ol className="approval-timeline">{timeline.map((event) => <TimelineRow event={event} key={event.id} />)}</ol> : <p className="timeline-empty">No approval activity recorded yet.</p>}
      </aside>
    </div>
  </div>
}

function ApprovedActionCard({ item, busy, onExecute }: { item: ReviewItem; busy: boolean; onExecute: () => Promise<void> }) {
  const details = item.details
  const proposal = record(details.proposal_details) || details
  const actionType = stringValue(proposal.action_type) || stringValue(details.action_type) || 'action'
  const effects = stringList(proposal.effects) || stringList(details.effects)
  const destination = stringValue(proposal.target_id) || stringValue(details.proposed_destination) || stringValue(proposal.destination)
  const source = stringValue(proposal.source_path) || stringValue(details.source_path)
  return <article className="approval-card" aria-label={`Approved ${actionType} ready to execute`}>
    <div className="approval-card-heading"><div><span className="review-kind">{actionLabels[actionType] || 'Approved action'}</span><h3>{item.title}</h3><p>{item.course || 'Workspace'} · approved and waiting for execution</p></div><span className="approval-ready">Ready</span></div>
    {(source || destination) && <dl className="approval-targets">{source && <div><dt>Source</dt><dd>{source}</dd></div>}{destination && <div><dt>Destination</dt><dd>{destination}</dd></div>}</dl>}
    {effects.length > 0 && <div className="effect-list"><strong>This will:</strong><ul>{effects.map((effect) => <li key={effect}>{effect}</li>)}</ul></div>}
    <div className="decision-row"><span className="approval-hint">Nothing has been copied or changed yet.</span><button className="primary-button" disabled={busy} onClick={() => void onExecute()}>{busy ? 'Executing…' : 'Execute approved action'}</button></div>
  </article>
}

function TimelineRow({ event }: { event: ActivityEvent }) {
  const tone = event.event_type.includes('failed') ? 'timeline-failed' : event.event_type === 'action.verified' ? 'timeline-verified' : event.event_type === 'action.executed' ? 'timeline-executed' : 'timeline-proposed'
  const label = event.event_type.replace('action.', '').replace('review.', '').replaceAll('_', ' ')
  const reason = stringValue(event.details.failure_reason)
  const decision = stringValue(event.details.decision)
  return <li className={`approval-timeline-row ${tone}`}>
    <span className="timeline-dot" aria-hidden="true" />
    <div className="timeline-copy"><div><strong>{event.title}</strong><time dateTime={event.created_at}>{formatDate(event.created_at)}</time></div><p>{label} · {event.actor}{decision ? ` · ${decision}` : ''}{reason ? ` · ${reason}` : ''}</p>{event.course && <small>{event.course}</small>}</div>
  </li>
}

function ReviewEmpty({ title, body }: { title: string; body: string }) { return <article className="empty-card review-empty"><div className="empty-mark">✦</div><h3>{title}</h3><p>{body}</p><span className="muted-copy">You’re clear</span></article> }
function record(value: unknown): Record<string, unknown> | null { return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null }
function stringValue(value: unknown): string { return typeof value === 'string' && value.trim() ? value : '' }
function stringList(value: unknown): string[] { return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string' && Boolean(item.trim())) : [] }
function formatDate(value: string): string { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) }
