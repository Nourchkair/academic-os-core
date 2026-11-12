import type { ChatProposal } from './lib/chat-history'

export function ChatProposals({ proposals, onOpenReview }: { proposals: ChatProposal[]; onOpenReview: (reviewId: string) => void }) {
  if (!proposals.length) return null
  return <section className="chat-proposal-list" aria-label="Action proposals waiting for review">
    {proposals.map((proposal) => <article className="chat-proposal-card" key={proposal.review_id}>
      <div className="chat-proposal-heading">
        <span className="chat-proposal-kind">{proposalKind(proposal.kind)}</span>
        <strong>{proposal.title}</strong>
        <span className={`chat-proposal-status ${proposalStatusTone(proposal)}`}>{proposal.status_label ?? 'Waiting for your review'}</span>
      </div>
      <p>{proposal.summary}</p>
      {proposal.effects?.length ? <ul>{proposal.effects.slice(0, 4).map((effect) => <li key={effect}>{effect}</li>)}</ul> : null}
      <div className="chat-proposal-actions">
        <span>Approval and execution happen only in Review.</span>
        {proposal.status === 'resolved' || proposal.action_status === 'verified'
          ? <span className="chat-proposal-done">No further action needed</span>
          : <button type="button" className="secondary-button" onClick={() => onOpenReview(proposal.review_id)}>Review this action</button>}
      </div>
    </article>)}
  </section>
}

function proposalKind(kind: string) {
  if (kind === 'task') return 'Personal task'
  if (kind === 'import') return 'File import'
  return 'Action'
}

function proposalStatusTone(proposal: ChatProposal) {
  if (proposal.action_status === 'verified' || proposal.status === 'resolved') return 'complete'
  if (proposal.action_status === 'failed' || proposal.status === 'rejected') return 'failed'
  if (proposal.action_status === 'approved' || proposal.action_status === 'executed' || proposal.status === 'approved') return 'approved'
  return 'open'
}
