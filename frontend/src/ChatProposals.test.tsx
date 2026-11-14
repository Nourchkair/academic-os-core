import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { ChatProposals } from './ChatProposals'
import type { ChatProposal } from './lib/chat-history'

const proposals: ChatProposal[] = [
  {
    kind: 'task',
    title: 'Personal task proposal',
    summary: 'Read Week 5 · POL 2103 - Politics · due 2026-10-01',
    effects: ["add 'Read Week 5' to Fall 2026/SEMESTER_TASKS.md", 'preserve unrelated Markdown and every existing task'],
    review_id: 'review-1',
    proposal_id: 'proposal-1',
    status: 'open',
    status_label: 'Waiting for your review',
  },
  {
    kind: 'import',
    title: 'File import proposal',
    summary: 'Copy into Fall 2026/POL 2103 - Politics/00_INBOX',
    effects: ['preserve the original source file'],
    review_id: 'review-2',
    proposal_id: 'proposal-2',
    status: 'resolved',
    action_status: 'verified',
    status_label: 'Completed and verified',
  },
]

afterEach(cleanup)

describe('ChatProposals', () => {
  it('renders exact proposal summaries without implying execution', () => {
    render(<ChatProposals proposals={proposals} onOpenReview={vi.fn()} />)

    expect(screen.getByText('Personal task proposal')).toBeInTheDocument()
    expect(screen.getByText('File import proposal')).toBeInTheDocument()
    expect(screen.getByText('Read Week 5 · POL 2103 - Politics · due 2026-10-01')).toBeInTheDocument()
    expect(screen.getByText('Waiting for your review')).toBeInTheDocument()
    expect(screen.getByText('Applied and verified')).toBeInTheDocument()
    expect(screen.getAllByText('Approval and execution happen only in Review.')).toHaveLength(1)
  })

  it('offers allow, allow-for-chat, and refuse on an inline proposal', () => {
    const onAllow = vi.fn()
    const onAllowForChat = vi.fn()
    const onRefuse = vi.fn()
    const inline: ChatProposal[] = [{
      kind: 'action',
      title: 'Record a coursework grade',
      summary: 'Update First Essay in POL 2103.',
      effects: ['Grade: — → 82%'],
      review_id: null,
      proposal_id: 'proposal-9',
      tier: 'inline',
      action_type: 'grade_record',
      status_label: 'Waiting for Allow',
    }]
    render(<ChatProposals proposals={inline} onOpenReview={vi.fn()} onAllow={onAllow} onAllowForChat={onAllowForChat} onRefuse={onRefuse} />)

    fireEvent.click(screen.getByRole('button', { name: 'Allow' }))
    expect(onAllow).toHaveBeenCalledWith('proposal-9')
    fireEvent.click(screen.getByRole('button', { name: 'Allow for this chat' }))
    expect(onAllowForChat).toHaveBeenCalledWith('proposal-9', 'grade_record')
    fireEvent.click(screen.getByRole('button', { name: 'Refuse' }))
    expect(onRefuse).toHaveBeenCalledWith('proposal-9')
  })

  it('opens the exact linked Review item', () => {
    const onOpenReview = vi.fn()
    render(<ChatProposals proposals={proposals} onOpenReview={onOpenReview} />)

    fireEvent.click(screen.getByRole('button', { name: 'Review this action' }))
    expect(onOpenReview).toHaveBeenCalledWith('review-1')
  })
})
