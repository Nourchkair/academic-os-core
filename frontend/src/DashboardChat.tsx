import { useEffect, useMemo, useRef, useState, type ClipboardEvent as ReactClipboardEvent } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import rehypeKatex from 'rehype-katex'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import { api } from './lib/api'
import { ChatProposals } from './ChatProposals'
import { deleteChatConversation, listChatConversations, saveChatConversation, stripChatAttachmentPreviews, type ChatConversation, type ChatMessage, type ChatProposal, type StudyChatRequest } from './lib/chat-history'
import { ChatStudyStudio, type ChatStudyRequest, type ModeId } from './ChatStudyStudio'
import type { Course, CourseworkHistoryRecord, LibraryItem, Task } from './types'
import 'katex/dist/katex.min.css'
import './dashboard-chat.css'

type Message = ChatMessage
type ChatProviderInfo = {
  id: 'codex' | 'claude'
  name: string
  installed: boolean | null
  authenticated: boolean | null
  available: boolean
  models: { id: string; name: string }[]
  default_model: string
  notice: string
  billing: string
  reason?: string
}
type ChatProviders = {
  default_provider?: string
  providers?: ChatProviderInfo[]
  chat?: { default_provider?: string; providers?: ChatProviderInfo[] }
  available?: boolean
  version?: string | null
  models?: { id: string; name: string }[]
  default_model?: string | null
  notice?: string | null
  codex?: { installed: boolean; effective_model?: string | null; models?: { id: string; name: string }[]; notice?: string | null }
}
type Attachment = { name: string; type: string; data: string; preview: string; size: number }
type ChatResult = { message: string; model: string | null; effort: string; speed: string; notice: string | null; proposal_mode?: boolean; proposals?: ChatProposal[] }
type StudySourceContext = {
  sources?: Array<{ id: string; name: string; complete?: boolean; pages_scanned?: number | null; page_count?: number | null }>
  chunks: { source_name: string; locator: string; text: string }[]
  warnings: string[]
  coverage?: { deep: boolean; selected_sources: number; scanned_sources: number; complete: boolean; pdf_pages_scanned: number; matching_chunks: number; returned_chunks: number }
}
type StudyOverview = {
  topics?: Array<{ topic: string; item_count?: number; needs_review?: boolean; attempt_count?: number; correct_count?: number; self_review_count?: number }>
  annotations?: Array<{ id: string; kind: string; topic?: string; note: string; quote?: string; citation?: { source_name?: string; locator?: string }; stale_source?: { source_id: string; reason: string } | null }>
  exams?: Array<{ id: string; title: string; date?: string | null; format?: string; topics?: string[]; objectives?: string[]; source_ids?: string[] }>
  sessions?: Array<{ id: string; set_id: string; title: string; status: string; created_at: string; mode?: string; score?: { correct: number; graded: number; self_assessed: number } }>
  attempt_count?: number
  due_count?: number
}
type CourseAcademicContext = { courseId: string; tasks: Task[]; history: CourseworkHistoryRecord[]; study: StudyOverview | null; unavailable: string[] }
type HistoryEntry = { course: Course; session: NonNullable<StudyOverview['sessions']>[number] }
type ChatSuggestion = { label: string; prompt: string }
type ChatStudyDraft = { mode: ModeId; topic: string; count?: number; difficulty?: string; focus?: string; examId?: string; suggestedExam?: { id: string; title: string; date?: string | null; topics: string[] } }

const chatStudyModes: { mode: ModeId; expression: RegExp; defaultCount: number }[] = [
  { mode: 'flashcards', expression: /flash\s*cards?/i, defaultCount: 12 },
  { mode: 'guide', expression: /study\s+guide|review\s+guide|\bguide\b/i, defaultCount: 8 },
  { mode: 'map', expression: /mind\s+map|concept\s+map/i, defaultCount: 12 },
  { mode: 'compare', expression: /compare(?:\s+and\s+contrast)?(?:\s+(?:these|my|the))?\s+(?:sources|readings|materials)/i, defaultCount: 5 },
  { mode: 'quiz', expression: /quiz|practice\s+test|practice\s+exam/i, defaultCount: 8 },
  { mode: 'explain', expression: /explain|explanation|break\s+down/i, defaultCount: 4 },
]

function extractStudyPreferences(text: string, mode: ModeId, allowBareCount = false) {
  const countMatch = text.match(/\b(\d{1,2})\s+(?:questions?|cards?|sections?|items?)\b/i) ?? (allowBareCount ? text.match(/^\s*(\d{1,2})\s*(?:[,.;]|$)/) : null)
  const difficultyMatch = text.match(/\b(easy|medium|hard)(?:\s+difficulty)?\b/i)
  let focus: string | undefined
  if (mode === 'quiz') {
    if (/multiple[ -]?choice/i.test(text)) focus = 'Multiple choice'
    else if (/short[ -]?answer|open[ -]?ended/i.test(text)) focus = 'Short answer'
    else if (/\bmixed\b/i.test(text)) focus = 'Mixed'
  } else if (mode === 'flashcards') {
    if (/key\s+terms?|definitions?/i.test(text)) focus = 'Key terms'
    else if (/concepts?(?:\s+and\s+examples)?/i.test(text)) focus = 'Concepts & examples'
    else if (/\bmixed\b/i.test(text)) focus = 'Mixed'
  }
  const cleaned = text
    .replace(/\b\d{1,2}\s+(?:questions?|cards?|sections?|items?)\b/gi, ' ')
    .replace(/\b(?:at\s+|level\s+)?(?:easy|medium|hard)(?:\s+difficulty)?\b/gi, ' ')
    .replace(/\b(?:multiple[ -]?choice|short[ -]?answer|open[ -]?ended|mixed|key\s+terms?|definitions?|concepts?(?:\s+and\s+examples)?)\b/gi, ' ')
    .replace(/\b(?:difficulty|question\s+type|card\s+style)\b/gi, ' ')
    .replace(/\s+(?:with|at|and|plus)\s*$/i, '')
    .replace(/^(?:from|of|in|for)\s+/i, '')
    .replace(/^[\s,.;:!?-]+|[\s,.;:!?-]+$/g, '')
    .replace(/\s+/g, ' ')
  const count = countMatch ? Math.max(1, Math.min(30, Number(countMatch[1]))) : undefined
  return { topic: cleaned, count, difficulty: difficultyMatch ? `${difficultyMatch[1][0].toUpperCase()}${difficultyMatch[1].slice(1).toLowerCase()}` : undefined, focus }
}

function detectChatStudyCreation(text: string): ChatStudyDraft | null {
  const action = /\b(?:create|make|generate|build|prepare|design)\b|\bquiz\s+me\b|\bturn\b/i.test(text)
  if (!action) return null
  const matched = chatStudyModes.map((entry) => ({ ...entry, match: entry.expression.exec(text) })).find((entry) => entry.match)
  if (!matched?.match) return null
  const match = matched.match
  let tail = text.slice(match.index + match[0].length)
  const scope = tail.match(/\b(?:on|about|cover(?:ing)?|for|from|based\s+on)\s+([\s\S]*)/i)?.[1]
  if (scope) tail = scope
  else if (/\bturn\b/i.test(text)) tail = text.match(/\bturn\s+([\s\S]+?)\s+into\b/i)?.[1] ?? tail
  tail = tail.replace(/^(?:\s*(?:me|for me|a|an|the|please|class|course)\b\s*)+/i, '')
  const details = extractStudyPreferences(tail, matched.mode)
  const requestPreferences = extractStudyPreferences(text, matched.mode)
  const genericScope = /^(?:it|this|that|everything|all(?:\s+the)?\s+(?:sources|materials))$/i.test(details.topic)
  const requiresActionForExplain = matched.mode !== 'explain' || /\b(?:create|make|generate|build|prepare|design)\b/i.test(text)
  return { mode: matched.mode, topic: genericScope || !requiresActionForExplain ? '' : details.topic, count: requestPreferences.count ?? details.count, difficulty: requestPreferences.difficulty ?? details.difficulty, focus: requestPreferences.focus ?? details.focus }
}

function studyModeDefaults(mode: ModeId) {
  if (mode === 'quiz') return { count: 8, focus: 'Mixed' }
  if (mode === 'flashcards') return { count: 12, focus: 'Mixed' }
  if (mode === 'guide') return { count: 8, focus: 'Standard' }
  if (mode === 'map') return { count: 12, focus: 'Standard' }
  if (mode === 'compare') return { count: 5, focus: 'Both' }
  return { count: 4, focus: 'Step by step' }
}

const effortOptions = [['minimal', 'Minimal'], ['low', 'Low'], ['medium', 'Medium'], ['high', 'High'], ['xhigh', 'Extra high'], ['max', 'Maximum']] as const
const readableExtensions = new Set(['.pdf', '.md', '.markdown', '.txt', '.docx', '.pptx'])
const attachmentFormats: Record<string, { mime: string; acceptedMime: string[] }> = {
  '.pdf': { mime: 'application/pdf', acceptedMime: ['application/pdf', 'application/octet-stream'] },
  '.png': { mime: 'image/png', acceptedMime: ['image/png'] },
  '.jpg': { mime: 'image/jpeg', acceptedMime: ['image/jpeg', 'image/jpg'] },
  '.jpeg': { mime: 'image/jpeg', acceptedMime: ['image/jpeg', 'image/jpg'] },
  '.webp': { mime: 'image/webp', acceptedMime: ['image/webp'] },
  '.gif': { mime: 'image/gif', acceptedMime: ['image/gif'] },
  '.docx': { mime: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', acceptedMime: ['application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'application/zip', 'application/octet-stream'] },
  '.pptx': { mime: 'application/vnd.openxmlformats-officedocument.presentationml.presentation', acceptedMime: ['application/vnd.openxmlformats-officedocument.presentationml.presentation', 'application/zip', 'application/octet-stream'] },
  '.txt': { mime: 'text/plain', acceptedMime: ['text/plain', 'application/octet-stream'] },
  '.text': { mime: 'text/plain', acceptedMime: ['text/plain', 'application/octet-stream'] },
  '.md': { mime: 'text/markdown', acceptedMime: ['text/markdown', 'text/x-markdown', 'text/plain', 'application/octet-stream'] },
  '.markdown': { mime: 'text/markdown', acceptedMime: ['text/markdown', 'text/x-markdown', 'text/plain', 'application/octet-stream'] },
  '.csv': { mime: 'text/csv', acceptedMime: ['text/csv', 'application/csv', 'text/plain', 'application/octet-stream'] },
  '.json': { mime: 'application/json', acceptedMime: ['application/json', 'text/json', 'text/plain', 'application/octet-stream'] },
  '.yaml': { mime: 'text/yaml', acceptedMime: ['text/yaml', 'application/x-yaml', 'text/plain', 'application/octet-stream'] },
  '.yml': { mime: 'text/yaml', acceptedMime: ['text/yaml', 'application/x-yaml', 'text/plain', 'application/octet-stream'] },
}
const attachmentExtensionByMime: Record<string, string> = {
  'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp', 'image/gif': '.gif', 'application/pdf': '.pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation': '.pptx',
  'text/plain': '.txt', 'text/markdown': '.md', 'text/x-markdown': '.md', 'text/csv': '.csv',
  'application/csv': '.csv', 'application/json': '.json', 'text/json': '.json', 'text/yaml': '.yaml', 'application/x-yaml': '.yaml',
}
const chatMarkdownComponents: Components = {
  a: ({ href, children }) => href ? <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> : <span>{children}</span>,
  img: ({ alt }) => <span className="chat-image-note">{alt || 'Image'} · open the source to view</span>,
}

function makeClassSuggestions(course: Course | undefined, context: CourseAcademicContext | null, sources: LibraryItem[]): ChatSuggestion[] {
  if (!course) return []
  const today = new Date().toISOString().slice(0, 10)
  const exam = (context?.study?.exams ?? []).find((entry) => !entry.date || entry.date >= today)
  const planned = (context?.history ?? []).find((entry) => (entry.status === 'planned' || entry.status === 'in_progress') && (!entry.due_date || entry.due_date >= today))
  const upcomingTask = (context?.tasks ?? []).find((entry) => !entry.completed && entry.due_date && entry.due_date >= today)
  const recentPastAssessment = (context?.history ?? []).filter((entry) => ['quiz', 'exam'].includes(entry.kind) && ['submitted', 'graded', 'completed'].includes(entry.status)).slice().sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0]
  const next = exam ? { title: exam.title, dueDate: exam.date, source: 'saved exam scope', recordStatus: 'student-confirmed scope', isExam: true }
    : planned ? { title: planned.title, dueDate: planned.due_date, source: 'coursework history', recordStatus: `${planned.status}; ${planned.record_basis}`, isExam: false }
      : upcomingTask ? { title: upcomingTask.title, dueDate: upcomingTask.due_date, source: 'course task list', recordStatus: `confidence ${upcomingTask.confidence}`, isExam: upcomingTask.kind === 'exam' } : null
  const topicProgress = (context?.study?.topics ?? []).filter((entry) => (entry.attempt_count ?? 0) > 0)
  const topic = topicProgress.find((entry) => entry.needs_review) ?? topicProgress.slice().sort((a, b) => {
    const aChecked = Math.max(0, (a.attempt_count ?? 0) - (a.self_review_count ?? 0))
    const bChecked = Math.max(0, (b.attempt_count ?? 0) - (b.self_review_count ?? 0))
    const aRate = aChecked ? (a.correct_count ?? 0) / aChecked : 1
    const bRate = bChecked ? (b.correct_count ?? 0) / bChecked : 1
    return aRate - bRate || (b.attempt_count ?? 0) - (a.attempt_count ?? 0)
  })[0]
  const topicAttemptCount = topic?.attempt_count ?? 0
  const topicSelfReviews = topic?.self_review_count ?? 0
  const topicCheckedCount = Math.max(0, topicAttemptCount - topicSelfReviews)
  const topicCorrectCount = topic?.correct_count ?? 0
  const source = sources.find((entry) => ['readings', 'notes', 'syllabi'].includes(entry.category))
  const recentPracticeSession = (context?.study?.sessions ?? []).filter((session) => (session.score?.graded ?? 0) > 0 || (session.score?.self_assessed ?? 0) > 0).slice().sort((a, b) => b.created_at.localeCompare(a.created_at))[0]
  const pastCourseworkNote = recentPastAssessment
    ? ` My coursework history records ${recentPastAssessment.title} (${recentPastAssessment.kind}) as ${recentPastAssessment.status}${recentPastAssessment.grade ? ` with grade ${recentPastAssessment.grade}` : ''}${recentPastAssessment.submitted_on ? ` on ${recentPastAssessment.submitted_on}` : ''}; ask what I want to improve from it.`
    : ''
  const pastPracticeNote = recentPracticeSession
    ? ` My latest saved practice session, “${recentPracticeSession.title},”${recentPracticeSession.score!.graded ? ` has ${recentPracticeSession.score!.correct}/${recentPracticeSession.score!.graded} answer-key checks correct` : ''}${recentPracticeSession.score!.self_assessed ? ` has ${recentPracticeSession.score!.self_assessed} self-assessments` : ''}; use that as a practice signal and ask what I want to work on.`
    : ''
  const pastAssessmentNote = `${pastCourseworkNote}${pastPracticeNote}`
  const assessmentSuggestion = next
    ? { label: `${next.isExam ? 'Prepare for' : 'Review'} ${next.title}`, prompt: `My ${course.code} ${next.source} lists “${next.title}”${next.dueDate ? ` for ${next.dueDate}` : ''} (${next.recordStatus}). Help me prepare using relevant class sources and any saved exam scope. Consider my earlier coursework and saved practice results when recommending what to revisit, but don't treat them as a grade or mastery claim. If the record or study scope is uncertain, ask me to confirm it before relying on it.` }
    : { label: `Plan my next ${course.code} study session`, prompt: `Help me decide what to study next in ${course.code}. Use recorded coursework, study progress, and the source catalog to recommend a focused plan; ask me if there are multiple good options.` }
  const reviewSuggestion = topic
    ? { label: `${topic.needs_review ? 'Revisit' : 'Continue'} ${topic.topic}`, prompt: `Help me review ${topic.topic} in ${course.code}. My saved study progress shows ${topicAttemptCount} practice attempts${topicCheckedCount ? `, ${topicCorrectCount} correct in answer-key checks out of ${topicCheckedCount}` : ''}${topicSelfReviews ? `, and ${topicSelfReviews} self-assessments` : ''}${topic.needs_review ? ', with a recent result or self-rating marked for review' : ''}.${pastAssessmentNote} Treat practice and coursework records as context, not a grade or mastery claim. Use relevant class sources, ask if I want to focus here, then start with a short diagnostic question and adapt to my answer.` }
    : source ? { label: `Quiz me on ${source.name.slice(0, 28)}${source.name.length > 28 ? '…' : ''}`, prompt: `Quiz me one question at a time on the key ideas in ${source.name} for ${course.code}.${pastAssessmentNote} Use relevant excerpts, keep track of what I find difficult in this conversation, and adjust the next question based on my answers.` }
      : { label: 'Find a topic to review', prompt: `Look at my saved practice progress and course sources for ${course.code}. Recommend one topic worth reviewing and explain why, then help me practice it.` }
  const explainSuggestion = source
    ? { label: `Explain ${source.name.slice(0, 34)}${source.name.length > 34 ? '…' : ''}`, prompt: `Help me understand the key ideas in ${source.name} for ${course.code}.${pastAssessmentNote} Use its relevant excerpts, explain any difficult concepts step by step, and ask what is still unclear.` }
    : { label: 'Explain an idea I found confusing', prompt: `Help me understand an idea from ${course.code} that I found confusing. Use my course sources to suggest a likely focus, then ask one clear question if you need me to identify the concept.` }
  return [assessmentSuggestion, reviewSuggestion, explainSuggestion]
}

export function DashboardChat({ courses, items, semester, onOpenReview, onProposalCreated, onResumeStudySession, studyChatRequest, onStudyChatRequestConsumed }: { courses: Course[]; items: LibraryItem[]; semester: string; onOpenReview: (reviewId: string) => void; onProposalCreated: () => void; onResumeStudySession: (courseId: string, sessionId: string) => void; studyChatRequest: StudyChatRequest | null; onStudyChatRequestConsumed: () => void }) {
  const [providers, setProviders] = useState<ChatProviders | null>(null)
  const [provider] = useState<'codex'>('codex')
  const [messages, setMessages] = useState<Message[]>([])
  const [pendingChatStudy, setPendingChatStudy] = useState<ChatStudyDraft | null>(null)
  const [chatStudyRequest, setChatStudyRequest] = useState<ChatStudyRequest | null>(null)
  const [studyGenerationInProgress, setStudyGenerationInProgress] = useState(false)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [courseId, setCourseId] = useState('')
  const [sourceIds, setSourceIds] = useState<string[]>([])
  const [excludedCourseSourceIds, setExcludedCourseSourceIds] = useState<string[]>([])
  const [lastRetrievedSourceIds, setLastRetrievedSourceIds] = useState<string[]>([])
  const [academicContext, setAcademicContext] = useState<CourseAcademicContext | null>(null)
  const [sourceFilter, setSourceFilter] = useState('')
  const [sourcePickerFilter, setSourcePickerFilter] = useState('')
  const [attachments, setAttachments] = useState<File[]>([])
  const [chatAttachments, setChatAttachments] = useState<Attachment[]>([])
  const [model, setModel] = useState('')
  const [effort, setEffort] = useState('medium')
  const [speed, setSpeed] = useState(localStorage.getItem('academia.chat.speed') || 'standard')
  const [proposalMode, setProposalMode] = useState(() => localStorage.getItem('academia.chat.proposals') === 'true')
  const [showAttachMenu, setShowAttachMenu] = useState(false)
  const [showSourcePicker, setShowSourcePicker] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState('')
  const [historyEntries, setHistoryEntries] = useState<HistoryEntry[]>([])
  const [conversationHistory, setConversationHistory] = useState<ChatConversation[]>([])
  const [conversationHistoryLoading, setConversationHistoryLoading] = useState(true)
  const [conversationHistoryError, setConversationHistoryError] = useState('')
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null)
  const [openPicker, setOpenPicker] = useState<string | null>(null)
  const [sourcesOpen, setSourcesOpen] = useState(true)
  const [studioOpen, setStudioOpen] = useState(true)
  const listRef = useRef<HTMLDivElement>(null)
  const messagesRef = useRef<Message[]>([])
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const sourceFilterRef = useRef<HTMLInputElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const handledStudyChatRequest = useRef('')

  const course = courses.find((entry) => entry.id === courseId)
  useEffect(() => { messagesRef.current = messages }, [messages])
  const makeConversationSnapshot = (conversationMessages: Message[], id = activeConversationId || crypto.randomUUID()): ChatConversation => {
    const firstUserMessage = conversationMessages.find((message) => message.role === 'user')?.content.replace(/\s+/g, ' ').trim()
    const title = firstUserMessage ? firstUserMessage.slice(0, 72) : 'Study conversation'
    return stripChatAttachmentPreviews({
      id,
      title: title.length === 72 ? `${title.slice(0, 69)}…` : title,
      courseId,
      courseLabel: course ? `${course.code} · ${course.name}` : 'General study chat',
      messages: conversationMessages,
      sourceIds,
      excludedCourseSourceIds,
      updatedAt: new Date().toISOString(),
    })
  }
  const persistConversation = async (conversationMessages: Message[], id = activeConversationId || crypto.randomUUID()) => {
    const updated = makeConversationSnapshot(conversationMessages, id)
    setConversationHistory((current) => [updated, ...current.filter((conversation) => conversation.id !== id)].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)))
    setActiveConversationId(id)
    try {
      await saveChatConversation(updated)
      setConversationHistoryError('')
    } catch (reason) {
      setConversationHistoryError(`This conversation is visible for now, but could not be saved on this device. ${String(reason)}`)
    }
  }
  const suggestions = useMemo(() => makeClassSuggestions(course, academicContext, items.filter((item) => item.course_id === courseId && readableExtensions.has(item.extension.toLowerCase()))), [academicContext, course, courseId, items])
  const readableItems = useMemo(() => items.filter((item) => readableExtensions.has(item.extension.toLowerCase())), [items])
  const selectedItems = useMemo(() => readableItems.filter((item) => {
    if (courseId && item.course_id === courseId) return !excludedCourseSourceIds.includes(item.id)
    return sourceIds.includes(item.id)
  }), [courseId, excludedCourseSourceIds, readableItems, sourceIds])
  const availableSourceCount = course ? selectedItems.filter((item) => item.course_id === courseId).length : selectedItems.length
  const selectedSourceIdSet = useMemo(() => new Set(selectedItems.map((item) => item.id)), [selectedItems])
  const lastRetrievedSourceIdSet = useMemo(() => new Set(lastRetrievedSourceIds), [lastRetrievedSourceIds])
  const academicContextLoading = Boolean(courseId && academicContext?.courseId !== courseId)
  const filteredItems = useMemo(() => {
    const query = sourceFilter.trim().toLocaleLowerCase()
    return readableItems.filter((item) => {
      if (courseId && item.course_id !== courseId) return false
      if (!query) return true
      const owner = courses.find((entry) => entry.id === item.course_id)
      return `${item.name} ${item.relative_path} ${owner?.code || ''} ${owner?.name || ''}`.toLocaleLowerCase().includes(query)
    })
  }, [courseId, courses, readableItems, sourceFilter])
  const allVisibleSourcesSelected = filteredItems.length > 0 && filteredItems.every((item) => selectedSourceIdSet.has(item.id))
  const sourceGroups = useMemo(() => {
    const groups = new Map<string, { name: string; items: LibraryItem[] }>()
    for (const item of filteredItems) {
      const key = item.course_id || 'semester'
      const owner = courses.find((entry) => entry.id === item.course_id)
      const name = owner ? `${owner.code} · ${owner.name}` : `${item.semester} · Semester files`
      const group = groups.get(key) || { name, items: [] }
      group.items.push(item)
      groups.set(key, group)
    }
    return [...groups.entries()].sort(([a], [b]) => a === courseId ? -1 : b === courseId ? 1 : groups.get(a)!.name.localeCompare(groups.get(b)!.name))
  }, [courseId, courses, filteredItems])
  const pickerGroups = useMemo(() => {
    const query = sourcePickerFilter.trim().toLocaleLowerCase()
    const groups = new Map<string, { name: string; items: LibraryItem[] }>()
    for (const item of readableItems) {
      if (courseId && item.course_id === courseId) continue
      const owner = courses.find((entry) => entry.id === item.course_id)
      const key = item.course_id || 'semester'
      const name = owner ? `${owner.code} · ${owner.name}` : `${item.semester} · Semester files`
      if (query && !`${item.name} ${item.relative_path} ${name}`.toLocaleLowerCase().includes(query)) continue
      const group = groups.get(key) || { name, items: [] }
      group.items.push(item)
      groups.set(key, group)
    }
    return [...groups.entries()].sort(([, a], [, b]) => a.name.localeCompare(b.name))
  }, [courseId, courses, readableItems, sourcePickerFilter])

  const providerCatalog = providers?.chat ?? providers
  const providerOptions = providerCatalog?.providers ?? []
  const activeProvider = providerOptions.find((entry) => entry.id === provider)
  const modelOptions = activeProvider?.models ?? []
  const defaultModel = activeProvider?.default_model ?? ''
  const isAvailable = Boolean(activeProvider?.available)
  const statusLabel = `${activeProvider?.name ?? provider} · ${isAvailable ? 'connected' : 'not connected'}`
  const thinkingOptions = effortOptions

  useEffect(() => {
    const savedModel = localStorage.getItem(`academia.chat.model.${provider}`) ?? (provider === 'codex' ? localStorage.getItem('academia.chat.model') : null) ?? ''
    const savedEffort = localStorage.getItem(`academia.chat.effort.${provider}`) ?? localStorage.getItem('academia.chat.effort') ?? 'medium'
    setModel(savedModel)
    setEffort(effortOptions.some(([value]) => value === savedEffort) ? savedEffort : 'medium')
  }, [provider])

  useEffect(() => { void api.chatProviders<ChatProviders>().then(setProviders).catch((reason) => setError(String(reason))) }, [])
  useEffect(() => {
    let current = true
    void listChatConversations().then((conversations) => {
      if (current) setConversationHistory(conversations)
    }).catch((reason) => {
      if (current) setConversationHistoryError(`Saved conversations could not be loaded from this device. ${String(reason)}`)
    }).finally(() => {
      if (current) setConversationHistoryLoading(false)
    })
    return () => { current = false }
  }, [])
  useEffect(() => {
    if (!courseId) return
    let current = true
    void Promise.allSettled([
      api.agentCourseContext(courseId, semester),
      api.courseworkHistory(courseId, semester),
      api.study<StudyOverview>(['overview', '--course', courseId, ...(semester ? ['--semester', semester] : [])]),
    ]).then(async ([tasksResult, historyResult, studyResult]) => {
      if (!current) return
      const tasks = tasksResult.status === 'fulfilled' ? tasksResult.value.current_state?.open_tasks ?? [] : []
      const history = historyResult.status === 'fulfilled' ? historyResult.value : []
      const overview = studyResult.status === 'fulfilled' ? studyResult.value : null
      const sessionResults = overview?.sessions?.slice(-6) ?? []
      const sessionDetails = await Promise.allSettled(sessionResults.map((session) => api.study<{ id: string; score?: { correct: number; graded: number; self_assessed: number } }>([
        'session', '--course', courseId, ...(semester ? ['--semester', semester] : []), '--session', session.id,
      ])))
      if (!current) return
      const scores = new Map(sessionDetails.flatMap((result) => result.status === 'fulfilled' ? [[result.value.id, result.value.score] as const] : []))
      const study = overview ? { ...overview, sessions: overview.sessions?.map((session) => ({ ...session, score: scores.get(session.id) })) } : null
      const unavailable: string[] = []
      if (tasksResult.status === 'rejected') unavailable.push('course task records')
      if (historyResult.status === 'rejected') unavailable.push('coursework history')
      if (studyResult.status === 'rejected') unavailable.push('saved study scope')
      setAcademicContext({ courseId, tasks, history, study, unavailable })
    })
    return () => { current = false }
  }, [courseId, semester])
  useEffect(() => { listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' }) }, [messages, busy])
  useEffect(() => {
    const closeDropdowns = (event: PointerEvent) => {
      const target = event.target
      if (!(target instanceof Element)) return
      if (!target.closest('.chat-picker')) setOpenPicker(null)
      if (!target.closest('.chat-attach-anchor, .chat-attach-menu')) setShowAttachMenu(false)
    }
    const closeDropdownsOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpenPicker(null)
        setShowAttachMenu(false)
        setShowSourcePicker(false)
        setHistoryOpen(false)
      }
    }
    document.addEventListener('pointerdown', closeDropdowns)
    document.addEventListener('keydown', closeDropdownsOnEscape)
    return () => {
      document.removeEventListener('pointerdown', closeDropdowns)
      document.removeEventListener('keydown', closeDropdownsOnEscape)
    }
  }, [])

  const send = async () => {
    const text = draft.trim()
    if ((!text && !attachments.length) || busy || studyGenerationInProgress) return
    const pendingAttachments = [...attachments]
    const userMessage: Message = { role: 'user', content: text || `Please review ${pendingAttachments.map((file) => file.name).join(', ')}.` }
    let nextMessages = [...messages, userMessage]
    setMessages(nextMessages)
    setDraft('')
    setAttachments([])
    setBusy(true)
    setError('')
    try {
      const newAttachments = await Promise.all(pendingAttachments.map(fileToAttachment))
      const uploaded = [...chatAttachments, ...newAttachments]
      if (uploaded.length > 5 || uploaded.reduce((sum, file) => sum + file.size, 0) > 32 * 1024 * 1024) throw new Error('This chat can keep up to five attachments and 32 MB in its working context. Remove an attachment or start a new chat to switch files.')
      if (newAttachments.length) {
        const sentMessage: Message = { ...userMessage, attachments: newAttachments.map(({ name, type, preview }) => ({ name, type, ...(preview ? { preview } : {}) })) }
        nextMessages = [...messages, sentMessage]
        setMessages(nextMessages)
      }

      if (!pendingAttachments.length) {
        const detectedStudy = pendingChatStudy ? null : detectChatStudyCreation(text)
        const workingDraft = pendingChatStudy ?? detectedStudy
        if (workingDraft) {
          const replyPreferences = pendingChatStudy ? extractStudyPreferences(text, workingDraft.mode, Boolean(workingDraft.topic)) : null
          const acceptsDefaults = Boolean(pendingChatStudy && /^(?:yes|yeah|yep|use defaults|defaults|go ahead|that works|sounds good)\b/i.test(text.trim()))
          const modeDefaults = studyModeDefaults(workingDraft.mode)
          let nextDraft: ChatStudyDraft = {
            ...workingDraft,
            count: replyPreferences?.count ?? workingDraft.count,
            difficulty: replyPreferences?.difficulty ?? workingDraft.difficulty,
            focus: replyPreferences?.focus ?? workingDraft.focus,
          }
          if (acceptsDefaults) nextDraft = { ...nextDraft, count: nextDraft.count ?? modeDefaults.count, difficulty: nextDraft.difficulty ?? 'Medium', focus: nextDraft.focus ?? modeDefaults.focus }
          const savedExam = academicContext?.courseId === courseId
            ? academicContext.study?.exams?.find((exam) => !exam.date || exam.date >= new Date().toISOString().slice(0, 10))
            : undefined
          if (pendingChatStudy && !workingDraft.topic) {
            const confirmsSavedScope = Boolean(workingDraft.suggestedExam && /^(?:yes|yeah|yep|use (?:it|that|the saved scope)|that one|go ahead|sounds good)\b/i.test(text.trim()))
            if (confirmsSavedScope && workingDraft.suggestedExam) {
              const exam = workingDraft.suggestedExam
              nextDraft = { ...nextDraft, topic: `${exam.title}${exam.topics.length ? `: ${exam.topics.join(', ')}` : ''}`, examId: exam.id }
            } else {
              const replyTopic = replyPreferences?.topic.replace(/^(?:no|not that)\b[,.:; -]*/i, '').replace(/^(?:please\s+)?(?:use|cover|focus on|about|on|instead)\s+/i, '').trim() ?? ''
              nextDraft = { ...nextDraft, topic: replyTopic }
            }
          }
          const refersToUnspecifiedAssessment = Boolean(!pendingChatStudy && nextDraft.topic && /\b(?:(?:my|the)\s+)?(?:(?:next|upcoming|coming)\s+)?(?:midterm|exam|quiz|test|assessment)\b/i.test(nextDraft.topic))
          if (refersToUnspecifiedAssessment) {
            nextDraft = savedExam
              ? { ...nextDraft, topic: '', suggestedExam: { id: savedExam.id, title: savedExam.title, date: savedExam.date, topics: savedExam.topics ?? [] } }
              : { ...nextDraft, topic: '' }
          }
          const saveAssistantReply = async (content: string) => {
            const completed = [...nextMessages, { role: 'assistant' as const, content }]
            messagesRef.current = completed
            setMessages(completed)
            await persistConversation(completed)
          }

          if (!course) {
            setPendingChatStudy(nextDraft)
            await saveAssistantReply(`Which class should I use? Select it in the Course context picker first. I’ll use that class’s checked sources${nextDraft.topic ? ` to make a ${nextDraft.mode === 'quiz' ? 'quiz' : nextDraft.mode === 'flashcards' ? 'flashcard set' : nextDraft.mode === 'guide' ? 'study guide' : nextDraft.mode === 'map' ? 'mind map' : nextDraft.mode === 'compare' ? 'source comparison' : 'explanation'} about ${nextDraft.topic}` : `, then ask what topic or assessment scope to cover`}.`)
            return
          }
          if (!nextDraft.topic) {
            const examHint = nextDraft.suggestedExam
              ? `Your saved class context has ${nextDraft.suggestedExam.title}${nextDraft.suggestedExam.date ? ` on ${nextDraft.suggestedExam.date}` : ''}${nextDraft.suggestedExam.topics.length ? `, covering ${nextDraft.suggestedExam.topics.join(', ')}` : ''}. Should I use that scope, or another topic?`
              : savedExam
                ? `Your saved class context includes ${savedExam.title}${savedExam.date ? ` on ${savedExam.date}` : ''}${savedExam.topics?.length ? `, covering ${savedExam.topics.join(', ')}` : ''}. Should I use that scope, or another topic?`
                : `What topics, chapters, or assessment scope should it cover? I couldn't confirm a saved upcoming exam scope for this class.`
            if (!nextDraft.suggestedExam && savedExam) nextDraft = { ...nextDraft, suggestedExam: { id: savedExam.id, title: savedExam.title, date: savedExam.date, topics: savedExam.topics ?? [] } }
            setPendingChatStudy(nextDraft)
            const defaults = studyModeDefaults(nextDraft.mode)
            const unit = nextDraft.mode === 'quiz' ? 'questions' : nextDraft.mode === 'flashcards' ? 'cards' : nextDraft.mode === 'map' ? 'concepts' : nextDraft.mode === 'explain' ? 'steps' : 'sections'
            const plan = ['quiz', 'flashcards'].includes(nextDraft.mode)
              ? `${nextDraft.count ?? defaults.count} ${unit}, medium difficulty, and ${nextDraft.focus ?? defaults.focus}`
              : `${nextDraft.count ?? defaults.count} ${unit} with ${nextDraft.focus ?? defaults.focus.toLowerCase()} detail`
            await saveAssistantReply(`${examHint} I’ll use ${plan} unless you prefer something else.`)
            return
          }
          const checkedClassSources = selectedItems.filter((item) => item.course_id === courseId)
          if (!checkedClassSources.length) {
            setPendingChatStudy(nextDraft)
            await saveAssistantReply(`There are no checked ${course.code} sources right now. Check the material you want in the Context panel, then tell me to continue. I’ll use only those checked class sources.`)
            return
          }
          const defaults = studyModeDefaults(nextDraft.mode)
          if (!acceptsDefaults && ['quiz', 'flashcards'].includes(nextDraft.mode) && (!nextDraft.count || !nextDraft.difficulty || !nextDraft.focus)) {
            setPendingChatStudy(nextDraft)
            const noun = nextDraft.mode === 'quiz' ? 'questions' : 'cards'
            const formatLabel = nextDraft.mode === 'quiz' ? 'question type' : 'card style'
            await saveAssistantReply(`How would you like this ${nextDraft.mode === 'quiz' ? 'quiz' : 'flashcard set'} set up? I can use ${nextDraft.count ?? defaults.count} ${noun}, ${nextDraft.difficulty ?? 'medium'} difficulty, and ${nextDraft.focus ?? defaults.focus.toLowerCase()} ${formatLabel}. Tell me what to change, or reply “use defaults” to start.`)
            return
          }
          const title = nextDraft.mode === 'quiz' ? 'quiz' : nextDraft.mode === 'flashcards' ? 'flashcards' : nextDraft.mode === 'guide' ? 'study guide' : nextDraft.mode === 'map' ? 'mind map' : nextDraft.mode === 'compare' ? 'source comparison' : 'explanation'
          const request: ChatStudyRequest = {
            id: crypto.randomUUID(), courseId: course.id, mode: nextDraft.mode, topic: nextDraft.topic,
            count: nextDraft.count ?? defaults.count, difficulty: nextDraft.difficulty ?? 'Medium', focus: nextDraft.focus ?? defaults.focus,
            provider, ...(model ? { model } : {}),
            ...(nextDraft.examId ? { examId: nextDraft.examId } : {}),
          }
          setPendingChatStudy(null)
          setStudyGenerationInProgress(true)
          setStudioOpen(true)
          setChatStudyRequest(request)
          await saveAssistantReply(`Got it. I’m creating a ${title} about ${nextDraft.topic} from the ${checkedClassSources.length} checked ${course.code} source${checkedClassSources.length === 1 ? '' : 's'}. It will be saved in this class’s Studio library.`)
          return
        }
      }

      const priorSearchText = messages.slice(-4).filter((message) => message.role === 'user').map((message) => message.content).join(' ').slice(-600)
      const currentSearchText = text.length > 1400 ? `${text.slice(0, 1100)} ${text.slice(-300)}` : text
      const retrievalQuery = [priorSearchText, currentSearchText].filter(Boolean).join(' ').slice(-1800)
      const assessmentIntent = /\b(midterm|exam|quiz|test|assessment|assignment|essay|paper|upcoming|coming up|due|prepare|study next)\b/i.test(retrievalQuery)
      const recordedScope = assessmentIntent && academicContext?.courseId === courseId ? [
        ...(academicContext.study?.exams ?? []).slice(0, 6).flatMap((exam) => [exam.title, ...(exam.topics ?? []).slice(0, 8), ...(exam.objectives ?? []).slice(0, 8), ...(exam.source_ids ?? []).map((id) => selectedItems.find((item) => item.id === id)?.name ?? '')]),
        ...academicContext.tasks.filter((task) => !task.completed).slice(0, 8).map((task) => task.title),
        ...academicContext.history.filter((record) => record.status === 'planned' || record.status === 'in_progress').slice(0, 8).map((record) => record.title),
        ...(academicContext.study?.topics ?? []).filter((topic) => topic.needs_review).slice(0, 12).map((topic) => topic.topic),
      ].join(' ') : ''
      // The local study retriever searches every selected item in full. It returns
      // a bounded, page-addressed evidence set after scanning the complete sources.
      const retrievalPlan = selectedItems
      const grouped = new Map<string, LibraryItem[]>()
      for (const item of retrievalPlan) {
        if (!item.course_id) continue
        const group = grouped.get(item.course_id) || []
        group.push(item)
        grouped.set(item.course_id, group)
      }
      const groupEntries = [...grouped.entries()]
      const retrievalBatches = groupEntries.flatMap(([ownerId, sourceItems]) => Array.from({ length: Math.ceil(sourceItems.length / 300) }, (_, index) => ({
        ownerId,
        sourceItems: sourceItems.slice(index * 300, (index + 1) * 300),
      })))
      const contextResults = await Promise.all(retrievalBatches.map(async ({ ownerId, sourceItems }) => {
        const evidenceLimit = Math.max(1, Math.floor(128 * sourceItems.length / Math.max(1, retrievalPlan.length)))
        const args = ['context', '--course', ownerId, '--semester', semester, '--deep', '--limit', String(evidenceLimit)]
        for (const item of sourceItems) args.push('--source', item.id)
        const groupSearchQuery = [currentSearchText, priorSearchText.slice(-300), ownerId === courseId ? recordedScope.slice(0, 500) : ''].filter(Boolean).join(' ').slice(0, 1800)
        if (groupSearchQuery) args.push('--query', groupSearchQuery)
        return api.study<StudySourceContext>(args)
      }))
      const semesterItems = retrievalPlan.filter((item) => !item.course_id)
      const semesterResults = await Promise.all(semesterItems.map(async (item) => {
        try {
          return { item, preview: await api.filePreview(item.path, item.semester), error: '' }
        } catch (reason) {
          return { item, preview: null, error: String(reason) }
        }
      }))

      const contextParts: string[] = []
      if (course) {
        contextParts.push(`CURRENT CLASS: ${course.code} · ${course.name}. The selected source catalog below is metadata only; use it to reason about possible scope, but do not claim evidence from a source unless its retrieved passage appears below.`)
        const catalog = selectedItems.slice(0, 300).map((item) => `${item.category}: ${item.name.slice(0, 100)}${item.provenance ? ` · ${item.provenance}` : ''}`)
        contextParts.push(`AVAILABLE CLASS SOURCE CATALOG (metadata only; ${selectedItems.length} eligible sources${selectedItems.length > catalog.length ? `, first ${catalog.length} shown` : ''}): ${JSON.stringify(catalog)}`)
        if (academicContext?.courseId === course.id) {
          const tasks = academicContext.tasks.filter((task) => !task.completed).slice(0, 14).map((task) => ({ title: task.title, kind: task.kind, due_date: task.due_date, due_time: task.due_time, status: task.status, confidence: task.confidence }))
          const coursework = academicContext.history.filter((record) => record.status === 'planned' || record.status === 'in_progress').slice(0, 14).map((record) => ({ title: record.title, kind: record.kind, due_date: record.due_date, status: record.status, basis: record.record_basis }))
          const exams = (academicContext.study?.exams ?? []).slice(0, 12).map((exam) => ({ title: exam.title, date: exam.date, format: exam.format, topics: exam.topics, objectives: exam.objectives, source_ids: exam.source_ids }))
          const courseworkHistory = academicContext.history.slice().sort((a, b) => b.updated_at.localeCompare(a.updated_at)).slice(0, 16).map((record) => ({ title: record.title, kind: record.kind, status: record.status, due_date: record.due_date, submitted_on: record.submitted_on, grade: record.grade, record_basis: record.record_basis }))
          const studyTopics = (academicContext.study?.topics ?? []).filter((topic) => (topic.attempt_count ?? 0) > 0).slice().sort((a, b) => Number(Boolean(b.needs_review)) - Number(Boolean(a.needs_review)) || (a.correct_count ?? 0) / Math.max(1, (a.attempt_count ?? 0) - (a.self_review_count ?? 0)) - (b.correct_count ?? 0) / Math.max(1, (b.attempt_count ?? 0) - (b.self_review_count ?? 0))).slice(0, 30).map((topic) => ({ topic: topic.topic, attempts: topic.attempt_count, answer_key_correct: topic.correct_count, self_assessments: topic.self_review_count, needs_review: topic.needs_review }))
          const savedSessions = (academicContext.study?.sessions ?? []).slice(-12).map((session) => ({ title: session.title, status: session.status, mode: session.mode, created_at: session.created_at, score: session.score }))
          const practiceProgress = { total_attempts: academicContext.study?.attempt_count ?? 0, due_reviews: academicContext.study?.due_count ?? 0, topics: studyTopics, recent_saved_sessions: savedSessions }
          const studentNotes = (academicContext.study?.annotations ?? []).slice(-12).map((note) => ({ kind: note.kind, topic: note.topic, note: note.note, quote: note.quote, source_name: note.citation?.source_name, locator: note.citation?.locator, stale_source: note.stale_source }))
          contextParts.push(`RECORDED COURSEWORK AND STUDY CONTEXT (local student records; may be incomplete; dates, grades, and confidence are exactly as recorded): ${JSON.stringify({ open_tasks: tasks, upcoming_coursework: coursework, recent_coursework_history: courseworkHistory, saved_exam_scopes: exams, practice_progress: practiceProgress, student_study_notes: studentNotes })}`)
          if (academicContext.unavailable.length) contextParts.push(`Some local records could not be checked: ${academicContext.unavailable.join(', ')}. Do not infer that missing records mean there is no upcoming work.`)
        } else {
          contextParts.push('RECORDED COURSEWORK AND STUDY CONTEXT could not be loaded. Do not imply that AcademiaOS has checked upcoming assessments; ask the student if this context matters.')
        }
        if (academicContextLoading) contextParts.push('Course records may still be loading. Do not infer that missing records mean the class has no upcoming work.')
      }
      const deepScannedCount = retrievalPlan.filter((item) => Boolean(item.course_id)).length
      if (deepScannedCount) contextParts.push(`FULL-TEXT SOURCE SEARCH: Academia scanned all ${deepScannedCount} selected course sources across ${groupEntries.length} class scope(s), including all extractable PDF pages. The excerpts below are the most relevant passages from that complete scan, not complete copies of the files. Use their source names and page locations as evidence.`)
      if (semesterItems.length) contextParts.push(`SEMESTER-LEVEL SOURCES: ${semesterItems.length} selected source(s) were supplied through local file previews. Their preview may be bounded; read the retrieval note and do not claim full coverage when a preview says it was truncated.`)
      contextResults.forEach((context, index) => {
        const owner = courses.find((entry) => entry.id === retrievalBatches[index]?.ownerId)
        if (owner) contextParts.push(`CLASS: ${owner.code} · ${owner.name}`)
        if (context.coverage) contextParts.push(`SOURCE SEARCH COVERAGE: ${context.coverage.scanned_sources} of ${context.coverage.selected_sources} selected sources scanned; ${context.coverage.pdf_pages_scanned} PDF pages searched; ${context.coverage.matching_chunks} matching passages found; ${context.coverage.returned_chunks} passages supplied to you; complete=${context.coverage.complete}.`)
        contextParts.push(...context.chunks.map((chunk) => `SOURCE: ${chunk.source_name} · ${chunk.locator}\n${chunk.text}`))
        if (context.warnings.length) contextParts.push(`Retrieval notes: ${context.warnings.join(' ')}`)
      })
      for (const result of semesterResults) {
        if (!result.preview) {
          contextParts.push(`SOURCE NOT RETRIEVED: ${result.item.name}. ${result.error}`)
          continue
        }
        const previewTruncated = result.preview.truncated || result.preview.content.length > 12_000
        contextParts.push(`SOURCE: ${result.item.name} · ${result.item.relative_path}\n${result.preview.content.slice(0, 12_000)}${previewTruncated ? '\n[Preview truncated to a bounded excerpt.]' : ''}`)
      }
      const courseContext = contextParts.join('\n\n').slice(0, 235_000)
      const retrievedSourceIds = [...contextResults.flatMap((context) => (context.sources ?? []).map((source) => source.id)), ...semesterResults.filter((result) => result.preview).map((result) => result.item.id)]

      const boundedMessages: Message[] = []
      let historyLength = 0
      for (const message of nextMessages.slice(-20).reverse()) {
        if (historyLength + message.content.length > 58_000) break
        boundedMessages.unshift(message)
        historyLength += message.content.length
      }
      const result = await api.chat<ChatResult>({ provider, messages: boundedMessages.map(({ role, content }) => ({ role, content })), model: model || defaultModel || null, effort, speed, attachments: uploaded.map((attachment) => ({ name: attachment.name, type: attachment.type, data: attachment.data })), course_context: courseContext, proposal_mode: proposalMode, course_id: courseId || null, semester: semester || null })
      const assistantMessage: Message = { role: 'assistant' as const, content: result.message, ...(result.proposals?.length ? { proposals: result.proposals } : {}) }
      const completedMessages = [...nextMessages, assistantMessage]
      setMessages(completedMessages)
      await persistConversation(completedMessages)
      if (result.proposals?.length) onProposalCreated()
      setChatAttachments(uploaded)
      setLastRetrievedSourceIds([...new Set(retrievedSourceIds)])
      if (result.notice) setError(result.notice)
    } catch (reason) {
      setMessages(messages)
      if (text) setDraft((current) => current || text)
      if (pendingAttachments.length) setAttachments((current) => [...pendingAttachments, ...current].slice(0, 5))
      setError(String(reason))
    } finally {
      setBusy(false)
    }
  }

  const onChatStudyRequestComplete = (id: string, title?: string, generationError?: string) => {
    if (chatStudyRequest?.id !== id) return
    setChatStudyRequest(null)
    setStudyGenerationInProgress(false)
    const classLabel = courses.find((entry) => entry.id === chatStudyRequest.courseId)?.code ?? 'the selected class'
    const content = generationError
      ? `I couldn’t finish creating that study material. ${generationError}`
      : `Saved **${title ?? 'Study material'}** to the ${classLabel} Study library. Open it in Studio when you’re ready to practice.`
    const completed = [...messagesRef.current, { role: 'assistant' as const, content }]
    messagesRef.current = completed
    setMessages(completed)
    void persistConversation(completed)
  }

  const chooseFiles = (files: FileList | File[] | null) => {
    if (!files) return
    const incoming = Array.from(files)
    const next = incoming.map(normalizeAttachmentFile).filter((file): file is File => file !== null)
    if (!next.length) {
      setError('Attach a PDF, DOCX, PPTX, text, Markdown, CSV, JSON, YAML, PNG, JPEG, WebP, or GIF file.')
      return
    }
    if (next.some((file) => file.size > 12 * 1024 * 1024)) {
      setError('Each attachment must be under 12 MB.')
      return
    }
    const existingCount = chatAttachments.length + attachments.length
    const existingBytes = chatAttachments.reduce((sum, file) => sum + file.size, 0) + attachments.reduce((sum, file) => sum + file.size, 0)
    if (existingCount + next.length > 5) {
      setError('This chat can keep up to five attachments. Remove one before adding another.')
      return
    }
    if (existingBytes + next.reduce((sum, file) => sum + file.size, 0) > 32 * 1024 * 1024) {
      setError('Each attachment must be under 12 MB and all attachments under 32 MB.')
      return
    }
    setAttachments((current) => [...current, ...next])
    setError(incoming.length !== next.length ? 'Some files were skipped because their file type is not supported.' : '')
  }

  const pasteFiles = (event: ReactClipboardEvent<HTMLTextAreaElement>) => {
    const clipboard = event.clipboardData
    const files = new Map<string, File>()
    for (const file of Array.from(clipboard.files)) files.set(`${file.name}:${file.size}:${file.type}`, file)
    for (const item of Array.from(clipboard.items)) {
      if (item.kind !== 'file') continue
      const file = item.getAsFile()
      if (file) files.set(`${file.name}:${file.size}:${file.type}`, file)
    }
    if (!files.size) return
    event.preventDefault()
    chooseFiles([...files.values()])
  }

  const selectCourse = (nextCourseId: string) => {
    setCourseId(nextCourseId)
    setSourceIds([])
    setExcludedCourseSourceIds([])
    setLastRetrievedSourceIds([])
  }
  const toggleSource = (id: string) => {
    const item = readableItems.find((entry) => entry.id === id)
    if (courseId && item?.course_id === courseId) {
      setExcludedCourseSourceIds((current) => current.includes(id) ? current.filter((entry) => entry !== id) : [...current, id])
    } else {
      setSourceIds((current) => current.includes(id) ? current.filter((entry) => entry !== id) : [...current, id])
    }
    setLastRetrievedSourceIds([])
  }
  const toggleAllVisibleSources = () => {
    const ids = filteredItems.map((item) => item.id)
    if (!ids.length) return
    if (courseId) {
      setExcludedCourseSourceIds((current) => allVisibleSourcesSelected
        ? [...new Set([...current, ...ids])]
        : current.filter((id) => !ids.includes(id)))
    } else {
      setSourceIds((current) => allVisibleSourcesSelected
        ? current.filter((id) => !ids.includes(id))
        : [...new Set([...current, ...ids])])
    }
    setLastRetrievedSourceIds([])
  }
  const openHistory = async () => {
    setHistoryOpen(true)
    setHistoryLoading(true)
    setHistoryError('')
    const scopeCourses = course ? [course] : courses
    const results = await Promise.allSettled(scopeCourses.map(async (entry) => ({
      course: entry,
      overview: await api.study<StudyOverview>(['overview', '--course', entry.id, ...(semester ? ['--semester', semester] : [])]),
    })))
    const nextEntries = results.flatMap((result) => result.status === 'fulfilled'
      ? (result.value.overview.sessions ?? []).map((session) => ({ course: result.value.course, session }))
      : [])
    setHistoryEntries(nextEntries.sort((a, b) => b.session.created_at.localeCompare(a.session.created_at)))
    if (results.length && results.every((result) => result.status === 'rejected')) setHistoryError('Saved study history could not be loaded. Try again in a moment.')
    setHistoryLoading(false)
  }
  const archiveCurrentConversation = () => {
    if (!messages.length) return
    void persistConversation(messages)
  }
  const resumeConversation = (conversation: ChatConversation) => {
    if (busy || studyGenerationInProgress) return
    setPendingChatStudy(null)
    setChatStudyRequest(null)
    archiveCurrentConversation()
    setActiveConversationId(conversation.id)
    setMessages(conversation.messages)
    setCourseId(conversation.courseId)
    setSourceIds(conversation.sourceIds)
    setExcludedCourseSourceIds(conversation.excludedCourseSourceIds)
    setChatAttachments([])
    setAttachments([])
    setDraft('')
    setError('')
    setLastRetrievedSourceIds([])
    setHistoryOpen(false)
  }
  const removeConversation = async (id: string) => {
    try {
      await deleteChatConversation(id)
      setConversationHistory((current) => current.filter((conversation) => conversation.id !== id))
      setConversationHistoryError('')
    } catch (reason) {
      setConversationHistoryError(`This conversation could not be deleted from this device. ${String(reason)}`)
    }
  }
  const startNewChat = () => {
    if (busy || studyGenerationInProgress) return
    archiveCurrentConversation()
    setActiveConversationId(null)
    setMessages([])
    messagesRef.current = []
    setPendingChatStudy(null)
    setChatStudyRequest(null)
    setDraft('')
    setChatAttachments([])
    setAttachments([])
    setError('')
    setLastRetrievedSourceIds([])
    setHistoryOpen(false)
  }
  useEffect(() => {
    if (!studyChatRequest || conversationHistoryLoading || busy || studyGenerationInProgress || handledStudyChatRequest.current === studyChatRequest.id) return
    handledStudyChatRequest.current = studyChatRequest.id
    if (studyChatRequest.action === 'open') {
      const conversation = conversationHistory.find((entry) => entry.id === studyChatRequest.conversationId)
      if (conversation) resumeConversation(conversation)
      else setError('That saved conversation is no longer available in this browser profile.')
      onStudyChatRequestConsumed()
      return
    }
    const targetCourseExists = courses.some((entry) => entry.id === studyChatRequest.courseId)
    if (!targetCourseExists) {
      setError('That class is no longer available in the current semester.')
      onStudyChatRequestConsumed()
      return
    }
    startNewChat()
    setCourseId(studyChatRequest.courseId)
    setSourceIds([])
    setExcludedCourseSourceIds([])
    setDraft(studyChatRequest.prompt || '')
    onStudyChatRequestConsumed()
  }, [busy, conversationHistory, conversationHistoryLoading, courses, onStudyChatRequestConsumed, resumeConversation, startNewChat, studyChatRequest, studyGenerationInProgress])

  return <div className="page-stack chat-page">
    <section className={`chat-workspace ${!sourcesOpen ? 'sources-collapsed' : ''} ${!studioOpen ? 'studio-collapsed' : ''}`} aria-label="Study chat workspace">
      {sourcesOpen ? <aside className="chat-sources-panel" aria-label="Sources in this chat">
        <header className="chat-panel-heading"><div><p className="eyebrow">Context</p><h3>Sources</h3></div><div className="chat-panel-actions"><button className="chat-source-bulk-toggle" type="button" onClick={toggleAllVisibleSources} disabled={!filteredItems.length} aria-label={`${allVisibleSourcesSelected ? 'Uncheck' : 'Check'} all ${sourceFilter ? 'matching ' : ''}sources`} data-tooltip={`${allVisibleSourcesSelected ? 'Uncheck' : 'Check'} all ${sourceFilter ? 'matching ' : ''}sources`} data-tooltip-side="bottom"><span>{allVisibleSourcesSelected ? 'Uncheck all' : 'Check all'}</span><small>{availableSourceCount} available</small></button><button className="chat-panel-collapse" onClick={() => setSourcesOpen(false)} aria-label="Collapse sources panel" data-tooltip="Collapse sources" data-tooltip-side="bottom">‹</button></div></header>
        <label className="chat-source-search"><span aria-hidden="true">⌕</span><input ref={sourceFilterRef} value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)} placeholder={course ? `Find ${course.code} sources` : 'Find class sources'} aria-label="Search Academia sources" /></label>
          {draft.trim() && <section className="chat-source-plan" aria-live="polite"><header><strong>Full-text source search</strong><span>{selectedItems.length} selected</span></header><p>Every selected source’s extractable text is searched. Relevant passages with page locations are supplied to the chat, and any extraction limits are reported.</p></section>}
        <div className="chat-source-groups">
          {sourceGroups.map(([groupId, group]) => {
            const checkedCount = group.items.filter((item) => selectedSourceIdSet.has(item.id)).length
            return <section className={`chat-source-group ${groupId === courseId ? 'current' : ''}`} key={groupId}>
              <header><strong>{group.name}</strong><span>{groupId === courseId ? `${checkedCount} available` : checkedCount ? `${checkedCount} added` : `${group.items.length} sources`}</span></header>
              {group.items.map((item) => {
                const isAvailable = selectedSourceIdSet.has(item.id)
                const wasRetrieved = lastRetrievedSourceIdSet.has(item.id)
                return <label className={`chat-source-row ${isAvailable ? 'selected' : ''} ${wasRetrieved ? 'retrieved' : ''}`} key={item.id}>
                <input type="checkbox" checked={isAvailable} onChange={() => toggleSource(item.id)} aria-label={`${isAvailable ? item.course_id === courseId ? 'Exclude' : 'Remove' : 'Add'} ${item.name} ${isAvailable && item.course_id === courseId ? 'from' : 'in'} this chat`} />
                <span className="chat-source-file-icon" aria-hidden="true">{item.extension.replace('.', '').slice(0, 3).toUpperCase()}</span>
                <span className="chat-source-copy"><strong>{item.name}</strong><small>{wasRetrieved ? 'Searched for latest reply · ' : ''}{item.category.replaceAll('_', ' ')}{item.intake_status === 'inbox' ? ' · Intake' : ''} · {item.extension.toUpperCase()}</small></span>
              </label>})}
            </section>
          })}
          {!sourceGroups.length && <div className="chat-sources-empty"><span>▤</span><strong>{course ? 'No readable sources in this class yet' : 'No readable sources here yet'}</strong><p>Import course material, or choose a class with indexed PDFs, notes, or documents.</p></div>}
        </div>
        {(chatAttachments.length > 0 || attachments.length > 0) && <section className="chat-local-files"><p className="eyebrow">Attached files</p>{chatAttachments.map((file, index) => <div className="chat-local-file" key={`sent-${file.name}-${index}`}><span>▤</span><span title={file.name}>{file.name}<small>Used in this chat</small></span><button aria-label={`Remove ${file.name} from future messages`} onClick={() => setChatAttachments((current) => current.filter((_, position) => position !== index))}>×</button></div>)}{attachments.map((file, index) => <div className="chat-local-file pending" key={`pending-${file.name}-${index}`}><span>▧</span><span title={file.name}>{file.name}<small>Ready to attach</small></span><button aria-label={`Remove ${file.name}`} onClick={() => setAttachments((current) => current.filter((_, position) => position !== index))}>×</button></div>)}</section>}
      </aside> : <aside className="chat-sources-panel chat-collapsed-rail sources-collapsed-rail" aria-label="Sources panel collapsed"><button className="chat-rail-toggle" type="button" onClick={() => setSourcesOpen(true)} aria-label="Expand sources panel" data-tooltip="Sources" data-tooltip-side="right">›</button></aside>}

      <section className="chat-main" aria-label="Conversation">
        <header className="chat-conversation-heading"><div className="chat-heading-start"><div className="chat-heading-title"><p className="eyebrow">Conversation</p></div></div><div className="chat-heading-end"><strong>{course ? `${course.code} · ${course.name}` : 'General study chat'}</strong><button className="chat-history-button" onClick={() => void openHistory()} disabled={busy || studyGenerationInProgress} aria-label="Open study history"><svg className="chat-action-icon" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M3.4 7.2A7 7 0 1 1 3 11"/><path d="M3 3.8v3.8h3.8M10 6.5V10l2.5 1.5"/></svg><span>History</span></button><button className="chat-new-session" onClick={startNewChat} disabled={busy || studyGenerationInProgress} aria-label="Start a new study chat"><svg className="chat-action-icon" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M11.8 3.2H5.5A1.5 1.5 0 0 0 4 4.7v10.8A1.5 1.5 0 0 0 5.5 17h9a1.5 1.5 0 0 0 1.5-1.5V9.2"/><path d="m9 12.8.5-2.6L15.7 4a1.6 1.6 0 0 1 2.3 2.3l-6.2 6.2-2.8.3Z"/></svg><span>New chat</span></button></div></header>
        <div className="chat-messages" ref={listRef} aria-live="polite">
          {messages.length === 0 ? <div className="chat-welcome"><p className="eyebrow">{course ? `Your ${course.code} study space` : 'Ready when you are'}</p><h3>{course ? `What’s next in ${course.code}?` : 'What are you studying?'}</h3><p>{course ? 'Pick a goal based on this class, or ask about an idea that still feels unclear.' : 'Choose a class to get study suggestions based on its course context, or start a general study chat.'}</p><div className="chat-suggestions">{course ? suggestions.map((suggestion) => <button key={suggestion.label} onClick={() => setDraft(suggestion.prompt)}>{suggestion.label} <span>↗</span></button>) : <span className="chat-suggestions-empty">Select a class in the composer for tailored study prompts.</span>}</div></div> : messages.map((message, index) => <article className={`chat-message ${message.role}`} key={index}><span className="chat-avatar">{message.role === 'user' ? 'You' : 'A'}</span><div className="chat-message-content"><small>{message.role === 'user' ? 'You' : 'Academia study assistant'}</small>{message.attachments?.length ? <div className="chat-message-attachments">{message.attachments.map((attachment, attachmentIndex) => attachment.preview ? <figure className="chat-message-image" key={`${attachment.name}-${attachmentIndex}`}><img src={attachment.preview} alt={`Attached image: ${attachment.name}`} /><figcaption>{attachment.name}</figcaption></figure> : <div className="chat-message-file" key={`${attachment.name}-${attachmentIndex}`}><span aria-hidden="true">▤</span><span><strong>{attachment.name}</strong><small>{attachment.type.startsWith('image/') ? 'Image attachment · reattach to view' : attachment.type === 'application/pdf' ? 'PDF document' : 'Attached document'}</small></span></div>)}</div> : null}<div className="chat-rich-text"><ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]} components={chatMarkdownComponents}>{message.content}</ReactMarkdown></div>{message.proposals?.length ? <ChatProposals proposals={message.proposals} onOpenReview={onOpenReview} /> : null}</div></article>)}
          {(busy || studyGenerationInProgress) && <div className="chat-thinking" role="status" aria-live="polite"><span className="chat-avatar">A</span><span className="chat-thinking-copy">{studyGenerationInProgress ? 'Creating source-grounded study material in Studio' : selectedItems.length ? 'Reading selected sources and thinking through your question' : 'Thinking through your question'}<span className="chat-loading-dots" aria-hidden="true"><span /><span /><span /></span></span></div>}
        </div>
        <div className="chat-composer-wrap">
          {error && <p className="chat-error" role="alert">{error}</p>}
          {proposalMode && <p className="chat-proposal-mode-note" role="note">Proposal mode is on: the assistant can prepare exact task or import proposals for Review. It cannot approve, execute, or write.</p>}
          {showAttachMenu && <div className="chat-attach-menu" role="menu" aria-label="Add to this chat">
            <button role="menuitem" onClick={() => { setShowAttachMenu(false); fileInputRef.current?.click() }}><span>↑</span><span><strong>Add a file to this chat</strong><small>Images, PDF, DOCX, PPTX, and text · 12 MB each</small></span></button>
            <button role="menuitem" onClick={() => { setShowAttachMenu(false); setShowSourcePicker(true) }}><span>▤</span><span><strong>Add Academia sources</strong><small>Choose materials from any class</small></span></button>
          </div>}
          <form className="chat-composer" onSubmit={(event) => { event.preventDefault(); void send() }}>
            {(attachments.length > 0 || chatAttachments.length > 0 || selectedItems.some((item) => item.course_id !== courseId)) && <div className="chat-composer-attachments">{chatAttachments.map((file, index) => <span key={`kept-${file.name}-${index}`}>{file.type.startsWith('image/') ? '▧' : '▤'} {file.name} · in chat</span>)}{attachments.map((file, index) => <span key={`${file.name}-${index}`}>{file.type.startsWith('image/') ? '▧' : '▤'} {file.name}</span>)}{selectedItems.filter((item) => item.course_id !== courseId).map((item) => <span className="chat-source-chip" key={item.id} title={`${courses.find((entry) => entry.id === item.course_id)?.code ?? item.semester} · ${item.name}`}>▤ {item.name}<button type="button" aria-label={`Remove ${item.name} from chat`} onClick={() => toggleSource(item.id)}>×</button></span>)}</div>}
            <textarea ref={textareaRef} value={draft} onChange={(event) => setDraft(event.target.value)} onPaste={pasteFiles} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void send() } }} placeholder="Ask anything about your classes…" rows={2} maxLength={12000} aria-label="Your message. Paste an image or document to attach it." />
            <div className="chat-composer-toolbar">
              <div className="chat-composer-context">
                <div className="chat-attach-anchor"><button className="chat-attach-button" type="button" aria-label="Attach a file or Academia source" aria-expanded={showAttachMenu} onClick={() => setShowAttachMenu((open) => !open)}>＋</button></div>
                <input ref={fileInputRef} className="chat-file-input" type="file" accept="application/pdf,image/png,image/jpeg,image/webp,image/gif,.docx,.pptx,.txt,.text,.md,.markdown,.csv,.json,.yaml,.yml" multiple onChange={(event) => { chooseFiles(event.target.files); event.target.value = '' }} />
                <span className={`chat-status-dot ${isAvailable ? 'available' : 'unavailable'}`} role="img" aria-label={statusLabel} data-tooltip={statusLabel} data-tooltip-side="top" />
                <ChatPicker id="course" icon="▣" value={courseId} placeholder="Course context" ariaLabel="Course context" options={[{ value: '', label: 'General study chat' }, ...courses.map((entry) => ({ value: entry.id, label: `${entry.code} · ${entry.name}` }))]} openPicker={openPicker} setOpenPicker={setOpenPicker} onChange={selectCourse} />
              </div>
              <div className="chat-composer-controls">
                <ChatPicker id="provider" label="AI" value={provider} ariaLabel="AI provider" options={providerOptions.map((entry) => ({ value: entry.id, label: entry.name, disabled: !entry.available, reason: entry.reason }))} disabled={!providerOptions.length} openPicker={openPicker} setOpenPicker={setOpenPicker} onChange={(value) => { if (value === 'codex') localStorage.setItem('academia.chat.provider', value) }} />
                <ChatPicker id="model" label="Model" value={model || defaultModel} placeholder="Provider default" ariaLabel="Model" options={modelOptions.map((entry) => ({ value: entry.id, label: entry.name }))} disabled={!modelOptions.length} openPicker={openPicker} setOpenPicker={setOpenPicker} onChange={(value) => { setModel(value); localStorage.setItem(`academia.chat.model.${provider}`, value); if (provider === 'codex') localStorage.setItem('academia.chat.model', value) }} />
                <ChatPicker id="effort" label="Thinking" value={effort} ariaLabel="Thinking effort" options={thinkingOptions.map(([value, label]) => ({ value, label }))} openPicker={openPicker} setOpenPicker={setOpenPicker} onChange={(value) => { setEffort(value); localStorage.setItem(`academia.chat.effort.${provider}`, value); localStorage.setItem('academia.chat.effort', value) }} />
                <button className={`chat-proposal-toggle ${proposalMode ? 'active' : ''}`} type="button" aria-label={proposalMode ? 'Action proposals enabled' : 'Enable action proposals'} aria-pressed={proposalMode} disabled={busy || studyGenerationInProgress} data-tooltip={proposalMode ? 'Proposal mode is on · the assistant can create Review items but cannot approve or execute them' : 'Enable action proposals · the assistant can prepare exact task or import changes for Review'} data-tooltip-side="top" onClick={() => { const next = !proposalMode; setProposalMode(next); localStorage.setItem('academia.chat.proposals', String(next)) }}>
                  <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                    <path d="M7 3.5h7l3 3v14H7z" />
                    <path d="M14 3.5v3h3" />
                    <path d="M9.5 12.5h5M9.5 15.5h5" />
                  </svg>
                </button>
                {provider === 'codex' && <button className={`chat-speed-toggle ${speed === 'fast' ? 'active' : ''}`} type="button" aria-label={`${speed === 'fast' ? 'Fast' : 'Standard'} response speed`} aria-pressed={speed === 'fast'} data-tooltip={speed === 'fast' ? 'Fast response mode · shorter waits, but it may use your ChatGPT subscription allowance faster' : 'Standard response mode · normal processing speed'} data-tooltip-side="top" onClick={() => { const nextSpeed = speed === 'fast' ? 'standard' : 'fast'; setSpeed(nextSpeed); localStorage.setItem('academia.chat.speed', nextSpeed) }}>
                  <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                    <path className="chat-speed-gauge" d="M5.05 18.95a9.8 9.8 0 1 1 13.9 0l-2.12-2.12a6.8 6.8 0 1 0-9.66 0l-2.12 2.12Z" />
                    <path className="chat-speed-needle" d="m12 13 4.4-4.4" />
                    <circle className="chat-speed-center" cx="12" cy="13" r="1.35" />
                  </svg>
                </button>}
                <button className="chat-send" type="submit" disabled={busy || studyGenerationInProgress || (!draft.trim() && !attachments.length) || !isAvailable} aria-label={busy || studyGenerationInProgress ? 'Sending message' : 'Send message'} aria-busy={busy || studyGenerationInProgress}>{busy || studyGenerationInProgress ? <span className="chat-loading-dots compact" aria-hidden="true"><span /><span /><span /></span> : '↑'}</button>
              </div>
            </div>
          </form>
          <div className="chat-composer-foot"><span>Paste an image or document · Enter to send · Shift + Enter for a new line</span><span>{course ? `${selectedItems.filter((item) => item.course_id === courseId).length} class sources available${selectedItems.some((item) => item.course_id !== courseId) ? ` · ${selectedItems.filter((item) => item.course_id !== courseId).length} additional` : ''}${academicContextLoading ? ' · loading course context…' : ''}${lastRetrievedSourceIds.length ? ` · ${lastRetrievedSourceIds.length} retrieved last reply` : ''}` : selectedItems.length ? `${selectedItems.length} sources added` : 'Select a class to use its sources automatically'}</span></div>
        </div>
      </section>

      <ChatStudyStudio courses={courses} course={course} items={readableItems} selectedSourceIds={selectedItems.map((item) => item.id)} semester={semester} provider={provider} model={model || defaultModel || undefined} isVisible={studioOpen} onCollapse={() => setStudioOpen(false)} chatRequest={chatStudyRequest} onChatRequestComplete={onChatStudyRequestComplete} />
      {!studioOpen && <aside className="chat-study-panel chat-collapsed-rail studio-collapsed-rail" aria-label="Study modes panel collapsed"><button className="chat-rail-toggle" type="button" onClick={() => setStudioOpen(true)} aria-label="Expand study modes panel" data-tooltip="Studio" data-tooltip-side="left">‹</button></aside>}
    </section>
    {showSourcePicker && <div className="chat-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setShowSourcePicker(false) }}><section className="chat-dialog chat-source-picker-dialog" role="dialog" aria-modal="true" aria-labelledby="chat-source-picker-title"><header><div><p className="eyebrow">Add to this chat</p><h3 id="chat-source-picker-title">Choose Academia sources</h3><p>{course ? `Browse materials outside ${course.code}. They’ll be attached only to this chat.` : 'Choose material from any class to add to this chat.'}</p></div><button className="chat-dialog-close" onClick={() => setShowSourcePicker(false)} aria-label="Close source picker">×</button></header><label className="chat-source-search"><span aria-hidden="true">⌕</span><input value={sourcePickerFilter} onChange={(event) => setSourcePickerFilter(event.target.value)} placeholder="Search other classes and sources" aria-label="Search sources to add" /></label><div className="chat-picker-source-groups">{pickerGroups.map(([groupId, group]) => <section className="chat-source-group" key={groupId}><header><strong>{group.name}</strong><span>{group.items.filter((item) => sourceIds.includes(item.id)).length} added</span></header>{group.items.map((item) => <label className={`chat-source-row ${sourceIds.includes(item.id) ? 'selected' : ''}`} key={item.id}><input type="checkbox" checked={sourceIds.includes(item.id)} onChange={() => toggleSource(item.id)} aria-label={`${sourceIds.includes(item.id) ? 'Remove' : 'Add'} ${item.name} ${sourceIds.includes(item.id) ? 'from' : 'to'} this chat`} /><span className="chat-source-file-icon" aria-hidden="true">{item.extension.replace('.', '').slice(0, 3).toUpperCase()}</span><span className="chat-source-copy"><strong>{item.name}</strong><small>{item.category.replaceAll('_', ' ')}{item.intake_status === 'inbox' ? ' · Intake' : ''} · {item.extension.toUpperCase()}</small></span></label>)}</section>)}{!pickerGroups.length && <div className="chat-sources-empty"><strong>No sources found</strong><p>Try another search or import material into a class first.</p></div>}</div><footer><span>{selectedItems.filter((item) => item.course_id !== courseId).length} additional source{selectedItems.filter((item) => item.course_id !== courseId).length === 1 ? '' : 's'} attached</span><button className="primary-button" onClick={() => setShowSourcePicker(false)}>Done</button></footer></section></div>}
    {historyOpen && <div className="chat-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setHistoryOpen(false) }}><section className="chat-dialog chat-history-dialog" role="dialog" aria-modal="true" aria-labelledby="chat-history-title">
      <header><div><p className="eyebrow">Pick up where you left off</p><h3 id="chat-history-title">Chat & study history</h3><p>Conversations are saved in this browser on this device and stay until you delete them or clear browser data. Saved practice sessions remain in the class workspace. File contents and image previews are not retained; reattach original files to use them again.</p></div><button className="chat-dialog-close" onClick={() => setHistoryOpen(false)} aria-label="Close chat and study history">×</button></header>
      <div className="chat-history-content">
        {messages.length > 0 && <><p className="chat-history-section-label">Current conversation</p><div className="chat-history-list"><button className="chat-history-row chat-conversation-row" onClick={() => setHistoryOpen(false)}><span className="chat-history-icon">◌</span><span><strong>{messages.find((message) => message.role === 'user')?.content.replace(/\s+/g, ' ').slice(0, 72) || 'Study conversation'}</strong><small>{course ? `${course.code} · ${course.name}` : 'General study chat'} · {messages.length} messages</small></span><b>Current</b></button></div></>}
        {conversationHistoryLoading && <p className="chat-history-session-note" role="status">Loading saved conversations from this device…</p>}
        {conversationHistoryError && <p className="chat-error" role="alert">{conversationHistoryError}</p>}
        {conversationHistory.filter((conversation) => conversation.id !== activeConversationId).length > 0 && <><p className="chat-history-section-label">Saved conversations</p><div className="chat-history-list">{conversationHistory.filter((conversation) => conversation.id !== activeConversationId).map((conversation) => <div className="chat-history-entry" key={conversation.id}><button className="chat-history-row chat-conversation-row" onClick={() => resumeConversation(conversation)} disabled={busy}><span className="chat-history-icon">◌</span><span><strong>{conversation.title}</strong><small>{conversation.courseLabel} · {conversation.messages.length} messages · {new Date(conversation.updatedAt).toLocaleString()}</small></span><b>Open →</b></button><button className="chat-history-delete" onClick={() => void removeConversation(conversation.id)} aria-label={`Delete ${conversation.title}`} data-tooltip="Delete saved conversation" data-tooltip-side="left">×</button></div>)}</div></>}
        {(historyLoading || historyError || historyEntries.length > 0 || conversationHistory.length > 0) && <p className="chat-history-section-label">Saved practice sessions</p>}
        {historyLoading ? <p className="chat-history-session-note" role="status">Checking saved study sessions…</p> : historyError ? <p className="chat-error" role="alert">{historyError}</p> : historyEntries.length ? <div className="chat-history-list">{historyEntries.map(({ course: entryCourse, session }) => <button className="chat-history-row" key={`${entryCourse.id}:${session.id}`} onClick={() => { setHistoryOpen(false); onResumeStudySession(entryCourse.id, session.id) }}><span className="chat-history-icon">◷</span><span><strong>{session.title}</strong><small>{entryCourse.code} · {session.status === 'active' ? 'In progress' : 'Completed'}{session.created_at ? ` · ${new Date(session.created_at).toLocaleDateString()}` : ''}</small></span><b>{session.status === 'active' ? 'Resume →' : 'Review →'}</b></button>)}</div> : conversationHistory.length > 0 && <p className="chat-history-session-note">No saved practice sessions found for these classes yet.</p>}
        {!conversationHistoryLoading && !conversationHistoryError && !conversationHistory.length && !messages.length && !historyLoading && !historyError && !historyEntries.length && <div className="chat-history-empty"><span>◷</span><strong>No chat history yet</strong><p>Your conversations will be saved here on this device after you chat. Structured study sessions are saved separately by class.</p></div>}
      </div>
      <footer><button className="secondary-button" onClick={startNewChat} disabled={busy}>Start a new study chat</button><button className="primary-button" onClick={() => setHistoryOpen(false)}>Done</button></footer>
    </section></div>}
  </div>
}

type PickerOption = { value: string; label: string; disabled?: boolean; reason?: string }
function ChatPicker({ id, label, icon, value, placeholder = '', ariaLabel, title, options, disabled = false, openPicker, setOpenPicker, onChange }: {
  id: string
  label?: string
  icon?: string
  value: string
  placeholder?: string
  ariaLabel: string
  title?: string
  options: PickerOption[]
  disabled?: boolean
  openPicker: string | null
  setOpenPicker: (value: string | null) => void
  onChange: (value: string) => void
}) {
  const open = openPicker === id
  const selected = options.find((option) => option.value === value)
  return <div className={`chat-picker ${id === 'course' ? 'chat-course-picker' : ''} ${open ? 'open' : ''}`} title={title}>
    <button className={`chat-picker-trigger ${label ? 'has-label' : 'course-trigger'}`} type="button" aria-label={ariaLabel} aria-haspopup="listbox" aria-expanded={open} disabled={disabled} onClick={() => setOpenPicker(open ? null : id)}>
      {icon && <span className="chat-picker-icon" aria-hidden="true">{icon}</span>}
      {label && <span className="chat-picker-label">{label}</span>}
      <strong>{selected?.label || placeholder || value}</strong>
      <span className="chat-picker-caret" aria-hidden="true">⌄</span>
    </button>
    {open && <div className="chat-picker-menu" role="listbox" aria-label={ariaLabel}>{options.map((option) => <button key={option.value || '__empty'} type="button" role="option" aria-selected={value === option.value} aria-disabled={option.disabled || undefined} title={option.reason} disabled={option.disabled} className={value === option.value ? 'selected' : ''} onClick={() => { onChange(option.value); setOpenPicker(null) }}><span>{option.label}{option.reason && <small className="chat-picker-option-reason">{option.reason}</small>}</span>{value === option.value && <span className="chat-picker-check" aria-hidden="true">✓</span>}</button>)}</div>}
  </div>
}

async function fileToAttachment(file: File): Promise<Attachment> {
  const bytes = new Uint8Array(await file.arrayBuffer())
  let binary = ''
  const stride = 0x8000
  for (let offset = 0; offset < bytes.length; offset += stride) binary += String.fromCharCode(...bytes.subarray(offset, offset + stride))
  return { name: file.name, type: file.type, data: btoa(binary), preview: await createImagePreview(file), size: file.size }
}

async function createImagePreview(file: File): Promise<string> {
  if (!file.type.startsWith('image/')) return ''
  try {
    const bitmap = await createImageBitmap(file)
    const scale = Math.min(1, 360 / Math.max(bitmap.width, bitmap.height))
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(bitmap.width * scale))
    canvas.height = Math.max(1, Math.round(bitmap.height * scale))
    const context = canvas.getContext('2d')
    if (!context) { bitmap.close(); return '' }
    context.fillStyle = '#fff'
    context.fillRect(0, 0, canvas.width, canvas.height)
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
    bitmap.close()
    const preview = canvas.toDataURL('image/jpeg', 0.65)
    return preview.length <= 180_000 ? preview : ''
  } catch {
    return ''
  }
}

function normalizeAttachmentFile(file: File): File | null {
  const namedExtension = file.name.toLocaleLowerCase().match(/\.[^.]+$/)?.[0] ?? ''
  const extension = namedExtension
    ? (attachmentFormats[namedExtension] ? namedExtension : '')
    : attachmentExtensionByMime[file.type.toLocaleLowerCase()] ?? ''
  const format = attachmentFormats[extension]
  if (!format || (file.type && !format.acceptedMime.includes(file.type.toLocaleLowerCase()))) return null
  const name = namedExtension === extension ? file.name : `${file.name || 'pasted-file'}${extension}`
  if (file.type === format.mime && file.name === name) return file
  return new File([file], name, { type: format.mime, lastModified: file.lastModified })
}
