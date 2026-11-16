import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { FlashcardCard } from './FlashcardCard'

const baseProps = {
  number: 1,
  total: 4,
  topic: 'Sovereignty',
  prompt: 'Which definition matches sovereignty?',
  answer: 'Supreme authority within a territory',
  explanation: 'The chapter defines sovereignty in territorial terms.',
  citations: [{ id: 'chunk-1', source_name: 'Chapter 3', locator: 'page 4', text: 'Sovereignty is supreme authority.' }],
  busy: false,
}

describe('FlashcardCard', () => {
  it('does not reveal the answer before the student flips the card', () => {
    const onReveal = vi.fn()
    render(<FlashcardCard {...baseProps} revealed={false} onReveal={onReveal} onRate={vi.fn()} />)

    expect(screen.getByText('Which definition matches sovereignty?')).toBeInTheDocument()
    expect(screen.getByText('Supreme authority within a territory').closest('[aria-hidden="true"]')).not.toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /Flip to answer/ }))
    expect(onReveal).toHaveBeenCalledTimes(1)
  })

  it('shows the answer and records a self-rating after reveal', () => {
    const onRate = vi.fn()
    render(<FlashcardCard {...baseProps} revealed onReveal={vi.fn()} onRate={onRate} />)

    expect(screen.getByText('Supreme authority within a territory')).toBeInTheDocument()
    expect(screen.getByText('Check the source · 1')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Good.*Knew it/s }))
    expect(onRate).toHaveBeenCalledWith('good')
  })

  it('does not offer ratings again once one is saved', () => {
    render(<FlashcardCard {...baseProps} revealed rating="good" onReveal={vi.fn()} onRate={vi.fn()} />)
    expect(screen.getByText(/You rated this/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Again/ })).not.toBeInTheDocument()
  })
})
