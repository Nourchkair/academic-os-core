import { useEffect, useState } from 'react'
import { api } from './lib/api'
import type { StudyBlock, StudySchedulePayload } from './types'

type StudyBlockPlannerProps = {
  semester: string
  onOpenSettings: () => void
  onOpenReview: (reviewId: string) => void
}

export function StudyBlockPlanner({ semester, onOpenSettings, onOpenReview }: StudyBlockPlannerProps) {
  const [minutes, setMinutes] = useState(120)
  const [schedule, setSchedule] = useState<StudySchedulePayload | null>(null)
  const [loading, setLoading] = useState(false)
  const [busyBlock, setBusyBlock] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const load = () => {
    if (!semester) return
    setLoading(true)
    setError('')
    setNotice('')
    void api.studySchedule(semester, { minutes, days: 7 }).then((value) => setSchedule(value)).catch((reason) => setError(String(reason))).finally(() => setLoading(false))
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [semester, minutes])

  const propose = async (block: StudyBlock) => {
    setBusyBlock(block.id)
    setError('')
    setNotice('')
    try {
      const value = await api.proposeGoogleCalendarCreate({
        summary: block.summary,
        start: block.start,
        end: block.end,
        description: block.description,
      })
      setNotice(`Review created for ${block.summary}. Nothing is added to Google Calendar until you approve and execute it.`)
      onOpenReview(value.review.id)
    } catch (reason) {
      setError(String(reason))
    } finally {
      setBusyBlock(null)
    }
  }

  const authorized = schedule?.calendar_checked === true
  const grouped = (schedule?.blocks ?? []).reduce<Record<string, StudyBlock[]>>((result, block) => {
    const key = block.start.slice(0, 10)
    result[key] = [...(result[key] ?? []), block]
    return result
  }, {})

  return <section className="study-block-planner" aria-label="Study block planner">
    <header className="study-block-heading">
      <div><p className="eyebrow">Study blocks</p><h3>Turn the plan into real time</h3><p>Advisory blocks placed around your recorded calendar. Each block becomes a separate Review proposal.</p></div>
      <div className="study-block-controls">
        <label>Time budget<select value={minutes} onChange={(event) => setMinutes(Number(event.target.value))}><option value={60}>1 hour</option><option value={120}>2 hours</option><option value={180}>3 hours</option><option value={240}>4 hours</option></select></label>
        <button type="button" className="secondary-button" onClick={load} disabled={loading}>{loading ? 'Planning…' : 'Refresh'}</button>
      </div>
    </header>
    {error && <p className="setup-error" role="alert">{error}</p>}
    {notice && <p className="study-block-notice" role="status">{notice}</p>}
    {schedule && !authorized && <p className="study-block-note">{schedule.calendar_error || 'Google Calendar is not connected. Blocks can still be planned, but calendar proposals need a connection.'} <button type="button" className="text-button" onClick={onOpenSettings}>Open Settings →</button></p>}
    {schedule && !schedule.blocks.length && !loading && <p className="study-block-empty">No study blocks were needed from the current recorded workload.</p>}
    {schedule && schedule.blocks.length > 0 && <div className="study-block-days">
      {Object.entries(grouped).map(([day, blocks]) => <section className="study-block-day" key={day}>
        <h4>{formatDay(day)}</h4>
        {blocks.map((block) => <article className="study-block-row" key={block.id}>
          <div className="study-block-time"><strong>{formatTime(block.start)}</strong><small>{formatTime(block.end)}</small></div>
          <div className="study-block-copy"><strong>{block.title}</strong><span>{block.course_name || block.course_id} · {block.minutes} min</span><small>{block.reason}</small></div>
          <button type="button" className="secondary-button" onClick={() => void propose(block)} disabled={!authorized || busyBlock === block.id}>{busyBlock === block.id ? 'Preparing…' : 'Add to Calendar'}</button>
        </article>)}
      </section>)}
    </div>}
    {schedule && <p className="study-block-footnote">{schedule.note}</p>}
  </section>
}

function formatDay(value: string) {
  const date = new Date(`${value}T12:00:00`)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' })
}

function formatTime(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}
