export type ChatMessageAttachment = { name: string; type: string; preview?: string }
export type ChatProposal = {
  kind: string
  title: string
  summary: string
  effects: string[]
  review_id: string | null
  proposal_id?: string | null
  tier?: 'auto' | 'inline' | 'review' | null
  action_type?: string | null
  status?: string | null
  action_status?: string | null
  status_label?: string
}
export type ChatTraceStep = { tool: string; ok: boolean; ms?: number | null }
export type ChatMessage = { role: 'user' | 'assistant'; content: string; at?: string; attachments?: ChatMessageAttachment[]; proposals?: ChatProposal[]; trace?: ChatTraceStep[]; mentions?: string[] }

export type ChatConversation = {
  id: string
  title: string
  courseId: string
  courseLabel: string
  messages: ChatMessage[]
  sourceIds: string[]
  excludedCourseSourceIds: string[]
  updatedAt: string
}

export type ChatConversationSummary = {
  id: string
  title: string
  courseId: string
  courseLabel: string
  messageCount: number
  preview: string
  createdAt: string
  updatedAt: string
}

export type StudyChatRequest =
  | { id: string; action: 'open'; conversationId: string }
  | { id: string; action: 'new'; courseId: string; prompt?: string }

const sessionsPath = '/api/v1/agent/sessions'
const migrationKey = 'academia.chat.historyMigrated.v1'

function isDesktopShell() {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
}

async function invokeSessions<T>(args: string[]): Promise<T> {
  const { invoke } = await import('@tauri-apps/api/core')
  const raw = await invoke<string>('academia_command', { command: 'sessions', args })
  return JSON.parse(raw) as T
}

async function failure(response: Response): Promise<Error> {
  try {
    const value = await response.json()
    if (value && typeof value.error === 'string') return new Error(value.error)
  } catch {
    /* fall through */
  }
  return new Error(`The workspace returned HTTP ${response.status}.`)
}

export function stripChatAttachmentPreviews(conversation: ChatConversation): ChatConversation {
  return {
    ...conversation,
    messages: conversation.messages.map((message) => {
      if (!Array.isArray(message.attachments)) return message
      return {
        ...message,
        attachments: message.attachments.map(({ name, type }) => ({ name, type })),
      }
    }),
  }
}

function isConversation(value: unknown): value is ChatConversation {
  if (!value || typeof value !== 'object') return false
  const conversation = value as Partial<ChatConversation>
  return typeof conversation.id === 'string'
    && typeof conversation.title === 'string'
    && typeof conversation.courseId === 'string'
    && typeof conversation.courseLabel === 'string'
    && Array.isArray(conversation.messages)
    && Array.isArray(conversation.sourceIds)
    && Array.isArray(conversation.excludedCourseSourceIds)
    && typeof conversation.updatedAt === 'string'
}

export async function listChatConversations(): Promise<ChatConversationSummary[]> {
  let sessions: unknown[] = []
  if (isDesktopShell()) {
    const value = await invokeSessions<{ sessions?: unknown[] }>(['list', '--json'])
    sessions = Array.isArray(value?.sessions) ? value.sessions : []
  } else {
    const response = await fetch(sessionsPath)
    if (!response.ok) throw await failure(response)
    const value = await response.json()
    sessions = Array.isArray(value?.sessions) ? value.sessions : []
  }
  const summaries = sessions.filter((session: unknown): session is ChatConversationSummary => Boolean(session)
    && typeof (session as ChatConversationSummary).id === 'string'
    && typeof (session as ChatConversationSummary).title === 'string')
  if (!summaries.length) await migrateLegacyHistory()
  return summaries
}

export async function loadChatConversation(id: string): Promise<ChatConversation> {
  const value = isDesktopShell()
    ? await invokeSessions<{ session?: unknown }>(['load', id, '--json'])
    : await fetch(`${sessionsPath}/load?id=${encodeURIComponent(id)}`).then(async (response) => {
        if (!response.ok) throw await failure(response)
        return response.json() as Promise<{ session?: unknown }>
      })
  if (!isConversation(value?.session)) throw new Error('That conversation could not be read.')
  return value.session
}

export async function saveChatConversation(conversation: ChatConversation): Promise<void> {
  const payload = { session: stripChatAttachmentPreviews(conversation) }
  if (isDesktopShell()) {
    const { invoke } = await import('@tauri-apps/api/core')
    await invoke<string>('academia_sessions_save', { payload })
    return
  }
  const response = await fetch(`${sessionsPath}/save`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) throw await failure(response)
}

export async function deleteChatConversation(id: string): Promise<void> {
  if (isDesktopShell()) {
    await invokeSessions(['delete', id, '--json'])
    return
  }
  const response = await fetch(`${sessionsPath}/delete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id }),
  })
  if (!response.ok) throw await failure(response)
}

type LegacyConversation = ChatConversation

async function readLegacyIndexedDb(): Promise<LegacyConversation[]> {
  if (typeof window === 'undefined' || !('indexedDB' in window)) return []
  return new Promise((resolve) => {
    let settled = false
    const finish = (value: LegacyConversation[]) => {
      if (settled) return
      settled = true
      resolve(value)
    }
    const request = window.indexedDB.open('academia-os-dashboard')
    request.onupgradeneeded = () => finish([])
    request.onerror = () => finish([])
    request.onsuccess = () => {
      const database = request.result
      if (!database.objectStoreNames.contains('chat-conversations')) {
        database.close()
        finish([])
        return
      }
      try {
        const transaction = database.transaction('chat-conversations', 'readonly')
        const all = transaction.objectStore('chat-conversations').getAll()
        all.onsuccess = () => {
          database.close()
          finish((all.result as unknown[]).filter(isConversation))
        }
        all.onerror = () => {
          database.close()
          finish([])
        }
      } catch {
        database.close()
        finish([])
      }
    }
  })
}

/** One-time move of browser-era conversations into the local workspace store. */
export async function migrateLegacyHistory(): Promise<number> {
  if (typeof window === 'undefined') return 0
  if (window.localStorage.getItem(migrationKey) === 'done') return 0
  const legacy = await readLegacyIndexedDb()
  let migrated = 0
  for (const conversation of legacy) {
    try {
      await saveChatConversation(conversation)
      migrated += 1
    } catch {
      /* keep going; a single broken conversation must not block the rest */
    }
  }
  window.localStorage.setItem(migrationKey, 'done')
  return migrated
}
