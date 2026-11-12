import type { ChatProposal } from './lib/chat-history'

export function ChatProposals({ proposals, onOpenReview }: { proposals: ChatProposal[]; onOpenReview: (reviewId: string) => void }) {
  if (!proposals.length) return null
  return <section className="chat-proposal-list" aria-label="Action proposals waiting for review">
    {proposals.map((proposal) => <article className="chat-proposal-card" key={proposal.review_id}>
      <div className="chat-proposal-heading">
        <span className="chat-proposal-kind">{proposalKind(proposal.kind)}</span>
        <strong>{proposal.title}</strong>
      </div>
      <p>{proposal.summary}</p>
      {proposal.effects?.length ? <ul>{proposal.effects.slice(0, 4).map((effect) => <li key={effect}>{effect}</li>)}</ul> : null}
      <div className="chat-proposal-actions">
        <span>Approval and execution happen only in Review.</span>
        <button type="button" className="secondary-button" onClick={() => onOpenReview(proposal.review_id)}>Review this action</button>
      </div>
    </article>)}
  </section>
}

function proposalKind(kind: string) {
  if (kind === 'task') return 'Personal task'
  if (kind === 'import') return 'File import'
  return 'Action'
}
