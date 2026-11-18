import { useEffect, useState } from 'react'
import { api } from './lib/api'
import type { DailyBriefPayload } from './types'

type DailyBriefProps = {
  semester: string
  variant?: 'home' | 'planner'
  onNavigate: (view: 'planner' | 'changes' | 'courses') => void
}

export function DailyBrief({ semester, variant = 'home', onNavigate }: DailyBriefProps) {
  const [brief, setBrief] = useState<DailyBriefPayload | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!semester) return
    let active = true
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true)
    setError('')
    void api.brief(semester).then((value) => {
      if (active) setBrief(value)
    }).catch((reason) => {
      if (active) setError(String(reason))
    }).finally(() => {
      if (active) setLoading(false)
    })
    return () => { active = false }
  }, [semester])

  const navigate = (action: string) => {
    if (action === 'changes') onNavigate('changes')
    else if (action === 'courses') onNavigate('courses')
    else onNavigate('planner')
  }

  if (loading && !brief) {
    return <section className="daily-brief" aria-label="Daily academic brief"><div className="daily-brief-loading" role="status">Composing today’s brief from recorded deadlines, decisions, and study reviews…</div></section>
  }
  if (error && !brief) {
    return <section className="daily-brief" aria-label="Daily academic brief"><div className="daily-brief-error"><p className="eyebrow">Today’s brief</p><p>{error}</p><button type="button" className="text-button" onClick={() => onNavigate('planner')}>Open Planner instead →</button></div></section>
  }
  if (!brief) return null

  return <section className={`daily-brief ${variant === 'planner' ? 'compact' : ''}`} aria-label="Daily academic brief">
    <header className="daily-brief-heading">
      <div><p className="eyebrow">Today’s brief · {brief.date}</p><h2>{brief.headline}</h2></div>
      <span className="daily-brief-advisory">Advisory</span>
    </header>
    <div className="daily-brief-priorities">
      {brief.priorities.slice(0, variant === 'planner' ? 4 : 5).map((priority) => <button type="button" className="daily-brief-priority" data-kind={priority.kind} key={`${priority.kind}-${priority.title}`} onClick={() => navigate(priority.action)}><span className="daily-brief-priority-dot" aria-hidden="true" /><span><strong>{priority.title}</strong><small>{priority.detail}</small></span><span aria-hidden="true">→</span></button>)}
      {!brief.priorities.length && <p className="daily-brief-clear">No deadlines, decisions, or due reviews are waiting. You’re clear for today.</p>}
    </div>
    <div className="daily-brief-metrics">
      <div><strong>{brief.decisions.reviews}</strong><span>decisions</span></div>
      <div><strong>{brief.study.due_count}</strong><span>practice due</span></div>
      <div><strong>{brief.sources.totals.readings_completed}/{brief.sources.totals.assigned_readings}</strong><span>readings read</span></div>
      <div><strong>{brief.sources.totals.missing_sources + brief.sources.totals.stale_sources}</strong><span>source gaps</span></div>
    </div>
    {variant === 'home' && brief.study.blocks.length > 0 && <div className="daily-brief-blocks"><div><p className="eyebrow">Suggested study blocks</p>{brief.study.blocks.slice(0, 2).map((block) => <span key={block.id}><strong>{formatBlock(block.start)}</strong> {block.title} · {block.minutes} min</span>)}</div><button type="button" className="text-button" onClick={() => onNavigate('planner')}>Plan the week →</button></div>}
    <p className="daily-brief-note">{brief.note}</p>
  </section>
}

function formatBlock(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, { weekday: 'short', hour: 'numeric', minute: '2-digit' })
}
