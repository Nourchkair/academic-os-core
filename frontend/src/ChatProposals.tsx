import type { ChatProposal } from './lib/chat-history'

type ProposalActions = {
  onOpenReview: (reviewId: string) => void
  onAllow?: (proposalId: string) => void
  onAllowForChat?: (proposalId: string, actionType: string | null) => void
  onRefuse?: (proposalId: string) => void
  onAllowAll?: (proposalIds: string[]) => void
}

export function ChatProposals({ proposals, onOpenReview, onAllow, onAllowForChat, onRefuse, onAllowAll }: ProposalActions & { proposals: ChatProposal[] }) {
  if (!proposals.length) return null
  const inlinePending = proposals.filter(isInlinePending)
  return <section className="chat-proposal-list" aria-label="Action proposals waiting for approval">
    {inlinePending.length > 1 && onAllowAll && <div className="chat-proposal-batch">
      <span>{inlinePending.length} changes ready to apply</span>
      <button type="button" className="secondary-button" onClick={() => onAllowAll(inlinePending.map((proposal) => proposal.proposal_id as string))}>Allow all {inlinePending.length}</button>
    </div>}
    {proposals.map((proposal) => <article className="chat-proposal-card" key={proposal.proposal_id ?? proposal.review_id ?? proposal.title}>
      <div className="chat-proposal-heading">
        <span className="chat-proposal-kind">{proposalKind(proposal.kind)}</span>
        <strong>{proposal.title}</strong>
        <span className={`chat-proposal-status ${proposalStatusTone(proposal)}`}>{proposal.status_label ?? 'Waiting for your review'}</span>
      </div>
      <p>{proposal.summary}</p>
      {proposal.effects?.length ? <ul>{proposal.effects.slice(0, 4).map((effect) => <li key={effect}>{effect}</li>)}</ul> : null}
      {isSettled(proposal)
        ? <div className="chat-proposal-actions"><span className="chat-proposal-done">{settledLabel(proposal)}</span></div>
        : proposal.tier === 'inline' && proposal.proposal_id && onAllow
          ? <div className="chat-proposal-actions">
            <span>Applies only when you allow it.</span>
            <button type="button" className="primary-button" onClick={() => onAllow(proposal.proposal_id as string)}>Allow</button>
            {onAllowForChat && <button type="button" className="secondary-button" onClick={() => onAllowForChat(proposal.proposal_id as string, proposal.action_type ?? null)}>Allow for this chat</button>}
            {onRefuse && <button type="button" className="quiet-button" onClick={() => onRefuse(proposal.proposal_id as string)}>Refuse</button>}
          </div>
          : <div className="chat-proposal-actions">
            <span>Approval and execution happen only in Review.</span>
            <button type="button" className="secondary-button" disabled={!proposal.review_id} onClick={() => { if (proposal.review_id) onOpenReview(proposal.review_id) }}>Review this action</button>
            {onRefuse && proposal.proposal_id && <button type="button" className="quiet-button" onClick={() => onRefuse(proposal.proposal_id as string)}>Refuse</button>}
          </div>}
    </article>)}
  </section>
}

function isInlinePending(proposal: ChatProposal) {
  return proposal.tier === 'inline' && Boolean(proposal.proposal_id) && !isSettled(proposal)
}

function isSettled(proposal: ChatProposal) {
  return proposal.status === 'resolved' || proposal.status === 'rejected'
    || proposal.action_status === 'verified' || proposal.action_status === 'failed' || proposal.action_status === 'rejected'
}

function settledLabel(proposal: ChatProposal) {
  if (proposal.action_status === 'verified') return 'Applied and verified'
  if (proposal.action_status === 'failed') return 'This action failed'
  if (proposal.status === 'rejected' || proposal.action_status === 'rejected') return 'Refused'
  return 'No further action needed'
}

function proposalKind(kind: string) {
  if (kind === 'task') return 'Personal task'
  if (kind === 'import') return 'File import'
  if (kind === 'calendar') return 'Google Calendar'
  if (kind === 'action') return 'Workspace change'
  return 'Action'
}

function proposalStatusTone(proposal: ChatProposal) {
  if (proposal.action_status === 'verified' || proposal.status === 'resolved') return 'complete'
  if (proposal.action_status === 'failed' || proposal.status === 'rejected' || proposal.action_status === 'rejected') return 'failed'
  if (proposal.action_status === 'approved' || proposal.action_status === 'executed' || proposal.status === 'approved') return 'approved'
  return 'open'
}
