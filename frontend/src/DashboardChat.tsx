import { useEffect, useMemo, useRef, useState, type ClipboardEvent as ReactClipboardEvent, type ReactNode } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import rehypeKatex from 'rehype-katex'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import { api, ChatCancelledError, type ChatStreamEvent, type PendingAction } from './lib/api'
import { ChatProposals } from './ChatProposals'
import { deleteChatConversation, listChatConversations, loadChatConversation, saveChatConversation, stripChatAttachmentPreviews, type ChatConversation, type ChatConversationSummary, type ChatMessage, type ChatProposal, type ChatTraceStep, type StudyChatRequest } from './lib/chat-history'
import { ChatStudyStudio, type ChatStudyRequest, type ModeId } from './ChatStudyStudio'
import type { ActivityEvent, Course, CourseworkHistoryRecord, LibraryItem, ReviewItem, Task } from './types'
import 'katex/dist/katex.min.css'
import './dashboard-chat.css'

type Message = ChatMessage
type ChatProviderInfo = {
  id: string
  name: string
  installed: boolean | null
  authenticated: boolean | null
  available: boolean
  models: { id: string; name: string; capabilities?: string[] }[]
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
type ChatResult = { message: string; model: string | null; effort: string; speed: string; notice: string | null; proposal_mode?: boolean; proposals?: ChatProposal[]; trace?: ChatTraceStep[] }
type StreamProgress = { id: string; tool: string; label: string; state: 'running' | 'done' }
type StreamState = { content: string; progress: StreamProgress[]; proposals: ChatProposal[] }
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

function toolProgressLabel(tool: string) {
  if (tool === 'academia_propose_task') return 'Preparing a personal-task proposal'
  if (tool === 'academia_propose_import') return 'Preparing a file-import proposal'
  if (tool === 'academia_library') return 'Searching the class library'
  if (tool === 'academia_read_library_item') return 'Reading a selected source'
  if (tool === 'academia_agent_context') return 'Checking academic context'
  if (tool === 'academia_tasks') return 'Checking tasks'
  if (tool === 'academia_status') return 'Checking the workspace'
  if (tool === 'academia_external_context' || tool === 'academia_google_context') return 'Reading granted Gmail, Calendar, and Notion context'
  if (tool === 'academia_propose_calendar') return 'Checking duplicates and preparing a Calendar proposal'
  return 'Using an Academia tool'
}

function proposalStatusLabel(item: ReviewItem) {
  const action = item.action_status
  if (action === 'verified') return 'Completed and verified'
  if (action === 'executed') return 'Executed; verification pending'
  if (action === 'failed') return 'Execution failed; back in Review'
  if (action === 'approved') return 'Approved; ready to execute'
  if (action === 'rejected' || item.status === 'rejected') return 'Rejected'
  if (item.status === 'resolved') return 'Completed'
  if (item.status === 'approved') return 'Approved; ready to execute'
  return 'Waiting for your review'
}

export function DashboardChat({ courses, items, semester, activity, onOpenReview, onProposalCreated, reviewRevision, onResumeStudySession, studyChatRequest, onStudyChatRequestConsumed, onGoHome }: { courses: Course[]; items: LibraryItem[]; semester: string; activity: ActivityEvent[]; onOpenReview: (reviewId: string) => void; onProposalCreated: () => void; reviewRevision: number; onResumeStudySession: (courseId: string, sessionId: string) => void; studyChatRequest: StudyChatRequest | null; onStudyChatRequestConsumed: () => void; onGoHome: () => void }) {
  const [providers, setProviders] = useState<ChatProviders | null>(null)
  const [provider, setProvider] = useState(() => localStorage.getItem('academia.chat.provider') || 'codex')
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
  const [webSearch, setWebSearch] = useState(() => localStorage.getItem('academia.chat.webSearch') === 'true')
  const [googleAvailable, setGoogleAvailable] = useState(false)
  const [notionAvailable, setNotionAvailable] = useState(false)
  const [notionGrant, setNotionGrant] = useState(() => localStorage.getItem('academia.chat.notionGrant') === 'true')
  const [googleGrants, setGoogleGrants] = useState<string[]>(() => {
    try {
      const parsed = JSON.parse(localStorage.getItem('academia.chat.googleGrants') || '[]')
      return Array.isArray(parsed) ? parsed.filter((item) => item === 'gmail' || item === 'calendar') : []
    } catch {
      return []
    }
  })
  const [proposalGrants, setProposalGrants] = useState<string[]>(() => {
    try {
      const parsed = JSON.parse(localStorage.getItem('academia.chat.proposalGrants') || '["task","import"]')
      return Array.isArray(parsed) ? parsed.filter((item): item is string => item === 'task' || item === 'import' || item === 'calendar') : ['task', 'import']
    } catch {
      return ['task', 'import']
    }
  })
  const [streaming, setStreaming] = useState<StreamState | null>(null)
  const streamRef = useRef<{ controller: AbortController; runId: string | null } | null>(null)
  const streamingRef = useRef<StreamState | null>(null)
  const deltaBufferRef = useRef('')
  const deltaTimerRef = useRef<number | null>(null)
  const [showAttachMenu, setShowAttachMenu] = useState(false)
  const [showSourcePicker, setShowSourcePicker] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState('')
  const [historyEntries, setHistoryEntries] = useState<HistoryEntry[]>([])
  const [conversationHistory, setConversationHistory] = useState<ChatConversationSummary[]>([])
  const [conversationHistoryLoading, setConversationHistoryLoading] = useState(true)
  const [conversationHistoryError, setConversationHistoryError] = useState('')
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null)
  const [openPicker, setOpenPicker] = useState<string | null>(null)
  const [railOpen, setRailOpen] = useState(false)
  const [panelOpen, setPanelOpen] = useState(false)
  const [panelTab, setPanelTab] = useState<'context' | 'study' | 'actions' | 'activity'>('context')
  const [pendingActions, setPendingActions] = useState<PendingAction[]>([])
  const [sessionGrants, setSessionGrants] = useState<string[]>([])
  const [mentions, setMentions] = useState<string[]>([])
  const [mentionQuery, setMentionQuery] = useState<string | null>(null)
  const sessionGrantsRef = useRef<string[]>([])
  const [actionBusy, setActionBusy] = useState('')
  const [actionNotice, setActionNotice] = useState('')
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
    const summary: ChatConversationSummary = {
      id: updated.id,
      title: updated.title,
      courseId: updated.courseId,
      courseLabel: updated.courseLabel,
      messageCount: updated.messages.length,
      preview: (updated.messages[updated.messages.length - 1]?.content || '').slice(0, 280),
      createdAt: updated.updatedAt,
      updatedAt: updated.updatedAt,
    }
    setConversationHistory((current) => [summary, ...current.filter((conversation) => conversation.id !== id)].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)))
    setActiveConversationId(id)
    try {
      await saveChatConversation(updated)
      setConversationHistoryError('')
    } catch (reason) {
      setConversationHistoryError(`This conversation is visible for now, but could not be saved on this device. ${String(reason)}`)
    }
  }
  const updateStreaming = (update: (current: StreamState) => StreamState) => {
    const next = update(streamingRef.current ?? { content: '', progress: [], proposals: [] })
    streamingRef.current = next
    setStreaming(next)
  }
  const flushDeltas = () => {
    if (deltaTimerRef.current !== null) {
      window.clearTimeout(deltaTimerRef.current)
      deltaTimerRef.current = null
    }
    const buffered = deltaBufferRef.current
    deltaBufferRef.current = ''
    if (buffered) updateStreaming((current) => ({ ...current, content: current.content + buffered }))
  }
  const clearStreaming = () => {
    if (deltaTimerRef.current !== null) {
      window.clearTimeout(deltaTimerRef.current)
      deltaTimerRef.current = null
    }
    deltaBufferRef.current = ''
    streamingRef.current = null
    setStreaming(null)
  }
  const cancelRun = () => {
    const active = streamRef.current
    if (!active) return
    active.controller.abort()
    if (active.runId) void api.chatCancel(active.runId).catch(() => undefined)
  }
  const toggleProposalGrant = (grant: 'task' | 'import' | 'calendar' | 'actions') => {
    setProposalGrants((current) => {
      const next = current.includes(grant) ? current.filter((item) => item !== grant) : [...current, grant]
      localStorage.setItem('academia.chat.proposalGrants', JSON.stringify(next))
      return next
    })
  }
  const toggleGoogleGrant = (grant: 'gmail' | 'calendar') => {
    setGoogleGrants((current) => {
      const next = current.includes(grant) ? current.filter((item) => item !== grant) : [...current, grant]
      localStorage.setItem('academia.chat.googleGrants', JSON.stringify(next))
      return next
    })
  }
  const refreshProposalStatuses = async (current: Message[] = messagesRef.current) => {
    const reviewIds = [...new Set(current.flatMap((message) => message.proposals?.map((proposal) => proposal.review_id).filter((value): value is string => Boolean(value)) ?? []))]
    if (!reviewIds.length) return
    const results = await Promise.all(reviewIds.map((reviewId) => api.reviewShow(reviewId).catch(() => null)))
    const byId = new Map(results.filter((item): item is ReviewItem => Boolean(item)).map((item) => [item.id, item]))
    if (!byId.size) return
    const updated = current.map((message) => message.proposals?.length
      ? {
          ...message,
          proposals: message.proposals.map((proposal) => {
            const item = proposal.review_id ? byId.get(proposal.review_id) : undefined
            if (!item) return proposal
            const proposalDetails = item.details?.proposal_details
            const details = proposalDetails && typeof proposalDetails === 'object' && !Array.isArray(proposalDetails) ? proposalDetails as Record<string, unknown> : null
            const summary = typeof details?.after === 'string' && details.after.trim() ? details.after : proposal.summary
            const effects = Array.isArray(details?.effects) ? details.effects.filter((effect): effect is string => typeof effect === 'string') : proposal.effects
            return {
              ...proposal,
              summary,
              effects,
              status: item.status,
              action_status: item.action_status ?? null,
              status_label: proposalStatusLabel(item),
            }
          }),
        }
      : message)
    messagesRef.current = updated
    setMessages(updated)
    await persistConversation(updated)
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
  const providerOptions = (providerCatalog?.providers ?? []).filter((entry) => entry.id !== 'claude')
  const activeProvider = providerOptions.find((entry) => entry.id === provider)
  const apiProvider = provider.startsWith('api:')
  const modelOptions = activeProvider?.models ?? []
  const defaultModel = activeProvider?.default_model ?? ''
  const currentModel = model && modelOptions.some((entry) => entry.id === model) ? model : defaultModel
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
    if (!apiProvider || !proposalMode) return
    // API providers can propose catalog actions only.
    setProposalGrants(['actions'])
    localStorage.setItem('academia.chat.proposalGrants', JSON.stringify(['actions']))
  }, [apiProvider, proposalMode])
  useEffect(() => {
    let current = true
    const refresh = () => {
      void api.notionStatus().then((status) => {
        if (!current) return
        const available = status.auth_status === 'connected'
        setNotionAvailable(available)
        if (!available) {
          setNotionGrant(false)
          localStorage.setItem('academia.chat.notionGrant', 'false')
        }
      }).catch(() => { if (current) setNotionAvailable(false) })
    }
    refresh()
    window.addEventListener('focus', refresh)
    window.addEventListener('academia-notion-connection-changed', refresh)
    return () => {
      current = false
      window.removeEventListener('focus', refresh)
      window.removeEventListener('academia-notion-connection-changed', refresh)
    }
  }, [])
  useEffect(() => {
    let current = true
    const refresh = () => {
      void api.googleConnectorStatus().then((status) => {
        if (!current) return
        const available = status.auth_status === 'authorized'
        setGoogleAvailable(available)
        if (!available) {
          setGoogleGrants([])
          localStorage.setItem('academia.chat.googleGrants', '[]')
          setProposalGrants((current) => {
            const next = current.filter((item) => item !== 'calendar')
            localStorage.setItem('academia.chat.proposalGrants', JSON.stringify(next))
            return next
          })
        }
      }).catch(() => {
        if (!current) return
        setGoogleAvailable(false)
        setGoogleGrants([])
        localStorage.setItem('academia.chat.googleGrants', '[]')
        setProposalGrants((grants) => {
          const next = grants.filter((item) => item !== 'calendar')
          localStorage.setItem('academia.chat.proposalGrants', JSON.stringify(next))
          return next
        })
      })
    }
    refresh()
    window.addEventListener('focus', refresh)
    window.addEventListener('academia-google-connection-changed', refresh)
    return () => {
      current = false
      window.removeEventListener('focus', refresh)
      window.removeEventListener('academia-google-connection-changed', refresh)
    }
  }, [])
  useEffect(() => {
    if (reviewRevision > 0) void refreshProposalStatuses()
  }, [reviewRevision])
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
    const userMessage: Message = { role: 'user', content: text || `Please review ${pendingAttachments.map((file) => file.name).join(', ')}.`, ...(mentions.length ? { mentions: [...mentions] } : {}) }
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
          setPanelOpen(true)
          setPanelTab('study')
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
      const chatPayload = { provider, messages: boundedMessages.map(({ role, content }) => ({ role, content })), model: currentModel || null, effort, speed, attachments: uploaded.map((attachment) => ({ name: attachment.name, type: attachment.type, data: attachment.data })), course_context: courseContext, proposal_mode: proposalMode, course_id: courseId || null, semester: semester || null, granted_proposal_tools: proposalMode ? proposalGrants : [], web_search: webSearch, connector_grants: [...googleGrants, ...(notionGrant ? ['notion'] : [])] }
      let result: ChatResult
      let capturedProgress: StreamProgress[] = []
      if (proposalMode) {
        const controller = new AbortController()
        streamRef.current = { controller, runId: null }
        streamingRef.current = { content: '', progress: [], proposals: [] }
        setStreaming(streamingRef.current)
        const handleEvent = (event: ChatStreamEvent) => {
          if (event.type === 'started') {
            if (streamRef.current && typeof event.run_id === 'string') streamRef.current.runId = event.run_id
            return
          }
          if (event.type === 'tool_started') {
            const tool = typeof event.tool === 'string' ? event.tool : 'academia'
            const callId = typeof event.call_id === 'string' ? event.call_id : ''
            const id = callId || `${tool}-${Date.now()}-${Math.random()}`
            updateStreaming((current) => ({
              ...current,
              progress: [...current.progress.filter((item) => item.id !== id), { id, tool, label: toolProgressLabel(tool), state: 'running' }],
            }))
            return
          }
          if (event.type === 'tool_result') {
            const tool = typeof event.tool === 'string' ? event.tool : ''
            const callId = typeof event.call_id === 'string' ? event.call_id : ''
            updateStreaming((current) => ({
              ...current,
              progress: current.progress.map((item) => item.id === callId || (!callId && item.tool === tool && item.state === 'running') ? { ...item, state: 'done' } : item),
            }))
            return
          }
          if (event.type === 'proposal' && event.proposal && typeof event.proposal === 'object') {
            const proposal = event.proposal as ChatProposal
            updateStreaming((current) => ({ ...current, proposals: current.proposals.some((item) => item.review_id === proposal.review_id) ? current.proposals : [...current.proposals, proposal] }))
            return
          }
          if (event.type === 'delta' && typeof event.delta === 'string') {
            deltaBufferRef.current += event.delta
            if (deltaTimerRef.current === null) {
              deltaTimerRef.current = window.setTimeout(() => {
                deltaTimerRef.current = null
                const buffered = deltaBufferRef.current
                deltaBufferRef.current = ''
                if (buffered) updateStreaming((current) => ({ ...current, content: current.content + buffered }))
              }, 60)
            }
          }
        }
        try {
          result = await api.chatStream<ChatResult>(chatPayload, handleEvent, controller.signal)
        } catch (reason) {
          flushDeltas()
          const partial = streamingRef.current
          streamRef.current = null
          clearStreaming()
          if (reason instanceof ChatCancelledError || (reason instanceof Error && reason.name === 'AbortError')) {
            const cancelledMessage: Message = {
              role: 'assistant' as const,
              content: partial?.content.trim() || 'Assistant run cancelled before a final answer.',
              ...(partial?.proposals.length ? { proposals: partial.proposals } : {}),
            }
            const completed = [...nextMessages, cancelledMessage]
            messagesRef.current = completed
            setMessages(completed)
            await persistConversation(completed)
            if (partial?.proposals.length) {
              onProposalCreated()
              void refreshProposalStatuses(completed)
            }
            return
          }
          if (partial && (partial.content.trim() || partial.proposals.length)) {
            const detail = reason instanceof Error ? reason.message : String(reason)
            const failedMessage: Message = {
              role: 'assistant' as const,
              content: `${partial.content.trim()}${partial.content.trim() ? '\n\n' : ''}The assistant run ended before a final answer. ${detail}`,
              ...(partial.proposals.length ? { proposals: partial.proposals } : {}),
            }
            const completed = [...nextMessages, failedMessage]
            messagesRef.current = completed
            setMessages(completed)
            await persistConversation(completed)
            if (partial.proposals.length) {
              onProposalCreated()
              void refreshProposalStatuses(completed)
            }
            setError(detail)
            return
          }
          throw reason
        }
        capturedProgress = streamingRef.current?.progress ?? []
        flushDeltas()
        streamRef.current = null
        clearStreaming()
      } else {
        result = await api.chat<ChatResult>(chatPayload)
      }
      const runTrace = result.trace?.length ? result.trace : capturedProgress.map((step) => ({ tool: step.label, ok: step.state === 'done' }))
      const assistantMessage: Message = { role: 'assistant' as const, content: result.message, at: new Date().toISOString(), ...(result.proposals?.length ? { proposals: result.proposals } : {}), ...(runTrace.length ? { trace: runTrace } : {}) }
      const completedMessages = [...nextMessages, assistantMessage]
      setMessages(completedMessages)
      await persistConversation(completedMessages)
      if (result.proposals?.length) onProposalCreated()
      if (result.proposals?.length) void refreshProposalStatuses(completedMessages)
      void autoApplyGranted(completedMessages)
      setChatAttachments(uploaded)
      setMentions([])
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
  const resumeConversation = async (conversationId: string) => {
    if (busy || studyGenerationInProgress) return
    let conversation: ChatConversation
    try {
      conversation = await loadChatConversation(conversationId)
      setConversationHistoryError('')
    } catch (reason) {
      setConversationHistoryError(`That conversation could not be opened. ${String(reason)}`)
      return
    }
    setPendingChatStudy(null)
    setChatStudyRequest(null)
    sessionGrantsRef.current = []
    setSessionGrants([])
    archiveCurrentConversation()
    setActiveConversationId(conversation.id)
    messagesRef.current = conversation.messages
    setMessages(conversation.messages)
    void refreshProposalStatuses(conversation.messages)
    setCourseId(conversation.courseId)
    setSourceIds(conversation.sourceIds)
    setExcludedCourseSourceIds(conversation.excludedCourseSourceIds)
    setChatAttachments([])
    setAttachments([])
    setDraft('')
    setError('')
    setLastRetrievedSourceIds([])
    setHistoryOpen(false)
    setRailOpen(false)
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
    sessionGrantsRef.current = []
    setSessionGrants([])
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
      if (conversation) void resumeConversation(conversation.id)
      else setError('That saved conversation is no longer available in this workspace.')
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

  const markProposal = (proposalId: string, patch: Record<string, unknown>) => {
    setMessages((current) => current.map((message) => message.proposals?.length
      ? { ...message, proposals: message.proposals.map((proposal) => proposal.proposal_id === proposalId ? { ...proposal, ...patch } : proposal) }
      : message))
  }
  const applyProposal = async (proposalId: string) => {
    try {
      const result = await api.actionExecute(proposalId)
      markProposal(proposalId, {
        status: 'resolved',
        action_status: result.status,
        status_label: result.status === 'verified' ? 'Applied and verified' : `Status: ${result.status}`,
      })
      setActionNotice(result.status === 'verified' ? 'Applied and verified.' : `Action status: ${result.status}`)
      await refreshActions()
      onProposalCreated()
    } catch (reason) {
      setError(`The action could not be applied. ${String(reason)}`)
    }
  }
  const allowInlineProposal = (proposalId: string) => { void applyProposal(proposalId) }
  const allowAllProposals = (proposalIds: string[]) => { void (async () => { for (const id of proposalIds) await applyProposal(id) })() }
  const allowForChat = (proposalId: string, actionType: string | null) => {
    if (actionType && !sessionGrantsRef.current.includes(actionType)) {
      const next = [...sessionGrantsRef.current, actionType]
      sessionGrantsRef.current = next
      setSessionGrants(next)
    }
    void applyProposal(proposalId)
  }
  const refuseProposal = async (proposalId: string) => {
    try {
      await api.actionDiscard(proposalId)
      markProposal(proposalId, { status: 'rejected', action_status: 'rejected', status_label: 'Refused' })
      await refreshActions()
    } catch (reason) {
      setError(`The proposal could not be refused. ${String(reason)}`)
    }
  }
  const autoApplyGranted = async (list: Message[]) => {
    const grants = sessionGrantsRef.current
    if (!grants.length) return
    const targets = list.flatMap((message) => (message.proposals ?? []).filter((proposal) => proposal.tier === 'inline'
      && proposal.proposal_id
      && proposal.action_type
      && grants.includes(proposal.action_type)
      && proposal.status !== 'resolved'
      && proposal.status !== 'rejected'))
    for (const proposal of targets) {
      await applyProposal(proposal.proposal_id as string)
    }
  }
  useEffect(() => { sessionGrantsRef.current = sessionGrants }, [sessionGrants])
  useEffect(() => {
    setWebSearch(mentions.includes('web'))
    setGoogleGrants([
      ...(mentions.includes('gmail') ? ['gmail'] : []),
      ...(mentions.includes('calendar') ? ['calendar'] : []),
    ])
    setNotionGrant(mentions.includes('notion'))
    const wantsActions = mentions.includes('actions')
    setProposalMode(wantsActions)
    if (wantsActions) setProposalGrants(['actions'])
  }, [mentions])

  const refreshActions = async () => {
    try {
      const value = await api.actionPending()
      setPendingActions(value.actions)
    } catch (reason) {
      setActionNotice(`Pending actions could not be loaded. ${String(reason)}`)
    }
  }
  const allowAction = async (proposalId: string) => {
    setActionBusy(proposalId)
    setActionNotice('')
    try {
      const result = await api.actionExecute(proposalId)
      setActionNotice(result.status === 'verified' ? 'Applied and verified.' : `Action status: ${result.status}`)
      await refreshActions()
      onProposalCreated()
    } catch (reason) {
      setActionNotice(`The action could not be applied. ${String(reason)}`)
    } finally {
      setActionBusy('')
    }
  }
  const discardAction = async (proposalId: string) => {
    setActionBusy(proposalId)
    setActionNotice('')
    try {
      await api.actionDiscard(proposalId)
      setActionNotice('Declined.')
      await refreshActions()
    } catch (reason) {
      setActionNotice(`The action could not be declined. ${String(reason)}`)
    } finally {
      setActionBusy('')
    }
  }
  useEffect(() => { void refreshActions() }, [])

  const mentionLabels: Record<string, string> = { web: 'Web', gmail: 'Gmail', calendar: 'Calendar', notion: 'Notion', actions: 'Actions' }
  const mentionOptions = [
    { id: 'web', label: 'Web', hint: 'Search public pages and cite them', available: true },
    { id: 'gmail', label: 'Gmail', hint: 'Recent messages as reference', available: googleAvailable },
    { id: 'calendar', label: 'Calendar', hint: 'Upcoming events as reference', available: googleAvailable },
    { id: 'notion', label: 'Notion', hint: 'Pages shared with the integration', available: notionAvailable },
    { id: 'actions', label: 'Actions', hint: 'Let the agent propose workspace changes', available: true },
  ]
  const handleDraftChange = (value: string) => {
    setDraft(value)
    const match = /(?:^|\s)@([a-z]*)$/i.exec(value)
    setMentionQuery(match ? match[1].toLowerCase() : null)
  }
  const chooseMention = (id: string) => {
    setMentions((current) => current.includes(id) ? current : [...current, id])
    setDraft((current) => current.replace(/@[a-z]*$/i, '').replace(/\s+$/, ''))
    setMentionQuery(null)
  }

  const contextPanel = <>
            <header className="chat-panel-heading"><div><p className="eyebrow">Context</p><h3>Sources</h3></div><div className="chat-panel-actions"><button className="chat-source-bulk-toggle" type="button" onClick={toggleAllVisibleSources} disabled={!filteredItems.length} aria-label={`${allVisibleSourcesSelected ? 'Uncheck' : 'Check'} all ${sourceFilter ? 'matching ' : ''}sources`} data-tooltip={`${allVisibleSourcesSelected ? 'Uncheck' : 'Check'} all ${sourceFilter ? 'matching ' : ''}sources`} data-tooltip-side="bottom"><span>{allVisibleSourcesSelected ? 'Uncheck all' : 'Check all'}</span><small>{availableSourceCount} available</small></button><button className="chat-panel-collapse" onClick={() => setPanelOpen(false)} aria-label="Collapse panel" data-tooltip="Collapse sources" data-tooltip-side="bottom">‹</button></div></header>
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
      
  </>


  useEffect(() => {
    if (!railOpen && !panelOpen) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setRailOpen(false); setPanelOpen(false) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [railOpen, panelOpen])

  return <div className="page-stack chat-page">
    <section className="agent-workspace" aria-label="Academia agent">

      <section className="chat-main" aria-label="Conversation">
        <header className="chat-conversation-heading"><div className="chat-heading-start"><button className="agent-icon-button" type="button" onClick={() => { setRailOpen(true); setPanelOpen(false) }} aria-label="Show conversation history" title="History"><svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><rect x="3.5" y="4.5" width="13" height="11" rx="2" /><path d="M7.5 4.5v11" /></svg></button><ChatPicker id="course" icon="▣" value={courseId} placeholder="All Academia" ariaLabel="Scope" options={[{ value: '', label: 'All Academia' }, ...courses.map((entry) => ({ value: entry.id, label: entry.name.startsWith(entry.code) ? entry.name : `${entry.code} · ${entry.name}` }))]} openPicker={openPicker} setOpenPicker={setOpenPicker} onChange={selectCourse} /></div><div className="chat-heading-end"><button className="agent-icon-button" type="button" onClick={() => { setPanelOpen(true); setRailOpen(false) }} aria-label="Show panel" title="Panel"><svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><rect x="3.5" y="4.5" width="13" height="11" rx="2" /><path d="M12.5 4.5v11" /></svg></button></div></header>
        <div className="chat-messages" ref={listRef} aria-live="polite">
          {messages.length === 0 ? <div className="chat-welcome"><p className="eyebrow">{course ? `Your ${course.code} study space` : 'Academia AI'}</p><h3>{course ? `What’s next in ${course.code}?` : 'What do you need?'}</h3><p>{course ? 'Pick a goal based on this class, or ask about an idea that still feels unclear.' : 'Choose a scope above to ground answers in a class, or ask across everything in your workspace.'}</p><div className="chat-suggestions">{course ? suggestions.map((suggestion) => <button key={suggestion.label} onClick={() => setDraft(suggestion.prompt)}>{suggestion.label} <span>↗</span></button>) : <span className="chat-suggestions-empty">Choose a scope above for prompts grounded in that class.</span>}</div></div> : messages.map((message, index) => <article className={`chat-message ${message.role}`} key={index}><span className="chat-avatar">{message.role === 'user' ? 'You' : 'A'}</span><div className="chat-message-content"><small>{message.role === 'user' ? 'You' : 'Academia study assistant'}</small>{message.mentions?.length ? <div className="chat-message-mentions">{message.mentions.map((mention) => <span key={mention}>{mentionLabels[mention] ?? mention}</span>)}</div> : null}{message.attachments?.length ? <div className="chat-message-attachments">{message.attachments.map((attachment, attachmentIndex) => attachment.preview ? <figure className="chat-message-image" key={`${attachment.name}-${attachmentIndex}`}><img src={attachment.preview} alt={`Attached image: ${attachment.name}`} /><figcaption>{attachment.name}</figcaption></figure> : <div className="chat-message-file" key={`${attachment.name}-${attachmentIndex}`}><span aria-hidden="true">▤</span><span><strong>{attachment.name}</strong><small>{attachment.type.startsWith('image/') ? 'Image attachment · reattach to view' : attachment.type === 'application/pdf' ? 'PDF document' : 'Attached document'}</small></span></div>)}</div> : null}<div className="chat-rich-text">{message.role === 'assistant' && message.trace?.length ? <ChatTrace trace={message.trace} /> : null}<ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]} components={chatMarkdownComponents}>{message.content}</ReactMarkdown></div>{message.proposals?.length ? <ChatProposals proposals={message.proposals} onOpenReview={onOpenReview} onAllow={allowInlineProposal} onAllowForChat={allowForChat} onRefuse={(proposalId) => void refuseProposal(proposalId)} onAllowAll={allowAllProposals} /> : null}{message.role === 'assistant' && <ChatMessageFooter content={message.content} at={message.at} />}</div></article>)}
          {(busy || studyGenerationInProgress) && !streaming && <div className="chat-thinking" role="status" aria-live="polite"><span className="chat-avatar">A</span><span className="chat-thinking-copy"><ElapsedTimer label={studyGenerationInProgress ? 'Creating source-grounded study material' : selectedItems.length ? 'Reading selected sources' : 'Thinking'} /><span className="chat-loading-dots" aria-hidden="true"><span /><span /><span /></span></span></div>}
          {streaming && <article className="chat-message assistant streaming">
            <span className="chat-avatar">A</span>
            <div className="chat-message-content">
              <small>Academia study assistant · working</small>
              {streaming.progress.length > 0 && <ul className="chat-progress" aria-label="Assistant progress">{streaming.progress.map((item) => <li className={item.state} key={item.id}><span className="chat-progress-mark" aria-hidden="true">{item.state === 'done' ? '✓' : '·'}</span>{item.label}</li>)}</ul>}
              <div className="chat-rich-text">{streaming.content ? <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]} components={chatMarkdownComponents}>{streaming.content}</ReactMarkdown> : <span className="chat-stream-placeholder">{streaming.progress.length ? 'Working through the proposal…' : 'Starting the proposal run…'}</span>}</div>
              {streaming.proposals.length > 0 && <ChatProposals proposals={streaming.proposals} onOpenReview={onOpenReview} onAllow={allowInlineProposal} onAllowForChat={allowForChat} onRefuse={(proposalId) => void refuseProposal(proposalId)} onAllowAll={allowAllProposals} />}
            </div>
          </article>}
          
        </div>
        <div className="chat-composer-wrap">
          {error && <p className="chat-error" role="alert">{error}</p>}

          {showAttachMenu && <div className="chat-attach-menu" role="menu" aria-label="Add to this chat">
            <button role="menuitem" onClick={() => { setShowAttachMenu(false); fileInputRef.current?.click() }}><span>↑</span><span><strong>Add a file to this chat</strong><small>Images, PDF, DOCX, PPTX, and text · 12 MB each</small></span></button>
            <button role="menuitem" onClick={() => { setShowAttachMenu(false); setShowSourcePicker(true) }}><span>▤</span><span><strong>Add Academia sources</strong><small>Choose materials from any class</small></span></button>
          </div>}
          {mentionQuery !== null && <div className="chat-mentions">
            <div className="chat-mention-menu" role="listbox" aria-label="Add context">
              {mentionOptions.filter((option) => option.available && (!mentionQuery || option.id.startsWith(mentionQuery) || option.label.toLowerCase().includes(mentionQuery))).map((option) => <button type="button" role="option" key={option.id} onClick={() => chooseMention(option.id)}><strong>@{option.id}</strong><small>{option.hint}</small></button>)}
            </div>
          </div>}
          <form className="chat-composer" onSubmit={(event) => { event.preventDefault(); void send() }}>
            {(attachments.length > 0 || chatAttachments.length > 0 || selectedItems.some((item) => item.course_id !== courseId)) && <div className="chat-composer-attachments">{chatAttachments.map((file, index) => <span key={`kept-${file.name}-${index}`}>{file.type.startsWith('image/') ? '▧' : '▤'} {file.name} · in chat</span>)}{attachments.map((file, index) => <span key={`${file.name}-${index}`}>{file.type.startsWith('image/') ? '▧' : '▤'} {file.name}</span>)}{selectedItems.filter((item) => item.course_id !== courseId).map((item) => <span className="chat-source-chip" key={item.id} title={`${courses.find((entry) => entry.id === item.course_id)?.code ?? item.semester} · ${item.name}`}>▤ {item.name}<button type="button" aria-label={`Remove ${item.name} from chat`} onClick={() => toggleSource(item.id)}>×</button></span>)}</div>}
            <textarea ref={textareaRef} value={draft} onChange={(event) => handleDraftChange(event.target.value)} onPaste={pasteFiles} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void send() } }} placeholder="Ask anything about your classes…" rows={2} maxLength={12000} aria-label="Your message. Paste an image or document to attach it." />
            <div className="chat-composer-toolbar">
              <div className="chat-composer-context">
                <div className="chat-attach-anchor"><button className="chat-attach-button" type="button" aria-label="Attach a file or Academia source" aria-expanded={showAttachMenu} onClick={() => setShowAttachMenu((open) => !open)}>＋</button></div>
                <input ref={fileInputRef} className="chat-file-input" type="file" accept="application/pdf,image/png,image/jpeg,image/webp,image/gif,.docx,.pptx,.txt,.text,.md,.markdown,.csv,.json,.yaml,.yml" multiple onChange={(event) => { chooseFiles(event.target.files); event.target.value = '' }} />
                <span className={`chat-status-dot ${isAvailable ? 'available' : 'unavailable'}`} role="img" aria-label={statusLabel} data-tooltip={statusLabel} data-tooltip-side="top" />
                
              </div>
              <div className="chat-composer-controls">
                <ModelPicker
                  providers={providerOptions}
                  provider={provider}
                  model={currentModel}
                  activeName={activeProvider?.name ?? provider}
                  open={openPicker === 'model'}
                  setOpen={(next) => setOpenPicker(next ? 'model' : null)}
                  onProvider={(value) => { setProvider(value); localStorage.setItem('academia.chat.provider', value) }}
                  onModel={(value) => { setModel(value); localStorage.setItem(`academia.chat.model.${provider}`, value); if (provider === 'codex') localStorage.setItem('academia.chat.model', value); setOpenPicker(null) }}
                />
                <ChatPicker id="effort" label="Thinking" value={effort} ariaLabel="Thinking effort" options={thinkingOptions.map(([value, label]) => ({ value, label }))} openPicker={openPicker} setOpenPicker={setOpenPicker} onChange={(value) => { setEffort(value); localStorage.setItem(`academia.chat.effort.${provider}`, value); localStorage.setItem('academia.chat.effort', value) }} />

              </div>
              <div className="chat-composer-toggles">
              {notionAvailable && <button className={`chat-proposal-toggle ${notionGrant ? 'active' : ''}`} type="button" aria-label={notionGrant ? 'Notion context enabled' : 'Enable Notion context'} aria-pressed={notionGrant} disabled={busy || studyGenerationInProgress} data-tooltip={notionGrant ? 'Notion context is on · shared page text is sent to the selected AI provider for this message' : 'Use shared Notion pages as external context for this message'} data-tooltip-side="top" onClick={() => { const next = !notionGrant; setNotionGrant(next); localStorage.setItem('academia.chat.notionGrant', String(next)) }}>
                <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                  <path d="M6 4.5h8l4 4v11H6z" />
                  <path d="M14 4.5v4h4M9 12h6M9 15h6" />
                </svg>
              </button>}
              {googleAvailable && <>
                <button className={`chat-proposal-toggle ${googleGrants.includes('gmail') ? 'active' : ''}`} type="button" aria-label={googleGrants.includes('gmail') ? 'Gmail context enabled' : 'Enable Gmail context'} aria-pressed={googleGrants.includes('gmail')} disabled={busy || studyGenerationInProgress} data-tooltip={googleGrants.includes('gmail') ? 'Gmail context is on · recent message metadata and snippets are sent to the selected AI provider for this message' : 'Use recent Gmail messages as external context for this message'} data-tooltip-side="top" onClick={() => toggleGoogleGrant('gmail')}>
                  <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                    <rect x="3.5" y="5.5" width="17" height="13" rx="2" />
                    <path d="m4.5 7 7.5 6 7.5-6" />
                  </svg>
                </button>
                <button className={`chat-proposal-toggle ${googleGrants.includes('calendar') ? 'active' : ''}`} type="button" aria-label={googleGrants.includes('calendar') ? 'Calendar context enabled' : 'Enable Calendar context'} aria-pressed={googleGrants.includes('calendar')} disabled={busy || studyGenerationInProgress} data-tooltip={googleGrants.includes('calendar') ? 'Calendar context is on · upcoming events are sent to the selected AI provider for this message' : 'Use upcoming Calendar events as external context for this message'} data-tooltip-side="top" onClick={() => toggleGoogleGrant('calendar')}>
                  <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                    <rect x="4" y="5.5" width="16" height="14" rx="2" />
                    <path d="M8 3.5v4M16 3.5v4M4 10h16" />
                  </svg>
                </button>
              </>}
              <button className={`chat-search-toggle ${webSearch ? 'active' : ''}`} type="button" aria-label={webSearch ? 'Web search enabled' : 'Enable web search'} aria-pressed={webSearch} disabled={busy || studyGenerationInProgress || provider !== 'codex'} data-tooltip={webSearch ? 'Web search is on · Codex can use live web results; sources stay external and must be cited' : 'Enable web search · Codex may look up live web results for this chat'} data-tooltip-side="top" onClick={() => { const next = !webSearch; setWebSearch(next); localStorage.setItem('academia.chat.webSearch', String(next)) }}>
                <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                  <circle cx="12" cy="12" r="8.5" />
                  <path d="M3.5 12h17M12 3.5c2.4 2.5 3.6 5.3 3.6 8.5s-1.2 6-3.6 8.5c-2.4-2.5-3.6-5.3-3.6-8.5S9.6 6 12 3.5Z" />
                </svg>
              </button>
              <button className={`chat-proposal-toggle ${proposalMode ? 'active' : ''}`} type="button" aria-label={proposalMode ? 'Action proposals enabled' : 'Enable action proposals'} aria-pressed={proposalMode} disabled={busy || studyGenerationInProgress} data-tooltip={proposalMode ? 'Proposal mode is on · the assistant can create Review items but cannot approve or execute them' : 'Enable action proposals · the assistant can prepare exact task or import changes for Review'} data-tooltip-side="top" onClick={() => { const next = !proposalMode; setProposalMode(next); localStorage.setItem('academia.chat.proposals', String(next)) }}>
                <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                  <path d="M7 3.5h7l3 3v14H7z" />
                  <path d="M14 3.5v3h3" />
                  <path d="M9.5 12.5h5M9.5 15.5h5" />
                </svg>
              </button>

              </div>
              <div className="chat-composer-actions">
                  {provider === 'codex' && <button className={`chat-speed-toggle ${speed === 'fast' ? 'active' : ''}`} type="button" aria-label={`${speed === 'fast' ? 'Fast' : 'Standard'} response speed`} aria-pressed={speed === 'fast'} data-tooltip={speed === 'fast' ? 'Fast response mode · shorter waits, but it may use your ChatGPT subscription allowance faster' : 'Standard response mode · normal processing speed'} data-tooltip-side="top" onClick={() => { const nextSpeed = speed === 'fast' ? 'standard' : 'fast'; setSpeed(nextSpeed); localStorage.setItem('academia.chat.speed', nextSpeed) }}>
                  <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                    <path className="chat-speed-gauge" d="M5.05 18.95a9.8 9.8 0 1 1 13.9 0l-2.12-2.12a6.8 6.8 0 1 0-9.66 0l-2.12 2.12Z" />
                    <path className="chat-speed-needle" d="m12 13 4.4-4.4" />
                    <circle className="chat-speed-center" cx="12" cy="13" r="1.35" />
                  </svg>
                </button>}
                {streaming && <button type="button" className="chat-cancel-run" onClick={cancelRun} aria-label="Cancel assistant run"><span aria-hidden="true">■</span> Stop</button>}
                <button className="chat-send" type="submit" disabled={busy || studyGenerationInProgress || (!draft.trim() && !attachments.length) || !isAvailable || (proposalMode && proposalGrants.length === 0)} aria-label={busy || studyGenerationInProgress ? 'Sending message' : 'Send message'} aria-busy={busy || studyGenerationInProgress}>{busy || studyGenerationInProgress ? <span className="chat-loading-dots compact" aria-hidden="true"><span /><span /><span /></span> : '↑'}</button>
              </div>
            </div>
          </form>
          <div className="chat-composer-foot"><span>Paste an image or document · Enter to send · Shift + Enter for a new line</span><span>{course ? `${selectedItems.filter((item) => item.course_id === courseId).length} class sources available${selectedItems.some((item) => item.course_id !== courseId) ? ` · ${selectedItems.filter((item) => item.course_id !== courseId).length} additional` : ''}${academicContextLoading ? ' · loading course context…' : ''}${lastRetrievedSourceIds.length ? ` · ${lastRetrievedSourceIds.length} retrieved last reply` : ''}` : selectedItems.length ? `${selectedItems.length} sources added` : 'Choose a scope to use its sources automatically'}</span></div>
        </div>
      </section>

      {(railOpen || panelOpen) && <div className="agent-drawer-backdrop" role="presentation" onClick={() => { setRailOpen(false); setPanelOpen(false) }} />}
      {railOpen && <aside className="agent-drawer agent-drawer-left agent-history" aria-label="Conversation history" role="dialog" aria-modal="false">
        <header className="agent-history-heading"><div><p className="eyebrow">Academia AI</p><h3>History</h3></div><button className="chat-panel-collapse" type="button" onClick={() => setRailOpen(false)} aria-label="Collapse history">‹</button></header>
        <button className="agent-home-button" type="button" onClick={onGoHome}><span aria-hidden="true">⌂</span> Home</button>
        <button className="agent-new-chat" type="button" onClick={startNewChat} disabled={busy || studyGenerationInProgress}><span aria-hidden="true">＋</span> New chat</button>
        <div className="agent-history-list">
          {conversationHistory.map((conversation) => <button key={conversation.id} type="button" className={`agent-history-row ${conversation.id === activeConversationId ? 'active' : ''}`} onClick={() => void resumeConversation(conversation.id)} disabled={busy || studyGenerationInProgress}>
            <span>{conversation.title || 'Untitled chat'}</span>
            <small>{conversation.courseLabel || 'All classes'}{conversation.updatedAt ? ` · ${new Date(conversation.updatedAt).toLocaleDateString()}` : ''}</small>
          </button>)}
          {!conversationHistory.length && <p className="agent-history-empty">{conversationHistoryLoading ? 'Loading conversations…' : 'No conversations yet.'}</p>}
          {conversationHistoryError && <p className="agent-history-error" role="alert">{conversationHistoryError}</p>}
        </div>
        <button className="agent-history-more" type="button" onClick={() => void openHistory()} disabled={busy || studyGenerationInProgress}>Saved practice sessions</button>
      
      </aside>}
      {panelOpen && <aside className="agent-drawer agent-drawer-right agent-panel" aria-label="Agent panel" role="dialog" aria-modal="false">
          <div className="agent-panel-tabs" role="tablist" aria-label="Agent panel sections">
            <button type="button" role="tab" aria-selected={panelTab === 'context'} className={panelTab === 'context' ? 'active' : ''} onClick={() => setPanelTab('context')}>Context</button>
            <button type="button" role="tab" aria-selected={panelTab === 'study'} className={panelTab === 'study' ? 'active' : ''} onClick={() => setPanelTab('study')}>Study</button>
            <button type="button" role="tab" aria-selected={panelTab === 'actions'} className={panelTab === 'actions' ? 'active' : ''} onClick={() => setPanelTab('actions')}>Actions{pendingActions.length ? ` (${pendingActions.length})` : ''}</button>
          <button type="button" role="tab" aria-selected={panelTab === 'activity'} className={panelTab === 'activity' ? 'active' : ''} onClick={() => setPanelTab('activity')}>Activity</button>
            <button className="chat-panel-collapse" type="button" onClick={() => setPanelOpen(false)} aria-label="Collapse panel">›</button>
          </div>
          <div className="agent-panel-body">
            {panelTab === 'context' && contextPanel}
            {panelTab === 'study' && <ChatStudyStudio courses={courses} course={course} items={readableItems} selectedSourceIds={selectedItems.map((item) => item.id)} semester={semester} provider={provider} model={currentModel || undefined} isVisible onCollapse={() => setPanelOpen(false)} chatRequest={chatStudyRequest} onChatRequestComplete={onChatStudyRequestComplete} />}
            {panelTab === 'actions' && <div className="agent-actions">
            {actionNotice && <p className="agent-actions-notice" role="status">{actionNotice}</p>}
            {pendingActions.length ? pendingActions.map((action) => <article className="agent-action-card" key={action.proposal_id}>
              <header><strong>{action.title}</strong><span className={`agent-action-tier ${action.tier}`}>{action.tier}</span></header>
              {action.preview?.summary && <p>{action.preview.summary}</p>}
              {(action.preview?.changes ?? []).map((change, index) => <div className="agent-action-change" key={`${action.proposal_id}-${index}`}>
                <span>{change.label}</span>
                <code>{change.from ?? '—'} → {change.to ?? '—'}</code>
              </div>)}
              <div className="agent-action-buttons">
                {action.tier === 'review' && action.review_id
                  ? <button className="primary-button" type="button" onClick={() => { setPanelOpen(false); onOpenReview(action.review_id as string) }}>Open Review</button>
                  : <button className="primary-button" type="button" disabled={Boolean(actionBusy)} onClick={() => void allowAction(action.proposal_id)}>{actionBusy === action.proposal_id ? 'Applying…' : 'Allow'}</button>}
                <button className="quiet-button" type="button" disabled={Boolean(actionBusy)} onClick={() => void discardAction(action.proposal_id)}>Decline</button>
              </div>
            </article>) : <p className="agent-history-empty">No pending actions.</p>}
          </div>}
          {panelTab === 'activity' && <div className="agent-activity">
              {activity.length ? activity.slice(0, 40).map((entry) => <div className="agent-activity-row" key={entry.id}><span className="agent-activity-dot" aria-hidden="true" /><div><strong>{entry.title}</strong><small>{new Date(entry.created_at).toLocaleString()}</small></div></div>) : <p className="agent-history-empty">No activity recorded yet.</p>}
            </div>}
          </div>
        </aside>}

    </section>
    {showSourcePicker && <div className="chat-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setShowSourcePicker(false) }}><section className="chat-dialog chat-source-picker-dialog" role="dialog" aria-modal="true" aria-labelledby="chat-source-picker-title"><header><div><p className="eyebrow">Add to this chat</p><h3 id="chat-source-picker-title">Choose Academia sources</h3><p>{course ? `Browse materials outside ${course.code}. They’ll be attached only to this chat.` : 'Choose material from any class to add to this chat.'}</p></div><button className="chat-dialog-close" onClick={() => setShowSourcePicker(false)} aria-label="Close source picker">×</button></header><label className="chat-source-search"><span aria-hidden="true">⌕</span><input value={sourcePickerFilter} onChange={(event) => setSourcePickerFilter(event.target.value)} placeholder="Search other classes and sources" aria-label="Search sources to add" /></label><div className="chat-picker-source-groups">{pickerGroups.map(([groupId, group]) => <section className="chat-source-group" key={groupId}><header><strong>{group.name}</strong><span>{group.items.filter((item) => sourceIds.includes(item.id)).length} added</span></header>{group.items.map((item) => <label className={`chat-source-row ${sourceIds.includes(item.id) ? 'selected' : ''}`} key={item.id}><input type="checkbox" checked={sourceIds.includes(item.id)} onChange={() => toggleSource(item.id)} aria-label={`${sourceIds.includes(item.id) ? 'Remove' : 'Add'} ${item.name} ${sourceIds.includes(item.id) ? 'from' : 'to'} this chat`} /><span className="chat-source-file-icon" aria-hidden="true">{item.extension.replace('.', '').slice(0, 3).toUpperCase()}</span><span className="chat-source-copy"><strong>{item.name}</strong><small>{item.category.replaceAll('_', ' ')}{item.intake_status === 'inbox' ? ' · Intake' : ''} · {item.extension.toUpperCase()}</small></span></label>)}</section>)}{!pickerGroups.length && <div className="chat-sources-empty"><strong>No sources found</strong><p>Try another search or import material into a class first.</p></div>}</div><footer><span>{selectedItems.filter((item) => item.course_id !== courseId).length} additional source{selectedItems.filter((item) => item.course_id !== courseId).length === 1 ? '' : 's'} attached</span><button className="primary-button" onClick={() => setShowSourcePicker(false)}>Done</button></footer></section></div>}
    {historyOpen && <div className="chat-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setHistoryOpen(false) }}><section className="chat-dialog chat-history-dialog" role="dialog" aria-modal="true" aria-labelledby="chat-history-title">
      <header><div><p className="eyebrow">Pick up where you left off</p><h3 id="chat-history-title">Chat & study history</h3><p>Conversations are saved in your local workspace and stay until you delete them. Saved practice sessions remain in the class workspace. File contents and image previews are not retained; reattach original files to use them again.</p></div><button className="chat-dialog-close" onClick={() => setHistoryOpen(false)} aria-label="Close chat and study history">×</button></header>
      <div className="chat-history-content">
        {messages.length > 0 && <><p className="chat-history-section-label">Current conversation</p><div className="chat-history-list"><button className="chat-history-row chat-conversation-row" onClick={() => setHistoryOpen(false)}><span className="chat-history-icon">◌</span><span><strong>{messages.find((message) => message.role === 'user')?.content.replace(/\s+/g, ' ').slice(0, 72) || 'Study conversation'}</strong><small>{course ? `${course.code} · ${course.name}` : 'General study chat'} · {messages.length} messages</small></span><b>Current</b></button></div></>}
        {conversationHistoryLoading && <p className="chat-history-session-note" role="status">Loading saved conversations…</p>}
        {conversationHistoryError && <p className="chat-error" role="alert">{conversationHistoryError}</p>}
        {(historyLoading || historyError || historyEntries.length > 0 || conversationHistory.length > 0) && <p className="chat-history-section-label">Saved practice sessions</p>}
        {historyLoading ? <p className="chat-history-session-note" role="status">Checking saved study sessions…</p> : historyError ? <p className="chat-error" role="alert">{historyError}</p> : historyEntries.length ? <div className="chat-history-list">{historyEntries.map(({ course: entryCourse, session }) => <button className="chat-history-row" key={`${entryCourse.id}:${session.id}`} onClick={() => { setHistoryOpen(false); onResumeStudySession(entryCourse.id, session.id) }}><span className="chat-history-icon">◷</span><span><strong>{session.title}</strong><small>{entryCourse.code} · {session.status === 'active' ? 'In progress' : 'Completed'}{session.created_at ? ` · ${new Date(session.created_at).toLocaleDateString()}` : ''}</small></span><b>{session.status === 'active' ? 'Resume →' : 'Review →'}</b></button>)}</div> : conversationHistory.length > 0 && <p className="chat-history-session-note">No saved practice sessions found for these classes yet.</p>}
        {!conversationHistoryLoading && !conversationHistoryError && !conversationHistory.length && !messages.length && !historyLoading && !historyError && !historyEntries.length && <div className="chat-history-empty"><span>◷</span><strong>No chat history yet</strong><p>Your conversations will be saved in your workspace after you chat. Structured study sessions are saved separately by class.</p></div>}
      </div>
      <footer><button className="secondary-button" onClick={startNewChat} disabled={busy}>Start a new study chat</button><button className="primary-button" onClick={() => setHistoryOpen(false)}>Done</button></footer>
    </section></div>}
  </div>
}

type PickerOption = { value: string; label: string; disabled?: boolean; reason?: string }
function ModelPicker({
  providers, provider, model, activeName, open, setOpen, onProvider, onModel,
}: {
  providers: ChatProviderInfo[]
  provider: string
  model: string
  activeName: string
  open: boolean
  setOpen: (value: boolean) => void
  onProvider: (value: string) => void
  onModel: (value: string) => void
}) {
  const active = providers.find((entry) => entry.id === provider)
  const models = active?.models ?? []
  const modelLabel = models.find((entry) => entry.id === model)?.name || model || 'Provider default'
  return <div className={`chat-picker chat-picker-model ${open ? 'open' : ''}`}>
    <button className="chat-picker-trigger chat-model-trigger" type="button" aria-label={`Model: ${activeName} · ${modelLabel}`} aria-haspopup="listbox" aria-expanded={open} title={`${activeName} · ${modelLabel}`} onClick={() => setOpen(!open)}>
      <span className="chat-model-provider">{activeName}</span>
      <span className="chat-model-sep" aria-hidden="true">/</span>
      <strong>{modelLabel}</strong>
      <span className="chat-picker-caret" aria-hidden="true">⌄</span>
    </button>
    {open && <div className="chat-picker-menu chat-model-menu" role="listbox" aria-label="Provider and model">
      <p className="chat-picker-group-label">Provider</p>
      {providers.map((entry) => <button key={entry.id} type="button" role="option" aria-selected={entry.id === provider} aria-disabled={entry.available ? undefined : true} title={entry.reason || entry.notice} className={entry.id === provider ? 'selected' : ''} onClick={() => { if (entry.available) onProvider(entry.id) }}>
        <span>{entry.name}</span>
        {entry.id === provider && <span className="chat-picker-check" aria-hidden="true">✓</span>}
      </button>)}
      <p className="chat-picker-group-label">Model</p>
      {models.length ? models.map((entry) => <button key={entry.id} type="button" role="option" aria-selected={entry.id === model} className={entry.id === model ? 'selected' : ''} onClick={() => onModel(entry.id)}>
        <span>{entry.name}</span>
        {entry.id === model && <span className="chat-picker-check" aria-hidden="true">✓</span>}
      </button>) : <p className="chat-picker-empty">Choose a connected provider to see its models.</p>}
    </div>}
  </div>
}

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
  const displayLabel = selected?.label || placeholder || value
  return <div className={`chat-picker chat-picker-${id} ${id === 'course' ? 'chat-course-picker' : ''} ${open ? 'open' : ''}`} title={title}>
    <button className={`chat-picker-trigger ${label ? 'has-label' : 'course-trigger'}`} type="button" aria-label={ariaLabel} aria-haspopup="listbox" aria-expanded={open} disabled={disabled} title={label ? `${label}: ${displayLabel}` : displayLabel} onClick={() => setOpenPicker(open ? null : id)}>
      {icon && <span className="chat-picker-icon" aria-hidden="true">{icon}</span>}
      {label && <span className="chat-picker-label">{label}</span>}
      <strong>{displayLabel}</strong>
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

function ElapsedTimer({ label }: { label: string }) {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    const timer = window.setInterval(() => setSeconds((value) => value + 1), 1000)
    return () => window.clearInterval(timer)
  }, [])
  return <span className="chat-elapsed">{label}{seconds >= 1 ? ` · ${seconds}s` : ''}</span>
}

function friendlyTool(tool: string) {
  const name = tool.includes('.') ? tool.split('.').pop() || tool : tool
  return name.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function formatDuration(ms?: number | null) {
  if (ms === undefined || ms === null) return ''
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function ChatTrace({ trace }: { trace: ChatTraceStep[] }) {
  const [open, setOpen] = useState(false)
  const failed = trace.filter((step) => !step.ok).length
  const names = [...new Set(trace.map((step) => friendlyTool(step.tool)))]
  return <div className={`chat-trace ${open ? 'open' : ''}`}>
    <button type="button" className="chat-trace-toggle" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
      <span className="chat-trace-caret" aria-hidden="true">{open ? '▾' : '▸'}</span>
      <span>Used {trace.length} tool{trace.length === 1 ? '' : 's'}{failed ? ` · ${failed} failed` : ''}</span>
      <small>{names.slice(0, 3).join(', ')}{names.length > 3 ? ` +${names.length - 3}` : ''}</small>
    </button>
    {open && <ul className="chat-trace-list">
      {trace.map((step, index) => <li key={`${step.tool}-${index}`} className={step.ok ? '' : 'failed'}>
        <span className="chat-trace-dot" aria-hidden="true" />
        <strong>{friendlyTool(step.tool)}</strong>
        <code>{step.tool}</code>
        <time>{step.ok ? formatDuration(step.ms) || 'done' : 'failed'}</time>
      </li>)}
    </ul>}
  </div>
}

function ChatMessageFooter({ content, at }: { content: string; at?: string }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(content)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      setCopied(false)
    }
  }
  return <div className="chat-message-foot">
    <button type="button" className="chat-copy" onClick={() => void copy()} aria-label="Copy message">{copied ? 'Copied' : 'Copy'}</button>
    {at && <time className="chat-message-time" dateTime={at}>{new Date(at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time>}
  </div>
}
