import type { SourceHealthCourse, SourceReading } from './types'

type SourceHealthPanelProps = {
  health: SourceHealthCourse | null
  loading: boolean
  busy: boolean
  error?: string | null
  onMark: (reading: SourceReading, status: 'read' | 'reading' | 'unread') => Promise<void>
}

export function SourceHealthPanel({ health, loading, busy, error, onMark }: SourceHealthPanelProps) {
  if (loading && !health) return <p className="study-hint" role="status">Reading coverage is loading…</p>
  if (error && !health) return <p className="setup-error" role="alert">{error}</p>
  if (!health) return <p className="study-hint">Source coverage is not available for this class yet.</p>
  return <div className="source-health">
    <section className="source-health-summary" aria-label="Reading coverage summary">
      <div><strong>{health.readings_completed}/{health.assigned_readings}</strong><span>readings read</span></div>
      <div><strong>{health.linked_sources}/{health.assigned_readings}</strong><span>linked sources</span></div>
      <div><strong>{health.unverified_readings}</strong><span>unverified</span></div>
      <div><strong>{health.stale_sources}</strong><span>stale</span></div>
      <div><strong>{health.missing_sources}</strong><span>missing</span></div>
      <div><strong>{health.coverage_percent}%</strong><span>coverage</span></div>
    </section>
    <p className="study-hint">Reading status is student-reported. A missing record means unknown, not unread. Verification compares metadata only.</p>
    <section className="source-health-readings">
      <div className="study-section-title"><div><p className="eyebrow">Assigned readings</p><h4>{health.assigned_readings ? `${health.assigned_readings} recorded` : 'No assigned readings recorded'}</h4></div></div>
      {health.readings.map((reading) => <article className="source-reading-row" key={reading.reading_id}>
        <div className="source-reading-copy">
          <div className="source-reading-top"><strong>{reading.title}</strong><span className={`verification-badge ${verificationTone(reading.verification_result)}`}>{verificationLabel(reading.verification_result)}</span>{reading.stale && <span className="study-stale">Source changed</span>}</div>
          <p>{[reading.author, reading.chapter, reading.pages].filter(Boolean).join(' · ') || 'Reading details not recorded'}</p>
          <small>{reading.source_name ? `${reading.source_name}${reading.readable ? '' : ' · not readable yet'}${reading.processing_status ? ` · ${reading.processing_status}` : ''}` : 'No matching Library source'}{reading.exam_ids.length ? ` · Exam scope: ${reading.exam_ids.length}` : ''}</small>
        </div>
        <div className="source-reading-status" role="group" aria-label={`Reading status for ${reading.title}`}>
          {(['read', 'reading', 'unread'] as const).map((status) => <button type="button" key={status} className={reading.read_status === status ? 'active' : ''} aria-pressed={reading.read_status === status} disabled={busy} onClick={() => void onMark(reading, status)}>{status === 'read' ? 'Read' : status === 'reading' ? 'Reading' : 'Unread'}</button>)}
        </div>
      </article>)}
      {!health.readings.length && <p className="study-hint">Assigned readings appear here after a syllabus or course source records them. Nothing is inferred from filenames.</p>}
    </section>
    <section className="source-health-exams">
      <div className="study-section-title"><div><p className="eyebrow">Exam scope</p><h4>{health.exams.length ? `${health.exams.length} saved exam${health.exams.length === 1 ? '' : 's'}` : 'No exam scope saved'}</h4></div></div>
      {health.exams.map((exam) => <article className="source-exam-card" key={exam.exam_id}>
        <div><strong>{exam.title}</strong><small>{exam.date || 'Date to confirm'} · {exam.covered_topics}/{exam.topic_count} topics covered</small></div>
        <div className="source-exam-meter" aria-label={`${exam.coverage_percent}% topic coverage`}><span style={{ width: `${exam.coverage_percent}%` }} /></div>
        {exam.uncovered_topics.length > 0 && <p>Not yet recorded: {exam.uncovered_topics.join(' · ')}</p>}
        {exam.sources.length > 0 && <ul>{exam.sources.map((source) => <li key={source.source_id}><span>{source.name}</span><small>{source.available ? source.readable ? source.read_status === 'read' ? 'Read' : 'Readable · not read' : 'Not readable yet' : 'Missing source'}</small></li>)}</ul>}
      </article>)}
      {!health.exams.length && <p className="study-hint">Save an exam scope in the Exam scope tab to compare its topics and sources here.</p>}
    </section>
    <section className="source-health-sync">
      <div className="study-section-title"><div><p className="eyebrow">Source sync</p><h4>Syllabus and announcements</h4></div></div>
      {health.sync.syllabus.map((item) => <p className="source-sync-row" key={item.source_id}><span>{item.name}</span><strong>{syncLabel(item.status)}</strong></p>)}
      {!health.sync.syllabus.length && <p className="study-hint">No syllabus sources are visible in this class Library.</p>}
      <p className="study-hint">{health.sync.pending_intake} intake candidate{health.sync.pending_intake === 1 ? '' : 's'} waiting for review. Applying a changed syllabus still uses the existing extraction preview and Review flow.</p>
    </section>
  </div>
}

function verificationTone(value: string) {
  if (value.startsWith('EXACT MATCH')) return 'exact'
  if (value.startsWith('PROBABLE MATCH')) return 'probable'
  if (value === 'MISMATCH') return 'mismatch'
  return 'not-retrieved'
}

function verificationLabel(value: string) {
  if (value.startsWith('EXACT MATCH')) return 'Exact match'
  if (value.startsWith('PROBABLE MATCH')) return 'Probable match'
  if (value === 'MISMATCH') return 'Mismatch'
  return 'Not verified'
}

function syncLabel(value: string) {
  if (value === 'current') return 'Current'
  if (value === 'changed') return 'Changed · review extraction'
  if (value === 'not_applied') return 'Not applied'
  return 'Hash not recorded'
}
