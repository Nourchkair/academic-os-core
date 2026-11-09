import './flashcard-card.css'

type Evidence = { id: string; source_name: string; locator: string; text: string }
type RecallRating = 'again' | 'hard' | 'good' | 'easy'

const ratings: { id: RecallRating; icon: string; title: string; hint: string }[] = [
  { id: 'again', icon: '↻', title: 'Again', hint: 'Missed it' },
  { id: 'hard', icon: '◒', title: 'Hard', hint: 'Took effort' },
  { id: 'good', icon: '✓', title: 'Good', hint: 'Knew it' },
  { id: 'easy', icon: '⚡', title: 'Easy', hint: 'Instant recall' },
]

export function FlashcardCard({
  number,
  total,
  topic,
  prompt,
  answer,
  explanation,
  citations = [],
  revealed,
  busy,
  rating,
  canRate = true,
  recall,
  onRecallChange,
  onReveal,
  onRate,
}: {
  number: number
  total: number
  topic: string
  prompt: string
  answer?: string
  explanation?: string
  citations?: Evidence[]
  revealed: boolean
  busy: boolean
  rating?: string | null
  canRate?: boolean
  recall?: string
  onRecallChange?: (value: string) => void
  onReveal: () => void
  onRate: (rating: RecallRating) => void
}) {
  const savedRating = ratings.find((entry) => entry.id === rating)

  return <div className="flashcard-experience">
    <div className="flashcard-counter"><span>Card {number} of {total}</span><span className="flashcard-kind">Recall practice</span></div>
    <div className="flashcard-stage" aria-live="polite">
      <div className={`flashcard-flip-card ${revealed ? 'is-flipped' : ''}`}>
        <article className="flashcard-face flashcard-front" aria-hidden={revealed}>
          <div className="flashcard-face-top"><span className="flashcard-mark">A</span><span>{topic || 'Class concept'}</span><span className="flashcard-side-label">PROMPT</span></div>
          <h3>{prompt}</h3>
          {onRecallChange && <details className="flashcard-recall"><summary tabIndex={revealed ? -1 : 0}>Type your answer <span>optional</span></summary><textarea aria-label="Your recalled answer" rows={2} maxLength={4000} value={recall ?? ''} onChange={(event) => onRecallChange(event.target.value)} disabled={busy || revealed} placeholder="Write what you remember…" /></details>}
          <p className="flashcard-nudge">Pause and try to recall it before flipping.</p>
        </article>
        <article className="flashcard-face flashcard-back" aria-hidden={!revealed}>
          <div className="flashcard-face-top"><span className="flashcard-mark">B</span><span>{topic || 'Reference answer'}</span><span className="flashcard-side-label">ANSWER</span></div>
          <div className="flashcard-answer-copy"><h3>{answer || 'No reference answer was provided for this card.'}</h3>{explanation && <p>{explanation}</p>}</div>
          {citations.length > 0 && <details className="flashcard-evidence"><summary tabIndex={!revealed ? -1 : 0}>Check the source · {citations.length}</summary>{citations.map((citation) => <blockquote key={citation.id}><strong>{citation.source_name}{citation.locator ? ` · ${citation.locator}` : ''}</strong><p>{citation.text}</p></blockquote>)}</details>}
          {savedRating ? <p className="flashcard-saved-rating"><span>{savedRating.icon}</span> You rated this <strong>{savedRating.title}</strong></p> : null}
        </article>
      </div>
    </div>
    {!revealed ? <div className="flashcard-action-area"><p>Ready to check your recall?</p><button type="button" className="flashcard-reveal" disabled={busy} onClick={onReveal}>{busy ? <><span className="flashcard-button-spinner" />Finding the answer…</> : <>Flip to answer <span aria-hidden="true">↗</span></>}</button></div> : !savedRating && canRate ? <div className="flashcard-rating-area"><div><strong>How well did you know it?</strong><small>Choose honestly. You can review difficult cards again later.</small></div><div className="flashcard-ratings">{ratings.map((entry) => <button type="button" key={entry.id} className={`flashcard-rating flashcard-rating-${entry.id}`} disabled={busy} onClick={() => onRate(entry.id)}><span>{entry.icon}</span><strong>{entry.title}</strong><small>{entry.hint}</small></button>)}</div></div> : null}
  </div>
}
