import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from './lib/api'
import type { Course, LibraryItem } from './types'
import { StudyMindMap } from './StudyMindMap'
import { FlashcardCard } from './FlashcardCard'
import './chat-study-studio.css'

export type ModeId = 'explain' | 'quiz' | 'flashcards' | 'guide' | 'map' | 'compare'
export type ChatStudyRequest = { id: string; courseId: string; mode: ModeId; topic: string; count: number; difficulty: string; focus: string; provider?: 'codex'; model?: string; examId?: string }
type StudyMode = { id: ModeId; icon: string; title: string; detail: string; kind: string; defaultCount: number; topicLabel: string; placeholder: string; focusLabel: string }
type Citation = { id: string; source_id: string; source_name: string; locator: string; text: string }
type StudyItem = { id: string; kind: string; topic: string; prompt: string; options: string[]; answer?: string; explanation?: string; citations?: Citation[] }
type StudySet = { id: string; title: string; kind: string; item_count?: number; items?: StudyItem[]; sources?: { source_id: string }[]; stale_sources: { source_id: string; reason: string }[]; connections?: { from: string; to: string; label: string }[]; created_at?: string }
type Attempt = { id: string; item_id: string; answer: string; correct: boolean | null; basis: string; rating: string; feedback?: string }
type Session = { id: string; set_id: string; title: string; mode: string; status: string; items: StudyItem[]; attempts: Attempt[]; revealed_ids: string[]; score: { correct: number; graded: number; self_assessed: number } }
type Overview = { preferences: { instructions: string; preferred_kind: string; question_count: number }; sets: StudySet[]; exams?: { id: string; title: string; date?: string | null; topics: string[]; source_ids: string[] }[]; topics?: { topic: string; attempt_count: number; correct_count: number; needs_review: boolean }[] }
type Coverage = { deep: boolean; selected_sources: number; scanned_sources: number; complete: boolean; pdf_pages_scanned: number; matching_chunks: number; returned_chunks: number }
type GenerationAudit = { courseId: string; coverage?: Coverage; warnings: string[] }
type Props = { courses: Course[]; course?: Course; items: LibraryItem[]; selectedSourceIds: string[]; semester: string; provider: 'codex'; model?: string; onCollapse: () => void; isVisible: boolean; chatRequest: ChatStudyRequest | null; onChatRequestComplete: (id: string, title?: string, error?: string) => void }

const modes: StudyMode[] = [
  { id: 'explain', icon: '◎', title: 'Explain', detail: 'Unpack an idea step by step.', kind: 'explanation', defaultCount: 4, topicLabel: 'What should we make sense of?', placeholder: 'e.g. Why does Plato divide the soul into three parts?', focusLabel: 'Explanation depth' },
  { id: 'quiz', icon: '▦', title: 'Quiz me', detail: 'Practice one question at a time.', kind: 'quiz', defaultCount: 8, topicLabel: 'What should this quiz cover?', placeholder: 'e.g. Midterm topics: Books I–IV and the tripartite soul', focusLabel: 'Question types' },
  { id: 'flashcards', icon: '▤', title: 'Flashcards', detail: 'Recall key terms and ideas.', kind: 'flashcards', defaultCount: 12, topicLabel: 'What should we practice recalling?', placeholder: 'e.g. Key terms and arguments from Books I–II', focusLabel: 'Card style' },
  { id: 'guide', icon: '☷', title: 'Study guide', detail: 'Build a focused review outline.', kind: 'explanation', defaultCount: 8, topicLabel: 'What should the guide help you review?', placeholder: 'e.g. The argument for justice in Book I', focusLabel: 'Guide length' },
  { id: 'map', icon: '⌘', title: 'Mind map', detail: 'Connect the central concepts.', kind: 'mind_map', defaultCount: 12, topicLabel: 'What ideas should the map connect?', placeholder: 'e.g. Justice, the soul, and the ideal city', focusLabel: 'Map detail' },
  { id: 'compare', icon: '⇄', title: 'Compare sources', detail: 'Find agreements and differences.', kind: 'explanation', defaultCount: 5, topicLabel: 'What should we compare?', placeholder: 'e.g. How do these readings define political justice?', focusLabel: 'Comparison focus' },
]
const focusChoices: Record<ModeId, string[]> = {
  explain: ['Step by step', 'More concise', 'Deeper detail'],
  quiz: ['Multiple choice', 'Short answer', 'Mixed'],
  flashcards: ['Key terms', 'Concepts & examples', 'Mixed'],
  guide: ['Concise', 'Standard', 'Detailed'],
  map: ['Core concepts', 'Standard', 'Detailed'],
  compare: ['Agreements', 'Differences', 'Both'],
}
const difficulties = ['Easy', 'Medium', 'Hard']

function modeFor(kind: string, title = ''): StudyMode {
  const titleMode = modes.find((mode) => title.toLocaleLowerCase().startsWith(`${mode.title.toLocaleLowerCase()}:`))
  return titleMode ?? modes.find((mode) => mode.kind === kind) ?? modes.find((mode) => mode.id === (kind === 'practice_exam' ? 'quiz' : kind === 'mind_map' ? 'map' : kind === 'flashcards' ? 'flashcards' : 'explain'))!
}

function DialogChoice({ label, value, values, onChange }: { label: string; value: string; values: string[]; onChange: (value: string) => void }) {
  return <fieldset className="studio-fieldset"><legend>{label}</legend><div className="studio-segments" role="group" aria-label={label}>{values.map((entry) => <button type="button" key={entry} className={value === entry ? 'selected' : ''} aria-pressed={value === entry} onClick={() => onChange(entry)}>{entry}</button>)}</div></fieldset>
}

export function ChatStudyStudio({ courses, course, items, selectedSourceIds, semester, provider, model, onCollapse, isVisible, chatRequest, onChatRequestComplete }: Props) {
  const [studioCourseId, setStudioCourseId] = useState(course?.id ?? '')
  const [sourceIds, setSourceIds] = useState<string[]>(() => selectedSourceIds.filter((id) => items.some((item) => item.id === id && item.course_id === course?.id)))
  const [setupMode, setSetupMode] = useState<StudyMode | null>(null)
  const [topic, setTopic] = useState('')
  const [count, setCount] = useState(8)
  const [difficulty, setDifficulty] = useState('Medium')
  const [focus, setFocus] = useState('Mixed')
  const [sourceSearch, setSourceSearch] = useState('')
  const [sourceListOpen, setSourceListOpen] = useState(false)
  const sourcePickerRef = useRef<HTMLDivElement | null>(null)
  const [overview, setOverview] = useState<Overview | null>(null)
  const [loadingOverview, setLoadingOverview] = useState(false)
  const [generatingMode, setGeneratingMode] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [session, setSession] = useState<Session | null>(null)
  const [openedSet, setOpenedSet] = useState<StudySet | null>(null)
  const [activeIndex, setActiveIndex] = useState(0)
  const [selectedOption, setSelectedOption] = useState('')
  const [typedAnswer, setTypedAnswer] = useState('')
  const [busy, setBusy] = useState(false)
  const [newSetId, setNewSetId] = useState('')
  const [generationAudit, setGenerationAudit] = useState<GenerationAudit | null>(null)
  const [selectedExamId, setSelectedExamId] = useState('')
  const chatCourseRef = useRef(course?.id ?? '')
  const scopeEditedRef = useRef(false)
  const processedChatRequestRef = useRef('')

  const currentCourse = courses.find((entry) => entry.id === studioCourseId)
  const courseSources = useMemo(() => items.filter((item) => item.course_id === studioCourseId && !item.relative_path.includes('/STUDY/')), [items, studioCourseId])
  const filteredSources = useMemo(() => {
    const query = sourceSearch.trim().toLocaleLowerCase()
    return courseSources.filter((item) => !query || `${item.name} ${item.relative_path} ${item.category}`.toLocaleLowerCase().includes(query))
  }, [courseSources, sourceSearch])
  const allFilteredSelected = filteredSources.length > 0 && filteredSources.every((item) => sourceIds.includes(item.id))
  const selectedCourseSources = useMemo(() => courseSources.filter((item) => sourceIds.includes(item.id)), [courseSources, sourceIds])
  const upcomingExam = overview?.exams?.find((exam) => !exam.date || exam.date >= new Date().toISOString().slice(0, 10))
  const topicToReview = overview?.topics?.find((entry) => entry.needs_review)
  const request = (courseId: string, action: string, args: string[] = []) => api.study([action, '--course', courseId, '--semester', semester, ...args])
  const refreshOverview = async (courseId = studioCourseId) => {
    if (!courseId) { setOverview(null); return }
    setLoadingOverview(true)
    try { setOverview(await request(courseId, 'overview') as Overview) } finally { setLoadingOverview(false) }
  }

  useEffect(() => {
    const chatCourseId = course?.id ?? ''
    if (chatCourseRef.current !== chatCourseId) {
      chatCourseRef.current = chatCourseId
      scopeEditedRef.current = false
      setStudioCourseId(chatCourseId)
      setSession(null); setOpenedSet(null)
    }
    if (!scopeEditedRef.current && chatCourseId && studioCourseId === chatCourseId) {
      setSourceIds(selectedSourceIds.filter((id) => items.some((item) => item.id === id && item.course_id === chatCourseId)))
    }
  }, [course?.id, items, selectedSourceIds, studioCourseId])

  useEffect(() => {
    let active = true
    if (!studioCourseId) { setOverview(null); return }
    setLoadingOverview(true)
    void request(studioCourseId, 'overview').then((result) => { if (active) setOverview(result as Overview) }).catch((reason) => { if (active) setError(String(reason)) }).finally(() => { if (active) setLoadingOverview(false) })
    return () => { active = false }
  }, [studioCourseId, semester])

  useEffect(() => {
    if (!setupMode) return
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === 'Escape') setSetupMode(null) }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [setupMode])

  useEffect(() => {
    if (!sourceListOpen) return
    const frame = window.requestAnimationFrame(() => sourcePickerRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }))
    return () => window.cancelAnimationFrame(frame)
  }, [sourceListOpen])

  useEffect(() => {
    if (!setupMode) return
    const body = document.body
    const root = document.documentElement
    const previousBodyOverflow = body.style.overflow
    const previousRootOverflow = root.style.overflow
    const previousBodyOverscroll = body.style.overscrollBehavior
    const previousRootOverscroll = root.style.overscrollBehavior
    body.style.overflow = 'hidden'
    root.style.overflow = 'hidden'
    body.style.overscrollBehavior = 'none'
    root.style.overscrollBehavior = 'none'
    return () => {
      body.style.overflow = previousBodyOverflow
      root.style.overflow = previousRootOverflow
      body.style.overscrollBehavior = previousBodyOverscroll
      root.style.overscrollBehavior = previousRootOverscroll
    }
  }, [setupMode])

  const selectCourse = (courseId: string) => {
    scopeEditedRef.current = true
    setStudioCourseId(courseId)
    const nextIds = items.filter((item) => item.course_id === courseId && !item.relative_path.includes('/STUDY/')).map((item) => item.id)
    setSourceIds(nextIds)
  }

  const openSetup = (mode: StudyMode) => {
    setSetupMode(mode); setTopic(''); setSelectedExamId(''); setCount(mode.defaultCount); setDifficulty('Medium'); setFocus(focusChoices[mode.id][mode.id === 'quiz' ? 0 : 1]); setSourceSearch(''); setSourceListOpen(false); setError('')
    if (!studioCourseId && courses.length === 1) selectCourse(courses[0].id)
  }

  const toggleVisibleSources = () => {
    const ids = filteredSources.map((item) => item.id)
    scopeEditedRef.current = true
    setSourceIds((current) => allFilteredSelected ? current.filter((id) => !ids.includes(id)) : [...new Set([...current, ...ids])])
  }

  const runGeneration = async (configuration: { mode: StudyMode; targetCourse: Course; topic: string; count: number; difficulty: string; focus: string; sourceIds: string[]; examId?: string; preferenceInstructions?: string }) => {
    const { mode, targetCourse, topic: studyTopic, count: studyCount, difficulty: studyDifficulty, focus: studyFocus, sourceIds: studySourceIds, examId, preferenceInstructions } = configuration
    const focusTopic = studyTopic.trim()
    if (studySourceIds.length === 0 || studySourceIds.length > 300) throw new Error(studySourceIds.length === 0 ? 'Choose at least one checked source from this class.' : 'Choose no more than 300 sources for one study set.')
    if (mode.id === 'compare' && studySourceIds.length < 2) throw new Error('Choose at least two class sources to compare.')
    const scopedExam = targetCourse.id === studioCourseId ? overview?.exams?.find((exam) => exam.id === examId) : undefined
    const inferredExam = !focusTopic && targetCourse.id === studioCourseId ? scopedExam || upcomingExam : undefined
    const inferredReviewTopic = !focusTopic && targetCourse.id === studioCourseId ? topicToReview : undefined
    const effectiveExamId = examId || inferredExam?.id
    const defaultScope = inferredExam
      ? `Prepare for ${inferredExam.title}`
      : inferredReviewTopic
        ? `Review ${inferredReviewTopic.topic}`
        : 'Class overview'
    setBusy(true); setError(''); setGenerationAudit(null); setGeneratingMode(mode.id); setSetupMode(null)
    const custom = [
      focusTopic ? `Study focus: ${focusTopic}.` : `No specific focus was supplied. Choose a useful scope for this ${mode.title.toLowerCase()} from the selected class-source excerpts and supplied learning context. Prioritize saved upcoming exam scope or upcoming course tasks when relevant, then topics marked for review from recorded practice. If neither points to a clear scope, make a balanced selection of core concepts from the selected sources. Do not assume unrecorded exam scope or instructor preferences.`,
      inferredReviewTopic ? `A topic marked for review in recorded practice is ${inferredReviewTopic.topic}; prioritize it when it fits the selected study mode and upcoming assessment scope.` : '',
      `Difficulty: ${studyDifficulty.toLowerCase()}.`,
      `Mode-specific preference: ${studyFocus}.`,
      mode.id === 'quiz' ? `Question format: ${studyFocus === 'Mixed' ? 'mix multiple-choice and short-answer questions' : studyFocus.toLowerCase() + ' questions only'}.` : '',
      mode.id === 'flashcards' ? `Create cards for ${studyFocus.toLowerCase()}, with a clear prompt on the front and a concise evidence-based answer on the back.` : '',
      mode.id === 'guide' ? `Create a ${studyFocus.toLowerCase()} study guide with an organized outline, key terms, relationships, likely misunderstandings, and review questions.` : '',
      mode.id === 'map' ? `Create a ${studyFocus.toLowerCase()} concept map. Choose the number of map sections automatically from the focus and source evidence. A narrow focus should produce a compact map; a broad focus can use more sections. Include only distinct, useful concepts, make links meaningful, and do not pad the map to reach the maximum.` : '',
      mode.id === 'compare' ? `Compare the selected sources for ${studyFocus.toLowerCase()}. Clearly identify which source supports each point and avoid treating disagreement as error.` : '',
      mode.id === 'explain' ? `Explain in a ${studyFocus.toLowerCase()} way, beginning with a clear model, then examples, then a brief check for understanding.` : '',
      'Use the retrieved class evidence and saved study context. Cite every generated item to supporting excerpts. If evidence is insufficient, state the gap instead of filling it with outside facts.',
      preferenceInstructions ? `Student’s saved study preferences: ${preferenceInstructions}` : '',
    ].filter(Boolean).join(' ').slice(0, 2000)
    const selectedProvider = chatRequest?.provider ?? provider
    const selectedModel = chatRequest?.model ?? model
    const args = [
      '--deep', '--limit', '128', ...studySourceIds.flatMap((id) => ['--source', id]), ...(focusTopic ? ['--query', focusTopic] : []),
      '--kind', mode.kind, '--count', String(mode.id === 'map' ? 30 : Math.max(1, Math.min(30, studyCount))), '--instructions', custom,
      '--title', `${mode.title}: ${focusTopic || defaultScope}`.slice(0, 200),
      '--provider', selectedProvider,
      ...(selectedModel ? ['--model', selectedModel] : []),
      ...(effectiveExamId ? ['--exam', effectiveExamId] : []),
    ]
    try {
      const created = await request(targetCourse.id, 'generate', args) as StudySet & { coverage?: Coverage; warnings?: string[] }
      setNewSetId(created.id); setStudioCourseId(targetCourse.id)
      setGenerationAudit({ courseId: targetCourse.id, coverage: created.coverage, warnings: created.warnings ?? [] })
      await refreshOverview(targetCourse.id)
      return created
    } catch (reason) {
      setError(`Could not generate this study material. ${String(reason)}`)
      throw reason
    } finally { setBusy(false); setGeneratingMode(null) }
  }

  const generate = async () => {
    if (!setupMode || !currentCourse) return
    if (setupMode.id === 'compare' && sourceIds.length < 2) { setError('Choose at least two class sources to compare.'); return }
    try {
      await runGeneration({ mode: setupMode, targetCourse: currentCourse, topic, count, difficulty, focus, sourceIds, examId: selectedExamId, preferenceInstructions: overview?.preferences.instructions })
    } catch { /* The setup panel displays the generation error. */ }
  }

  useEffect(() => {
    if (!chatRequest || processedChatRequestRef.current === chatRequest.id) return
    processedChatRequestRef.current = chatRequest.id
    const targetCourse = courses.find((entry) => entry.id === chatRequest.courseId)
    const classSourceIds = selectedSourceIds.filter((id) => items.some((item) => item.id === id && item.course_id === chatRequest.courseId))
    const mode = modes.find((entry) => entry.id === chatRequest.mode)
    if (!targetCourse || !mode) {
      onChatRequestComplete(chatRequest.id, undefined, 'Choose a class before generating study material.')
      return
    }
    if (!classSourceIds.length) {
      onChatRequestComplete(chatRequest.id, undefined, `No sources from ${targetCourse.code} are checked. Check at least one source in the Context panel, then ask me to try again.`)
      return
    }
    setStudioCourseId(targetCourse.id)
    setSourceIds(classSourceIds)
    setSession(null); setOpenedSet(null)
    void runGeneration({ mode, targetCourse, topic: chatRequest.topic, count: chatRequest.count, difficulty: chatRequest.difficulty, focus: chatRequest.focus, sourceIds: classSourceIds, examId: chatRequest.examId })
      .then((created) => onChatRequestComplete(chatRequest.id, created.title || `${mode.title}: ${chatRequest.topic}`))
      .catch((reason) => onChatRequestComplete(chatRequest.id, undefined, String(reason)))
  }, [chatRequest])

  const openSet = async (record: StudySet) => {
    if (!currentCourse) return
    setBusy(true); setError(''); setSession(null); setOpenedSet(null)
    try {
      if (['quiz', 'practice_exam', 'flashcards'].includes(record.kind)) {
        const next = await request(currentCourse.id, 'start', ['--set', record.id]) as Session
        setSession(next); setOpenedSet(record); setActiveIndex(0); setSelectedOption(''); setTypedAnswer('')
      } else {
        const next = await request(currentCourse.id, 'show', ['--set', record.id, '--reveal']) as StudySet
        setOpenedSet(next)
      }
    } catch (reason) { setError(String(reason)) } finally { setBusy(false) }
  }

  const activeItem = session?.items[activeIndex]
  const activeAttempt = activeItem ? session?.attempts.find((attempt) => attempt.item_id === activeItem.id) : undefined
  const missedAttempts = session?.attempts.filter((attempt) => attempt.correct === false) ?? []
  const practicePercent = session && session.score.graded > 0 ? Math.round((session.score.correct / session.score.graded) * 100) : null
  const isRevealed = activeItem ? Boolean(session?.revealed_ids.includes(activeItem.id) || activeItem.answer) : false
  const isFlashcardSession = Boolean(session?.items.some((item) => item.kind === 'flashcard'))
  const flashcardsToReview = session?.attempts.flatMap((attempt) => {
    const item = session.items.find((entry) => entry.id === attempt.item_id)
    return item && ['again', 'hard'].includes(attempt.rating) ? [{ attempt, item }] : []
  }) ?? []
  const closeViewer = () => { setSession(null); setOpenedSet(null); setActiveIndex(0); setSelectedOption(''); setTypedAnswer(''); void refreshOverview() }

  const reveal = async () => {
    if (!session || !activeItem || !currentCourse) return
    setBusy(true); setError('')
    try { setSession(await request(currentCourse.id, 'reveal', ['--session', session.id, '--item', activeItem.id]) as Session) }
    catch (reason) { setError(String(reason)) } finally { setBusy(false) }
  }

  const answer = async (value: string, rating?: string) => {
    if (!session || !activeItem || !currentCourse) return
    setBusy(true); setError('')
    try {
      const result = await request(currentCourse.id, 'answer', ['--session', session.id, '--item', activeItem.id, '--answer', value, ...(rating ? ['--rating', rating] : [])]) as { session: Session }
      setSession(result.session); await refreshOverview()
    } catch (reason) { setError(String(reason)) } finally { setBusy(false) }
  }

  const goNext = () => {
    if (!session) return
    setActiveIndex((index) => Math.min(index + 1, session.items.length - 1)); setSelectedOption(''); setTypedAnswer('')
  }
  const goPrevious = () => {
    setActiveIndex((index) => Math.max(0, index - 1)); setSelectedOption(''); setTypedAnswer('')
  }

  return <>
    <aside className="chat-study-panel chat-studio-panel" aria-label="Study modes" hidden={!isVisible}>
      <header className="chat-panel-heading"><div><p className="eyebrow">Studio</p><h3>{session || openedSet ? 'Study material' : 'Study modes'}</h3></div><div className="chat-panel-actions"><button className="chat-panel-collapse" onClick={onCollapse} aria-label="Collapse study modes panel" data-tooltip="Collapse study modes" data-tooltip-side="bottom">›</button></div></header>
      {session || openedSet ? <>
        <div className="studio-view-heading"><button className="studio-back" onClick={closeViewer}>‹ <span>Studio</span></button><span>{currentCourse?.code}</span></div>
      {session ? <div className="studio-player">
          <div className="studio-player-title"><span className={`chat-mode-icon mode-${modeFor(openedSet?.kind ?? 'quiz', session.title).id}`}>{modeFor(openedSet?.kind ?? 'quiz', session.title).icon}</span><h4>{session.title}</h4></div>
          {session.status === 'completed' || !activeItem ? isFlashcardSession ? <div className="studio-complete studio-flashcard-complete"><span>✓</span><p className="eyebrow">Deck complete</p><h4>Nice recall session</h4><p>{session.score.self_assessed} cards rated. Cards marked Again or Hard are scheduled sooner for review. These are practice signals, not a course grade.</p><section className="studio-answer-review" aria-label="Flashcards to revisit"><h5>Revisit these cards <span>{flashcardsToReview.length}</span></h5>{flashcardsToReview.length ? flashcardsToReview.map(({ attempt, item }) => <article className="studio-review-item studio-flashcard-review" key={attempt.id}><small>{item.topic} · Rated {attempt.rating}</small><strong>{item.prompt}</strong>{item.answer && <p><b>Answer:</b> {item.answer}</p>}{item.explanation && <p>{item.explanation}</p>}{item.citations?.length ? <details className="studio-citations"><summary>Source evidence · {item.citations.length}</summary>{item.citations.map((citation) => <blockquote key={citation.id}><strong>{citation.source_name} · {citation.locator}</strong><p>{citation.text}</p></blockquote>)}</details> : null}</article>) : <p className="studio-no-missed">No cards marked Again or Hard. Nice work.</p>}</section><button className="studio-primary" onClick={closeViewer}>Back to Studio</button></div> : <div className="studio-complete"><span>✓</span><p className="eyebrow">Session complete</p>{practicePercent !== null ? <><h4>Practice score · {practicePercent}%</h4><p>{session.score.correct} of {session.score.graded} objective questions correct. This is a practice score, not a course grade.</p></> : <><h4>Practice reviewed</h4><p>No objective score for self-assessed responses. {session.score.self_assessed} self-assessments recorded.</p></>}{session.score.self_assessed > 0 && practicePercent !== null && <p className="studio-self-assessed-note">Plus {session.score.self_assessed} self-assessed responses.</p>}<section className="studio-answer-review" aria-label="Review missed answers"><h5>Review missed answers <span>{missedAttempts.length}</span></h5>{missedAttempts.length ? missedAttempts.map((attempt) => {
              const item = session.items.find((entry) => entry.id === attempt.item_id)
              if (!item) return null
              return <article className="studio-review-item" key={attempt.id}><small>{item.topic}</small><strong>{item.prompt}</strong><p><b>Your answer:</b> {attempt.answer || 'No answer recorded'}</p>{item.answer && <p><b>Reference answer:</b> {item.answer}</p>}{item.explanation && <p>{item.explanation}</p>}{item.citations?.length ? <details className="studio-citations"><summary>Source evidence · {item.citations.length}</summary>{item.citations.map((citation) => <blockquote key={citation.id}><strong>{citation.source_name} · {citation.locator}</strong><p>{citation.text}</p></blockquote>)}</details> : null}</article>
            }) : <p className="studio-no-missed">No missed objective answers to review. Nice work.</p>}</section><button className="studio-primary" onClick={closeViewer}>Back to Studio</button></div> : <>
            <div className="studio-progress"><span>{activeIndex + 1} / {session.items.length}</span><span>{activeItem.kind === 'flashcard' ? `${session.score.self_assessed} rated` : `${session.score.correct} correct`}</span><div><i style={{ width: `${((activeItem.kind === 'flashcard' ? session.score.self_assessed : activeIndex + 1) / session.items.length) * 100}%` }} /></div></div>
            {activeItem.kind === 'flashcard' ? <section className="studio-flashcard-question"><FlashcardCard number={activeIndex + 1} total={session.items.length} topic={activeItem.topic} prompt={activeItem.prompt} answer={activeItem.answer} explanation={activeItem.explanation} citations={activeItem.citations || []} revealed={isRevealed} busy={busy} rating={activeAttempt?.rating} canRate={!activeAttempt} recall={typedAnswer} onRecallChange={setTypedAnswer} onReveal={() => void reveal()} onRate={(rating) => void answer(typedAnswer, rating)} /></section> : <section className="studio-question"><small>{activeItem.topic}</small><h4>{activeItem.prompt}</h4>
              {activeItem.options?.length > 0 && <div className="studio-options">{activeItem.options.map((option, index) => <button type="button" key={option} className={`${selectedOption === option ? 'chosen' : ''} ${activeAttempt && option === activeItem.answer ? 'correct' : ''} ${activeAttempt && selectedOption === option && !activeAttempt.correct ? 'incorrect' : ''}`} onClick={() => !activeAttempt && setSelectedOption(option)} disabled={Boolean(activeAttempt) || busy}><span>{String.fromCharCode(65 + index)}</span>{option}</button>)}</div>}
              {!activeItem.options?.length && !activeAttempt && !isRevealed && <textarea className="studio-answer-input" value={typedAnswer} onChange={(event) => setTypedAnswer(event.target.value)} placeholder="Write your answer before revealing the reference" rows={3} />}
              {activeAttempt && <div className={`studio-feedback ${activeAttempt.correct === true ? 'good' : activeAttempt.correct === false ? 'needs-work' : ''}`}><strong>{activeAttempt.correct === true ? 'Correct' : activeAttempt.correct === false ? 'Not quite' : `You rated this ${activeAttempt.rating}`}</strong>{activeItem.answer && <p><b>Reference answer:</b> {activeItem.answer}</p>}{activeItem.explanation && <p>{activeItem.explanation}</p>}</div>}
              {!activeAttempt && isRevealed && <div className="studio-feedback"><strong>Reference answer</strong><p>{activeItem.answer}</p>{activeItem.explanation && <p>{activeItem.explanation}</p>}<div className="studio-ratings"><small>How well did you know it?</small><div>{['again', 'hard', 'good', 'easy'].map((rating) => <button key={rating} disabled={busy} onClick={() => void answer(typedAnswer, rating)}>{rating}</button>)}</div></div></div>}
              {activeItem.citations?.length ? <details className="studio-citations"><summary>Source evidence · {activeItem.citations.length}</summary>{activeItem.citations.map((citation) => <blockquote key={citation.id}><strong>{citation.source_name} · {citation.locator}</strong><p>{citation.text}</p></blockquote>)}</details> : null}
            </section>}
            {activeItem.kind === 'flashcard' ? <div className="studio-flashcard-nav"><button className="studio-secondary" disabled={activeIndex === 0 || busy} onClick={goPrevious}>← Previous</button><span>Card {activeIndex + 1} of {session.items.length}</span><button className="studio-primary" disabled={!activeAttempt || busy || activeIndex + 1 >= session.items.length} onClick={goNext}>Next card →</button></div> : <div className="studio-player-actions">{activeAttempt ? <button className="studio-primary" onClick={goNext}>{activeIndex + 1 >= session.items.length ? 'Finish' : 'Next'}</button> : activeItem.options?.length ? <button className="studio-primary" disabled={!selectedOption || busy} onClick={() => void answer(selectedOption)}>{busy ? 'Checking…' : 'Check answer'}</button> : !isRevealed ? <button className="studio-primary" disabled={busy || !typedAnswer.trim()} onClick={() => void reveal()}>Show reference answer</button> : null}</div>}
          </>}
        </div> : openedSet && (openedSet.kind === 'mind_map' ? <div className="studio-concept-view studio-map-panel"><StudyMindMap title={openedSet.title} rootLabel={openedSet.title.replace(/^mind map:\s*/i, '').replace(/^class overview$/i, currentCourse?.name || 'Class concepts')} items={openedSet.items ?? []} connections={openedSet.connections ?? []} startExpanded /><button className="studio-secondary" onClick={closeViewer}>Back to Studio</button></div> : <div className="studio-concept-view"><div className="studio-player-title"><span className={`chat-mode-icon mode-${modeFor(openedSet.kind, openedSet.title).id}`}>{modeFor(openedSet.kind, openedSet.title).icon}</span><h4>{openedSet.title}</h4></div><p className="studio-kind-caption">Study material · source-linked</p>{openedSet.items?.map((item, index) => <article className="studio-concept" key={item.id}><span>{index + 1}</span><div><small>{item.topic}</small><strong>{item.prompt}</strong><p>{item.answer}</p>{item.explanation && <p>{item.explanation}</p>}{item.citations?.length ? <details className="studio-citations"><summary>Evidence · {item.citations.length}</summary>{item.citations.map((citation) => <blockquote key={citation.id}><strong>{citation.source_name} · {citation.locator}</strong><p>{citation.text}</p></blockquote>)}</details> : null}</div></article>)}<button className="studio-secondary" onClick={closeViewer}>Back to Studio</button></div>)}
      </> : <>
        <div className="chat-mode-grid">{modes.map((mode) => <button className={`chat-mode-card mode-card-${mode.id}`} key={mode.id} onClick={() => openSetup(mode)}><span className={`chat-mode-icon mode-${mode.id}`}>{mode.icon}</span><strong>{mode.title}</strong><small>{mode.detail}</small></button>)}</div>
        {error && <div className="studio-error" role="alert">{error}</div>}
        {generatingMode && <div className="studio-generating" role="status"><span className="studio-spinner" /><div><strong>Generating {modes.find((mode) => mode.id === generatingMode)?.title}</strong><small>Scanning {sourceIds.length} selected class sources and saving the result.</small></div></div>}
        {generationAudit?.courseId === studioCourseId && generationAudit.coverage && <div className={`studio-coverage-notice ${generationAudit.coverage.complete ? 'complete' : 'partial'}`} role="status"><strong>{generationAudit.coverage.complete ? 'Source scan complete' : 'Some source text was unavailable or limited'}</strong><p>Scanned {generationAudit.coverage.scanned_sources} of {generationAudit.coverage.selected_sources} selected sources, including {generationAudit.coverage.pdf_pages_scanned} PDF pages. Sent {generationAudit.coverage.returned_chunks} topic-matched passages to the study generator.</p>{generationAudit.warnings.length > 0 && <details><summary>Coverage details · {generationAudit.warnings.length}</summary><ul>{generationAudit.warnings.slice(0, 8).map((warning) => <li key={warning}>{warning}</li>)}</ul></details>}</div>}
        <section className="studio-library"><header><div><p className="eyebrow">Your study materials</p><h4>{currentCourse?.code ?? 'Choose a class'}</h4></div><span>{loadingOverview ? '…' : overview?.sets.length ?? 0}</span></header>
          {overview?.sets.slice().reverse().map((record) => <button type="button" className={`studio-set-row ${newSetId === record.id ? 'new' : ''}`} key={record.id} disabled={busy || Boolean(record.stale_sources?.length)} onClick={() => void openSet(record)}><span className={`chat-mode-icon mode-${modeFor(record.kind, record.title).id}`}>{modeFor(record.kind, record.title).icon}</span><span><strong>{record.title}</strong><small>{record.item_count ?? 0} items · {modeFor(record.kind, record.title).title}{record.stale_sources?.length ? ' · source changed' : ''}</small></span><b>›</b></button>)}
          {currentCourse && !loadingOverview && !overview?.sets.length && <p className="studio-library-empty">Generated quizzes, flashcards, guides, explanations, and maps will be saved here for this class.</p>}
          {!currentCourse && <p className="studio-library-empty">Choose a class in a study mode to see its saved materials.</p>}
        </section>
      </>}
    </aside>

    {setupMode && <div className="studio-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setSetupMode(null) }}><section className="studio-dialog" role="dialog" aria-modal="true" aria-labelledby="studio-dialog-title">
      <header><div><p className="eyebrow">Guided study setup</p><h3 id="studio-dialog-title"><span className={`chat-mode-icon mode-${setupMode.id}`}>{setupMode.icon}</span>{setupMode.title}</h3><p>Optionally add a focus, then choose the class material to use. Your generated set will be saved in this class’s Study library.</p></div><button className="studio-close" onClick={() => setSetupMode(null)} aria-label="Close setup">×</button></header>
      <div className="studio-dialog-content">
        <div className="studio-form-row"><label className="studio-label">Class<select value={studioCourseId} onChange={(event) => selectCourse(event.target.value)}><option value="">Choose a class</option>{courses.map((entry) => <option value={entry.id} key={entry.id}>{entry.code} · {entry.name}</option>)}</select></label>{setupMode.id === 'map' ? <div className="studio-auto-count"><strong>Map sections</strong><span>Set automatically from your prompt or selected sources</span></div> : <label className="studio-label studio-count-label">{setupMode.id === 'quiz' ? 'Number of questions' : setupMode.id === 'flashcards' ? 'Number of cards' : 'Number of sections'}<input type="number" min={1} max={30} value={count} onChange={(event) => setCount(Number(event.target.value))} /></label>}</div>
        <div className="studio-form-row"><DialogChoice label={setupMode.id === 'quiz' || setupMode.id === 'flashcards' ? 'Level of difficulty' : setupMode.focusLabel} value={setupMode.id === 'quiz' || setupMode.id === 'flashcards' ? difficulty : focus} values={setupMode.id === 'quiz' || setupMode.id === 'flashcards' ? difficulties : focusChoices[setupMode.id]} onChange={setupMode.id === 'quiz' || setupMode.id === 'flashcards' ? setDifficulty : setFocus} />{(setupMode.id === 'quiz' || setupMode.id === 'flashcards') && <DialogChoice label={setupMode.focusLabel} value={focus} values={focusChoices[setupMode.id]} onChange={setFocus} />}</div>
        <label className="studio-label studio-topic-label"><span className="studio-topic-heading">{setupMode.topicLabel}<small>Optional</small></span><span className="studio-topic-hint">Leave this blank and Academia will choose a useful focus from the selected sources and saved class context.</span><textarea value={topic} onChange={(event) => setTopic(event.target.value)} placeholder={setupMode.placeholder} rows={4} maxLength={500} /></label>
        {(upcomingExam || topicToReview) && <div className="studio-context-suggestions"><span>From your saved class context</span>{upcomingExam && <button type="button" onClick={() => { setSelectedExamId(upcomingExam.id); setTopic(`Prepare me for ${upcomingExam.title}${upcomingExam.topics.length ? `, focusing on ${upcomingExam.topics.join(', ')}` : ''}.`) }}>Prepare for {upcomingExam.title}{upcomingExam.date ? ` · ${upcomingExam.date}` : ''}</button>}{topicToReview && <button type="button" onClick={() => { setSelectedExamId(''); setTopic(`Help me review ${topicToReview.topic}. Use my past practice on this topic to focus on what I still need to understand.`) }}>Revisit {topicToReview.topic}</button>}</div>}
        <div className="studio-source-setup"><div className="studio-source-setup-heading"><div><strong>Sources</strong><small>{sourceIds.length} selected · {courseSources.length} available in {currentCourse?.code ?? 'the chosen class'}</small></div><button className="studio-source-toggle" type="button" disabled={!courseSources.length} aria-expanded={sourceListOpen} onClick={() => setSourceListOpen((open) => !open)}>{sourceListOpen ? 'Hide sources' : 'Choose sources'} <span>{sourceListOpen ? '⌃' : '⌄'}</span></button></div>
          {sourceListOpen && <div className="studio-source-picker" ref={sourcePickerRef}><label className="studio-source-search"><span>⌕</span><input value={sourceSearch} onChange={(event) => setSourceSearch(event.target.value)} placeholder={`Search ${currentCourse?.code ?? 'class'} sources`} /></label><button type="button" className="studio-source-bulk" onClick={toggleVisibleSources} disabled={!filteredSources.length}>{allFilteredSelected ? 'Uncheck visible' : 'Check visible'}</button><div className="studio-source-list">{filteredSources.map((item) => <label key={item.id} className={sourceIds.includes(item.id) ? 'selected' : ''}><input type="checkbox" checked={sourceIds.includes(item.id)} onChange={() => { scopeEditedRef.current = true; setSourceIds((current) => current.includes(item.id) ? current.filter((id) => id !== item.id) : [...current, item.id]) }} /><span><strong>{item.name}</strong><small>{item.category} · {item.extension.toUpperCase()}</small></span></label>)}{!filteredSources.length && <p>No sources found for this class.</p>}</div></div>}
          <small className="studio-source-footnote">A deep search scans checked source text and supplies excerpts for your focus or a balanced class overview. Up to 300 sources can be scanned per set.</small>
        </div>
        {setupMode.id === 'compare' && sourceIds.length < 2 && <p className="studio-inline-hint">Select at least two sources to compare them.</p>}
        {error && <div className="studio-error" role="alert">{error}</div>}
      </div>
      <footer><span>{selectedCourseSources.length} sources · Deep text search · Saved to class</span><button className="studio-primary" disabled={busy || !currentCourse || sourceIds.length === 0 || sourceIds.length > 300 || (setupMode.id === 'compare' && sourceIds.length < 2) || count < 1 || count > 30} onClick={() => void generate()}>{busy ? 'Generating…' : 'Generate study material'}</button></footer>
    </section></div>}
  </>
}
