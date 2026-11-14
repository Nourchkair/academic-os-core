import { useCallback, useEffect, useState } from 'react'
import { api } from './lib/api'
import type { Course, LibraryItem } from './types'
import { StudyMindMap } from './StudyMindMap'
import { FlashcardCard } from './FlashcardCard'
import { listChatConversations, type ChatConversationSummary } from './lib/chat-history'
import './study.css'

type Citation = { id: string; source_id: string; source_name: string; locator: string; text: string; sha256: string }
type Item = { id: string; kind: string; topic: string; prompt: string; options: string[]; answer?: string; explanation?: string; citations?: Citation[]; flag?: { reason: string } | null }
type SourceCoverage = { deep: boolean; selected_sources: number; scanned_sources: number; complete: boolean; pdf_pages_scanned: number; ocr_pages_scanned?: number; matching_chunks: number; returned_chunks: number }
type StudySet = { id: string; title: string; kind: string; item_count?: number; source_count?: number; created_at?: string; created_by?: string; provenance?: string; authoritative?: boolean; citation_support?: string; items?: Item[]; connections?: { from: string; to: string; label: string }[]; stale_sources: { source_id: string; reason: string }[]; supersedes?: string | null; coverage?: SourceCoverage; warnings?: string[] }
type Attempt = { id: string; item_id: string; answer: string; correct: boolean | null; basis: string; rating: string; feedback: string; excluded?: boolean }
type Session = { id: string; set_id: string; title: string; mode: string; status: string; items: Item[]; attempts: Attempt[]; revealed_ids: string[]; score: { correct: number; graded: number; self_assessed: number } }
type Annotation = { id: string; kind: string; note: string; quote: string; topic: string; citation: Citation; created_at?: string; created_by?: string; basis?: string; stale_source?: { source_id: string; reason: string } | null }
type Exam = { id: string; title: string; date: string | null; format: string; topics: string[]; objectives: string[]; source_ids: string[]; coverage?: { topic: string; read_annotations: number; practice: { attempt_count: number; needs_review: boolean } | null }[] }
type StudyPreferences = { instructions: string; preferred_kind: string; question_count: number; provider: string; model: string; endpoint: string; protocol: string }
type Overview = { preferences: StudyPreferences; sets: StudySet[]; due_count: number; attempt_count: number; topics: { topic: string; item_count: number; attempt_count: number; correct_count: number; self_review_count: number; needs_review: boolean }[]; sessions: { id: string; set_id: string; title: string; status: string; created_at: string }[]; annotations: Annotation[]; exams: Exam[] }
const ratings = ['again', 'hard', 'good', 'easy'] as const

export function StudyView({ course, semester, materials, resumeSessionId, onResumeConsumed, onOpenConversation, onStartStudyChat }: { course: Course; semester: string; materials: LibraryItem[]; resumeSessionId?: string; onResumeConsumed: () => void; onOpenConversation: (conversationId: string) => void; onStartStudyChat: (courseId: string, prompt?: string) => void }) {
  const [overview, setOverview] = useState<Overview | null>(null)
  const [conversations, setConversations] = useState<ChatConversationSummary[]>([])
  const [section, setSection] = useState<'history' | 'exams' | 'progress'>('history')
  const [filter, setFilter] = useState<'all' | 'chat' | 'material' | 'practice'>('all')
  const [archiveQuery, setArchiveQuery] = useState('')
  const [session, setSession] = useState<Session | null>(null)
  const [opened, setOpened] = useState<StudySet | null>(null)
  const [selectedExam, setSelectedExam] = useState<Exam | null>(null)
  const [loading, setLoading] = useState(true)
  const [chatHistoryError, setChatHistoryError] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState('')
  const request = useCallback(<T,>(action: string, args: string[] = []) => api.study<T>([action, '--course', course.id, '--semester', semester, ...args]), [course.id, semester])
  const refresh = useCallback(async () => setOverview(await request<Overview>('overview')), [request])

  useEffect(() => {
    let active = true
    setLoading(true)
    void Promise.allSettled([request<Overview>('overview'), listChatConversations()]).then(([studyResult, chatResult]) => {
      if (!active) return
      if (studyResult.status === 'fulfilled') setOverview(studyResult.value)
      else setError(String(studyResult.reason))
      if (chatResult.status === 'fulfilled') setConversations(chatResult.value)
      else setChatHistoryError('Saved study chats could not be loaded from this browser profile. ' + String(chatResult.reason))
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [request])

  useEffect(() => {
    if (!resumeSessionId) return
    let active = true
    void request<Session>('session', ['--session', resumeSessionId]).then((savedSession) => {
      if (active) { setSession(savedSession); setOpened(null); setSection('history'); setFilter('practice') }
    }).catch((reason) => { if (active) setError(String(reason)) }).finally(() => { if (active) onResumeConsumed() })
    return () => { active = false }
  }, [onResumeConsumed, request, resumeSessionId])

  const perform = async (task: () => Promise<void>) => {
    setBusy(true); setError(null); setNotice('')
    try { await task() } catch (reason) { setError(String(reason)) } finally { setBusy(false) }
  }
  const startSession = (setId: string, mode = 'all', allowStale = false) => perform(async () => {
    setSession(await request<Session>('start', ['--set', setId, '--mode', mode, ...(allowStale ? ['--allow-stale'] : [])]))
    setOpened(null); setSection('history'); setFilter('practice'); await refresh()
  })
  const openSession = (sessionId: string) => perform(async () => {
    setSession(await request<Session>('session', ['--session', sessionId])); setOpened(null)
  })
  const openSet = (record: StudySet) => perform(async () => {
    setOpened(await request<StudySet>('show', ['--set', record.id, '--reveal']))
    setSession(null); setSection('history')
  })
  const download = (format: string) => perform(async () => {
    const result = await request<{ content: string; filename: string }>('export', ['--format', format])
    const url = URL.createObjectURL(new Blob([result.content], { type: format === 'json' ? 'application/json' : 'text/markdown' }))
    const link = document.createElement('a'); link.href = url; link.download = result.filename; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
  })

  const classChats = conversations.filter((conversation) => conversation.courseId === course.id)
  const sets = overview?.sets ?? []
  const sessions = overview?.sessions ?? []
  const archive: Array<{ key: string; type: 'chat'; timestamp: string; conversation: ChatConversationSummary } | { key: string; type: 'material'; timestamp: string; record: StudySet } | { key: string; type: 'practice'; timestamp: string; record: Overview['sessions'][number] }> = [
    ...classChats.map((conversation) => ({ key: 'chat:' + conversation.id, type: 'chat' as const, timestamp: conversation.updatedAt, conversation })),
    ...sets.map((record) => ({ key: 'material:' + record.id, type: 'material' as const, timestamp: record.created_at || '', record })),
    ...sessions.map((record) => ({ key: 'practice:' + record.id, type: 'practice' as const, timestamp: record.created_at || '', record })),
  ].sort((a, b) => b.timestamp.localeCompare(a.timestamp))
  const visibleArchive = archive.filter((entry) => {
    if (filter !== 'all' && entry.type !== filter) return false
    if (!archiveQuery.trim()) return true
    const query = archiveQuery.trim().toLowerCase()
    const searchable = entry.type === 'chat' ? entry.conversation.title + ' ' + (entry.conversation.preview || '')
      : entry.type === 'material' ? entry.record.title + ' ' + (entry.record.items || []).map((item) => item.topic + ' ' + item.prompt).join(' ')
        : entry.record.title
    return searchable.toLowerCase().includes(query)
  })
  const kindLabel = (kind: string) => ({ quiz: 'Quiz', practice_exam: 'Practice exam', flashcards: 'Flashcards', mind_map: 'Mind map', explanation: 'Study guide' }[kind] || kind.replaceAll('_', ' '))
  const assessmentPrompt = (exam: Exam) => 'Help me prepare for ' + exam.title + ' in ' + course.code + '. Use the saved scope' + (exam.topics.length ? ': ' + exam.topics.join(', ') : '') + (exam.objectives.length ? '. Learning objectives: ' + exam.objectives.join('; ') : '') + (exam.format ? '. Format: ' + exam.format : '') + '. Ask me what I want to focus on, then help me study from relevant class sources.'

  return <section className="study-workspace study-archive-workspace" aria-label={`${course.code} study history`}>
    <header className="study-heading study-archive-heading"><div><p className="eyebrow">Study history · {course.code}</p><h3>Your class study archive</h3><p>Pick up an earlier conversation, reopen a quiz or mind map, or review a practice session.</p><p className="study-generation-boundary">New study material is created in Study Chat and saved here when it is linked to this class.</p></div><div className="study-archive-header-actions"><span className="study-count">{overview?.due_count ?? 0}<small>due to review</small></span><button className="primary-button" onClick={() => onStartStudyChat(course.id)}>Start study chat</button></div></header>
    <div className="study-tabs" role="tablist" aria-label="Class study archive sections"><button role="tab" aria-selected={section === 'history'} className={section === 'history' ? 'active' : ''} onClick={() => setSection('history')}>Study history</button><button role="tab" aria-selected={section === 'exams'} className={section === 'exams' ? 'active' : ''} onClick={() => setSection('exams')}>Exam scope</button><button role="tab" aria-selected={section === 'progress'} className={section === 'progress' ? 'active' : ''} onClick={() => setSection('progress')}>Progress & notes</button></div>
    {error && <p className="setup-error" role="alert">{error}</p>}{notice && <p className="study-notice" role="status">{notice}</p>}{busy && <p role="status" className="study-working">Opening saved study material…</p>}

    {section === 'history' && <div className="study-archive-content">
      <section className="study-archive-summary" aria-label="Study archive summary"><div><strong>{classChats.length}</strong><span>saved chats</span></div><div><strong>{sets.length}</strong><span>study materials</span></div><div><strong>{sessions.length}</strong><span>practice sessions</span></div><div><strong>{overview?.attempt_count ?? 0}</strong><span>recorded answers</span></div><div><strong>{materials.length}</strong><span>class sources</span></div></section>
      <div className="study-archive-toolbar"><div><p className="eyebrow">Saved for {course.code}</p><h4>Everything you’ve studied</h4></div><div className="study-archive-toolbar-controls"><label className="study-archive-search"><span aria-hidden="true">⌕</span><input value={archiveQuery} onChange={(event) => setArchiveQuery(event.target.value)} placeholder="Search chats and study materials" aria-label="Search study history" /></label><div className="study-archive-filters" role="group" aria-label="Filter study history">{([['all', 'All'], ['chat', 'Chats'], ['material', 'Study materials'], ['practice', 'Practice']] as const).map(([id, label]) => <button type="button" key={id} className={filter === id ? 'active' : ''} aria-pressed={filter === id} onClick={() => setFilter(id)}>{label}</button>)}</div></div></div>
      {chatHistoryError && <p className="study-hint" role="status">{chatHistoryError}</p>}
      {loading && <p className="study-hint" role="status">Loading saved study history…</p>}
      {!loading && !visibleArchive.length && <StudyEmpty title={filter === 'all' ? 'Your class study history starts here' : 'Nothing saved in this category yet'} body={filter === 'all' ? 'Start a Study Chat for this class. Conversations, quizzes, flashcards, mind maps, and completed practice will collect here as you work.' : 'When you use Study Chat or complete practice for this class, the saved item will appear here.'} />}
      <div className="study-archive-list">{visibleArchive.map((entry) => {
        if (entry.type === 'chat') {
          const conversation = entry.conversation
          const snippet = (conversation.preview || '').replace(/\s+/g, ' ').trim()
          return <article className="study-archive-card" key={entry.key}><span className="study-archive-icon chat">◌</span><div className="study-archive-card-copy"><div className="study-archive-card-top"><span className="study-kind">Study chat</span><time>{conversation.updatedAt ? new Date(conversation.updatedAt).toLocaleString() : 'Date not recorded'}</time></div><h4>{conversation.title}</h4><p>{snippet ? snippet.slice(0, 190) + (snippet.length > 190 ? '…' : '') : 'Saved conversation'}</p><small>{conversation.messageCount} message{conversation.messageCount === 1 ? '' : 's'} · Saved in your workspace</small></div><button className="secondary-button" onClick={() => onOpenConversation(conversation.id)}>Open chat →</button></article>
        }
        if (entry.type === 'material') {
          const record = entry.record
          const stale = (record.stale_sources || []).length > 0
          return <article className="study-archive-card" key={entry.key}><span className={'study-archive-icon material ' + record.kind}>{record.kind === 'mind_map' ? '⌘' : record.kind === 'flashcards' ? '▤' : record.kind === 'quiz' || record.kind === 'practice_exam' ? '?' : '◈'}</span><div className="study-archive-card-copy"><div className="study-archive-card-top"><span className="study-kind">{kindLabel(record.kind)}</span><time>{record.created_at ? new Date(record.created_at).toLocaleString() : 'Date not recorded'}</time></div><h4>{record.title}</h4><p>{record.item_count ?? record.items?.length ?? 0} ideas or questions · {record.source_count ?? 0} source references{record.supersedes ? ' · Revised version' : ''}</p>{stale && <small className="study-stale">Some source files have changed since this was created. This saved version remains available for reference.</small>}</div><div className="study-archive-card-actions"><button className="secondary-button" disabled={busy} onClick={() => void openSet(record)}>Open →</button>{!['mind_map', 'explanation'].includes(record.kind) && <button className="text-button" disabled={busy || stale} onClick={() => void startSession(record.id)}>Practice</button>}{stale && !['mind_map', 'explanation'].includes(record.kind) && <button className="text-button" disabled={busy} onClick={() => void startSession(record.id, 'all', true)}>Practice saved version</button>}</div></article>
        }
        const record = entry.record
        return <article className="study-archive-card" key={entry.key}><span className="study-archive-icon practice">✓</span><div className="study-archive-card-copy"><div className="study-archive-card-top"><span className="study-kind">{record.status === 'active' ? 'In progress' : 'Practice session'}</span><time>{record.created_at ? new Date(record.created_at).toLocaleString() : 'Date not recorded'}</time></div><h4>{record.title}</h4><p>{record.status === 'active' ? 'Continue where you left off.' : 'Saved answer history and review feedback.'}</p><small>{record.status === 'active' ? 'Progress saved automatically' : 'Completed or paused · available to review'}</small></div><button className="secondary-button" disabled={busy} onClick={() => void openSession(record.id)}>{record.status === 'active' ? 'Resume →' : 'Review →'}</button></article>
      })}</div>
      {session && <PracticeSession key={session.id} session={session} busy={busy} onClose={() => setSession(null)} onReveal={(itemId) => perform(async () => setSession(await request<Session>('reveal', ['--session', session.id, '--item', itemId])))} onAnswer={(itemId, answer, rating, feedback) => perform(async () => { const result = await request<{ session: Session }>('answer', ['--session', session.id, '--item', itemId, '--answer', answer, '--feedback', feedback, ...(rating ? ['--rating', rating] : [])]); setSession(result.session); await refresh() })} onRevise={(itemId, patch) => perform(async () => { const revised = await request<StudySet>('revise', ['--set', session.set_id, '--item', itemId, '--payload-json', JSON.stringify(patch)]); setOpened(revised); setSession(null); setNotice('A revised study set was saved. The earlier version and its attempts remain in the archive.'); await refresh() })} onFlag={(itemId, reason) => perform(async () => { await request('flag', ['--set', session.set_id, '--item', itemId, '--reason', reason]); setSession(await request<Session>('session', ['--session', session.id])); await refresh() })} />}
      {opened && <section className="study-archive-material-view"><div className="study-session-top"><div><p className="eyebrow">Saved study material</p><h4>{opened.title}</h4></div><button className="secondary-button" onClick={() => setOpened(null)}>Back to history</button></div>{(opened.stale_sources || []).length > 0 && <p className="study-stale study-freshness-note">One or more cited source files have changed. This historical version is preserved for review.</p>}{['mind_map', 'explanation'].includes(opened.kind) ? <ConceptExplorer studySet={opened} onClose={() => setOpened(null)} /> : <div className="study-archive-question-list">{(opened.items || []).map((item, index) => <article className="study-archive-question" key={item.id}><span className="study-kind">{kindLabel(item.kind)} · {item.topic || 'Question ' + (index + 1)}</span><h4>{item.prompt}</h4>{item.options?.length > 0 && <ol type="A">{item.options.map((option) => <li key={option}>{option}</li>)}</ol>}<details><summary>Show answer and explanation</summary><p><strong>{item.answer}</strong></p>{item.explanation && <p>{item.explanation}</p>}<Citations citations={item.citations || []} /></details></article>)}</div>}</section>}
    </div>}

    {section === 'exams' && <div className="study-exam-layout study-archive-exams"><ExamEditor busy={busy} onSave={(input) => perform(async () => { await request('exam-save', ['--payload-json', JSON.stringify({ ...input, source_ids: [] })]); setNotice('Exam scope saved for this class.'); await refresh() })} /><div className="study-exam-list">{overview?.exams.map((exam) => <article key={exam.id} className="study-exam-card"><p className="eyebrow">{exam.date || 'Date to confirm'} · Saved scope</p><h4>{exam.title}</h4><p>{exam.format || 'Format not recorded'}</p>{exam.topics.length > 0 && <p>{exam.topics.join(' · ')}</p>}<ul>{exam.objectives.map((objective) => <li key={objective}>{objective}</li>)}</ul><div className="study-actions"><button className="primary-button" onClick={() => onStartStudyChat(course.id, assessmentPrompt(exam))}>Prepare in Study Chat →</button><button className="secondary-button" disabled={busy} onClick={() => void perform(async () => setSelectedExam(await request<Exam>('exam', ['--exam', exam.id])))}>Review coverage</button></div>{selectedExam?.id === exam.id && selectedExam.coverage && <ul className="study-coverage">{selectedExam.coverage.map((topic) => <li key={topic.topic}><strong>{topic.topic}</strong><span>{topic.read_annotations ? 'Reading recorded' : 'Reading not recorded'} · {topic.practice?.attempt_count ?? 0} practice attempts{topic.practice?.needs_review ? ' · Needs review' : ''}</span></li>)}</ul>}</article>)}{!overview?.exams.length && <StudyEmpty title="No exam scope saved yet" body="Save confirmed exam topics and objectives here. Use Study Chat to work through that scope with relevant course sources." />}</div></div>}

    {section === 'progress' && <div className="study-progress-layout study-archive-progress"><div><div className="study-section-title"><div><p className="eyebrow">Practice record</p><h4>{overview?.attempt_count ?? 0} saved answers</h4></div></div><p className="study-hint">Practice results and self-ratings help you decide what to revisit. They are not course grades or claims of mastery.</p>{overview?.topics.map((topic) => <article className="study-topic-row" key={topic.topic}><div><strong>{topic.topic}</strong><p>{topic.item_count} items · {topic.attempt_count} attempts · {topic.self_review_count} self-assessments</p></div><span className={topic.needs_review ? 'study-stale' : 'study-hint'}>{topic.needs_review ? 'Revisit this topic' : topic.attempt_count ? 'Practice recorded' : 'Not practiced'}</span></article>)}<h4>Reading notes & learning feedback</h4>{overview?.annotations.slice().reverse().map((note) => <article className="study-annotation" key={note.id}><span className="study-kind">{note.kind.replaceAll('_', ' ')}</span>{note.topic && <h4>{note.topic}</h4>}<p>{note.note}</p>{note.quote && <blockquote>{note.quote}</blockquote>}{note.stale_source && <p className="study-stale study-freshness-note">The cited source is {note.stale_source.reason}. This note is preserved; verify it against a current source before relying on it.</p>}<small>{note.citation.source_name} · {note.citation.locator}{note.created_at ? ' · ' + new Date(note.created_at).toLocaleDateString() : ''}{note.created_by ? ' · ' + note.created_by : ''}{note.basis ? ' · ' + note.basis : ''}</small></article>)}{!overview?.annotations.length && <p className="study-hint">Notes saved from Study Chat or another authorized study interface will appear here.</p>}</div><aside><section className="study-backup"><h4>Back up this class study history</h4><p>Export saved sets, citations, practice attempts, review schedules, exam scope, and annotations.</p><div className="study-actions"><button className="secondary-button" disabled={busy} onClick={() => void download('json')}>JSON backup</button><button className="secondary-button" disabled={busy} onClick={() => void download('markdown')}>Readable archive</button></div></section><details className="study-agent-guide"><summary>Where Study Chat fits</summary><p>Study Chat is where you ask questions and request quizzes, flashcards, or mind maps. This class page keeps the saved conversations and structured study records together for later review.</p></details></aside></div>}
  </section>
}

function PracticeSession({ session, busy, onClose, onReveal, onAnswer, onFlag, onRevise }: { session: Session; busy: boolean; onClose: () => void; onReveal: (id: string) => Promise<void>; onAnswer: (id: string, answer: string, rating: string | null, feedback: string) => Promise<void>; onFlag: (id: string, reason: string) => Promise<void>; onRevise: (id: string, patch: Record<string, unknown>) => Promise<void> }) {
  const [index, setIndex] = useState(() => Math.max(0, session.items.findIndex((item) => !item.flag && !session.attempts.some((attempt) => attempt.item_id === item.id))))
  const [answer, setAnswer] = useState('')
  const [feedback, setFeedback] = useState('')
  const [flagReason, setFlagReason] = useState('')
  const item = session.items[index]
  const attempt = session.attempts.find((entry) => entry.item_id === item.id)
  const revealed = !!item.answer || session.revealed_ids.includes(item.id)
  const next = () => { setIndex((current) => Math.min(session.items.length - 1, current + 1)); setAnswer(''); setFeedback(''); setFlagReason('') }
  if (item.kind === 'flashcard') return <section className="study-session study-flashcard-session">
    <div className="study-session-top"><div><p className="eyebrow">Flashcard practice</p><h4>{session.title}</h4></div><button className="secondary-button" onClick={onClose}>Save & close</button></div>
    <div className="study-session-progress"><span style={{ width: `${session.attempts.length / session.items.length * 100}%` }} /></div>
    <p className="study-hint">{session.attempts.length} of {session.items.length} rated · Your progress saves automatically</p>
    {item.flag ? <p className="study-stale">Excluded from practice: {item.flag.reason}</p> : <FlashcardCard number={index + 1} total={session.items.length} topic={item.topic} prompt={item.prompt} answer={item.answer} explanation={item.explanation} citations={item.citations || []} revealed={revealed} busy={busy} rating={attempt?.rating} canRate={!attempt && !item.flag} recall={answer} onRecallChange={setAnswer} onReveal={() => void onReveal(item.id)} onRate={(rating) => void onAnswer(item.id, answer, rating, feedback)} />}
    {index < session.items.length - 1 && (attempt || item.flag) && <button className="primary-button study-next-card" disabled={busy} onClick={next}>Next card →</button>}
    {session.status === 'completed' && <div className="study-notice">Deck complete. {session.score.self_assessed} self-assessments saved. Cards marked Again or Hard will be prioritized for review. These ratings are practice signals, not a course grade.</div>}
    <div className="study-question-nav" aria-label="Choose a flashcard">{session.items.map((entry, entryIndex) => <button aria-label={`Card ${entryIndex + 1}`} aria-current={index === entryIndex ? 'step' : undefined} key={entry.id} onClick={() => { setIndex(entryIndex); setAnswer(''); setFeedback(''); setFlagReason('') }}>{entryIndex + 1}{session.attempts.some((entryAttempt) => entryAttempt.item_id === entry.id) ? ' ✓' : ''}</button>)}</div>
    {revealed && <QuestionEditor key={item.id} item={item} busy={busy} onSave={(patch) => onRevise(item.id, patch)} />}
    <details className="study-flag"><summary>Problem with this card?</summary><label>Describe the issue<input value={flagReason} onChange={(event) => setFlagReason(event.target.value)} maxLength={1000} /></label><button className="secondary-button" disabled={busy || !flagReason.trim()} onClick={() => void onFlag(item.id, flagReason)}>Flag & exclude from review</button></details>
  </section>
  return <section className="study-session"><div className="study-session-top"><div><p className="eyebrow">{session.mode === 'exam' ? 'Exam practice' : 'Practice session'}</p><h4>{session.title}</h4></div><button className="secondary-button" onClick={onClose}>Save & close</button></div><div className="study-session-progress"><span style={{ width: `${session.attempts.length / session.items.length * 100}%` }} /></div><p className="study-hint">Question {index + 1} of {session.items.length} · {session.attempts.length} answered · Progress saves automatically</p><span className="study-kind">{item.topic}</span><h3>{item.prompt}</h3>{item.kind === 'multiple_choice' ? <div className="study-options">{item.options.map((option, optionIndex) => <button className={`${answer === option || attempt?.answer === option ? 'selected' : ''} ${attempt && option === item.answer ? 'correct' : ''}`} disabled={busy || !!attempt || !!item.flag} key={option} onClick={() => setAnswer(option)}><span>{String.fromCharCode(65 + optionIndex)}</span>{option}</button>)}</div> : <label>Your response<textarea value={answer} onChange={(event) => setAnswer(event.target.value)} disabled={busy || !!attempt} rows={4} maxLength={4000} placeholder={item.kind === 'flashcard' ? 'Recall the answer before revealing it…' : 'Explain in your own words…'} /></label>}
    {item.flag ? <p className="study-stale">Excluded from practice: {item.flag.reason}</p> : !attempt && <div className="study-actions">{item.kind === 'multiple_choice' && !revealed ? <button className="primary-button" disabled={busy || !answer} onClick={() => void onAnswer(item.id, answer, null, feedback)}>Check answer</button> : !revealed ? <button className="primary-button" disabled={busy} onClick={() => void onReveal(item.id)}>Reveal reference answer</button> : null}</div>}
    {revealed && <div className="study-answer"><p className="eyebrow">{attempt?.basis === 'answer-key' ? attempt.correct ? 'Correct' : 'Worth another look' : 'Reference answer'}</p><h4>{item.answer}</h4><p>{item.explanation}</p><Citations citations={item.citations || []} />{!attempt && !item.flag && <><label>What was difficult? <small>(optional)</small><textarea value={feedback} onChange={(event) => setFeedback(event.target.value)} rows={2} maxLength={2000} /></label><p className="study-hint">Rate your recall. This is a self-assessment, separate from an objective score.</p><div className="study-actions">{ratings.map((rating) => <button className="secondary-button" disabled={busy} key={rating} onClick={() => void onAnswer(item.id, answer, rating, feedback)}>{rating[0].toUpperCase() + rating.slice(1)}</button>)}</div></>}{attempt && <p className="study-hint">Saved · {attempt.basis === 'answer-key' ? 'Answer-key scored' : `Self-assessed: ${attempt.rating}`}{attempt.excluded ? ' · Excluded from results' : ''}</p>}</div>}
    {index < session.items.length - 1 && (attempt || item.flag) && <button className="primary-button" disabled={busy} onClick={next}>Next question →</button>}
    {session.status === 'completed' && <div className="study-notice">Session complete. {session.score.correct}/{session.score.graded} answer-key questions correct · {session.score.self_assessed} self-assessments. Review intervals have been saved.</div>}
    <div className="study-question-nav">{session.items.map((entry, entryIndex) => <button aria-label={`Question ${entryIndex + 1}`} aria-current={index === entryIndex ? 'step' : undefined} key={entry.id} onClick={() => { setIndex(entryIndex); setAnswer(''); setFeedback(''); setFlagReason('') }}>{entryIndex + 1}{session.attempts.some((entryAttempt) => entryAttempt.item_id === entry.id) ? ' ✓' : ''}</button>)}</div>
    {revealed && <QuestionEditor key={item.id} item={item} busy={busy} onSave={(patch) => onRevise(item.id, patch)} />}
    <details className="study-flag"><summary>Problem with this question?</summary><label>Describe the issue<input value={flagReason} onChange={(event) => setFlagReason(event.target.value)} maxLength={1000} /></label><button className="secondary-button" disabled={busy || !flagReason.trim()} onClick={() => void onFlag(item.id, flagReason)}>Flag & exclude from results</button></details>
  </section>
}

function ExamEditor({ busy, onSave }: { busy: boolean; onSave: (input: { title: string; date: string; format: string; topics: string[]; objectives: string[] }) => Promise<void> }) {
  const [title, setTitle] = useState('')
  const [date, setDate] = useState('')
  const [format, setFormat] = useState('')
  const [topics, setTopics] = useState('')
  const [objectives, setObjectives] = useState('')
  return <form className="study-exam-editor" onSubmit={(event) => { event.preventDefault(); void onSave({ title, date, format, topics: topics.split('\n').map((value) => value.trim()).filter(Boolean), objectives: objectives.split('\n').map((value) => value.trim()).filter(Boolean) }) }}><p className="eyebrow">Plan with context</p><h4>Add an exam</h4><label>Exam name<input required value={title} onChange={(event) => setTitle(event.target.value)} maxLength={200} /></label><label>Confirmed date <small>(optional)</small><input type="date" value={date} onChange={(event) => setDate(event.target.value)} /></label><label>Format<input value={format} onChange={(event) => setFormat(event.target.value)} placeholder="e.g. 3 short essays, 90 minutes" maxLength={500} /></label><label>Covered topics <small>(one per line)</small><textarea value={topics} onChange={(event) => setTopics(event.target.value)} rows={4} /></label><label>Learning objectives <small>(one per line)</small><textarea value={objectives} onChange={(event) => setObjectives(event.target.value)} rows={3} /></label><p className="study-hint">This saves the scope for later. Use Study Chat to prepare with relevant course sources.</p><button className="primary-button" disabled={busy || !title.trim()} type="submit">Save exam scope</button></form>
}

function ConceptExplorer({ studySet, onClose }: { studySet: StudySet; onClose: () => void }) {
  const items = studySet.items || []
  const [selected, setSelected] = useState(items[0]?.id || '')
  if (studySet.kind === 'mind_map') {
    const rootLabel = studySet.title.replace(/^mind map:\s*/i, '').replace(/^class overview$/i, 'Class concepts')
    return <section className="study-concepts"><div className="study-session-top"><h4>{studySet.title}</h4><button className="secondary-button" onClick={onClose}>Close</button></div><StudyMindMap title={studySet.title} rootLabel={rootLabel} items={items} connections={studySet.connections || []} /></section>
  }
  const item = items.find((entry) => entry.id === selected)
  const positions = Object.fromEntries(items.map((entry, index) => { const angle = index / Math.max(items.length, 1) * Math.PI * 2 - Math.PI / 2; return [entry.id, { x: 360 + Math.cos(angle) * 240, y: 220 + Math.sin(angle) * 160 }] }))
  return <section className="study-concepts"><div className="study-session-top"><h4>{studySet.title}</h4><button className="secondary-button" onClick={onClose}>Close</button></div>{studySet.kind === 'mind_map' && <svg viewBox="0 0 720 440" className="study-map" aria-label="Interactive concept map">{studySet.connections?.map((edge, index) => { const from = positions[edge.from], to = positions[edge.to]; if (!from || !to) return null; return <g key={index}><line x1={from.x} y1={from.y} x2={to.x} y2={to.y} /><title>{edge.label}</title></g> })}{items.map((entry) => <g key={entry.id} role="button" tabIndex={0} aria-label={`Explore ${entry.prompt}`} aria-pressed={selected === entry.id} className={selected === entry.id ? 'selected' : ''} transform={`translate(${positions[entry.id].x},${positions[entry.id].y})`} onClick={() => setSelected(entry.id)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelected(entry.id) } }}><rect x={-75} y={-23} width={150} height={46} rx={12} /><text textAnchor="middle" dy={5}>{entry.topic.slice(0, 22)}</text></g>)}</svg>}<div className="study-actions">{items.map((entry) => <button className="secondary-button" aria-pressed={selected === entry.id} key={entry.id} onClick={() => setSelected(entry.id)}>{entry.topic}</button>)}</div>{item && <article className="study-answer"><h3>{item.prompt}</h3><p>{item.answer}</p><p>{item.explanation}</p><Citations citations={item.citations || []} /><ul>{studySet.connections?.filter((edge) => edge.from === item.id || edge.to === item.id).map((edge, index) => <li key={index}>{items.find((entry) => entry.id === edge.from)?.topic} → {edge.label} → {items.find((entry) => entry.id === edge.to)?.topic}</li>)}</ul></article>}</section>
}
function Citations({ citations }: { citations: Citation[] }) { return <details className="study-citations"><summary>See source evidence · {citations.length}</summary>{citations.map((citation) => <blockquote key={citation.id}><strong>{citation.source_name} · {citation.locator}</strong><p>{citation.text}</p></blockquote>)}<p className="study-hint">Source references support checking. Generated explanations can still contain mistakes.</p></details> }
function StudyEmpty({ title, body }: { title: string; body: string }) { return <div className="study-empty"><span>✦</span><h4>{title}</h4><p>{body}</p></div> }

function QuestionEditor({ item, busy, onSave }: { item: Item; busy: boolean; onSave: (patch: Record<string, unknown>) => Promise<void> }) {
  const [prompt, setPrompt] = useState(item.prompt)
  const [answer, setAnswer] = useState(item.answer || '')
  const [explanation, setExplanation] = useState(item.explanation || '')
  const [options, setOptions] = useState(item.options.join('\n'))
  return <details className="study-flag"><summary>Edit this question</summary><p className="study-hint">Save a new version with the same sources. Existing attempts stay with the original.</p><label>Question<textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} maxLength={2000} /></label>{item.kind === 'multiple_choice' && <label>Options (one per line)<textarea value={options} onChange={(event) => setOptions(event.target.value)} /></label>}<label>Reference answer<textarea value={answer} onChange={(event) => setAnswer(event.target.value)} maxLength={4000} /></label><label>Explanation<textarea value={explanation} onChange={(event) => setExplanation(event.target.value)} maxLength={4000} /></label><button className="secondary-button" disabled={busy || !prompt.trim() || !answer.trim() || !explanation.trim()} onClick={() => void onSave({ prompt, answer, explanation, options: item.kind === 'multiple_choice' ? options.split('\n').map((entry) => entry.trim()).filter(Boolean) : [] })}>Save revised set</button></details>
}
