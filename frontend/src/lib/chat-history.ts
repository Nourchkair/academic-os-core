export type ChatMessageAttachment = { name: string; type: string; preview?: string }
export type ChatProposal = {
  kind: string
  title: string
  summary: string
  effects: string[]
  review_id: string
  proposal_id?: string | null
}
export type ChatMessage = { role: 'user' | 'assistant'; content: string; attachments?: ChatMessageAttachment[]; proposals?: ChatProposal[] }

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

export type StudyChatRequest =
  | { id: string; action: 'open'; conversationId: string }
  | { id: string; action: 'new'; courseId: string; prompt?: string }

const databaseName = 'academia-os-dashboard'
const databaseVersion = 2
const conversationStore = 'chat-conversations'
let persistenceRequest: Promise<boolean> | null = null

function requestPersistentStorage(): Promise<boolean> {
  if (!navigator.storage?.persist) return Promise.resolve(false)
  persistenceRequest ??= navigator.storage.persist().catch(() => false)
  return persistenceRequest
}

function withoutAttachmentPreviews(value: unknown): ChatConversation | null {
  if (!value || typeof value !== 'object') return null
  const conversation = value as Partial<ChatConversation>
  if (!Array.isArray(conversation.messages)) return null
  const sanitized = {
    ...conversation,
    messages: conversation.messages.map((message) => {
      if (!message || typeof message !== 'object') return message
      const { attachments, ...rest } = message
      return {
        ...rest,
        ...(Array.isArray(attachments) ? {
          attachments: attachments.map((attachment) => {
            if (!attachment || typeof attachment !== 'object') return attachment
            const metadata = { ...attachment }
            delete metadata.preview
            return metadata
          }),
        } : attachments === undefined ? {} : { attachments }),
      }
    }),
  }
  return isConversation(sanitized) ? sanitized : null
}

export function stripChatAttachmentPreviews(conversation: ChatConversation): ChatConversation {
  return withoutAttachmentPreviews(conversation) ?? conversation
}

async function openDatabase(): Promise<IDBDatabase> {
  if (!('indexedDB' in window)) return Promise.reject(new Error('Local chat history is unavailable in this browser.'))
  await requestPersistentStorage()

  return new Promise((resolve, reject) => {
    const request = window.indexedDB.open(databaseName, databaseVersion)
    request.onupgradeneeded = (event) => {
      const database = request.result
      if (!database.objectStoreNames.contains(conversationStore)) database.createObjectStore(conversationStore, { keyPath: 'id' })
      const oldVersion = (event as IDBVersionChangeEvent).oldVersion
      if (oldVersion > 0 && oldVersion < 2) {
        const cursorRequest = request.transaction?.objectStore(conversationStore).openCursor()
        if (cursorRequest) cursorRequest.onsuccess = () => {
          const cursor = cursorRequest.result
          if (!cursor) return
          const sanitized = withoutAttachmentPreviews(cursor.value)
          if (sanitized) cursor.update(sanitized)
          cursor.continue()
        }
      }
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error || new Error('Could not open local chat history.'))
    request.onblocked = () => reject(new Error('Local chat history is busy in another dashboard tab. Close the other tab and try again.'))
  })
}

function isConversation(value: unknown): value is ChatConversation {
  if (!value || typeof value !== 'object') return false
  const conversation = value as Partial<ChatConversation>
  return typeof conversation.id === 'string'
    && typeof conversation.title === 'string'
    && typeof conversation.courseId === 'string'
    && typeof conversation.courseLabel === 'string'
    && Array.isArray(conversation.messages)
    && conversation.messages.every((message) => message && (message.role === 'user' || message.role === 'assistant') && typeof message.content === 'string'
      && (message.attachments === undefined || (Array.isArray(message.attachments) && message.attachments.every((attachment) => attachment
        && typeof attachment.name === 'string' && typeof attachment.type === 'string'
        && (attachment.preview === undefined || (typeof attachment.preview === 'string' && attachment.preview.length <= 180_000))))))
    && Array.isArray(conversation.sourceIds) && conversation.sourceIds.every((id) => typeof id === 'string')
    && Array.isArray(conversation.excludedCourseSourceIds) && conversation.excludedCourseSourceIds.every((id) => typeof id === 'string')
    && typeof conversation.updatedAt === 'string'
}

export async function listChatConversations(): Promise<ChatConversation[]> {
  const database = await openDatabase()
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(conversationStore, 'readonly')
    const request = transaction.objectStore(conversationStore).getAll()
    let conversations: ChatConversation[] = []
    request.onsuccess = () => {
      conversations = (request.result as unknown[]).filter(isConversation)
        .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
    }
    transaction.oncomplete = () => { database.close(); resolve(conversations) }
    transaction.onerror = () => { database.close(); reject(transaction.error || new Error('Could not read local chat history.')) }
    transaction.onabort = () => { database.close(); reject(transaction.error || new Error('Could not read local chat history.')) }
  })
}

export async function saveChatConversation(conversation: ChatConversation): Promise<void> {
  const database = await openDatabase()
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(conversationStore, 'readwrite')
    transaction.objectStore(conversationStore).put(conversation)
    transaction.oncomplete = () => { database.close(); resolve() }
    transaction.onerror = () => { database.close(); reject(transaction.error || new Error('Could not save this conversation locally.')) }
    transaction.onabort = () => { database.close(); reject(transaction.error || new Error('Could not save this conversation locally.')) }
  })
}

export async function deleteChatConversation(id: string): Promise<void> {
  const database = await openDatabase()
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(conversationStore, 'readwrite')
    transaction.objectStore(conversationStore).delete(id)
    transaction.oncomplete = () => { database.close(); resolve() }
    transaction.onerror = () => { database.close(); reject(transaction.error || new Error('Could not delete this local conversation.')) }
    transaction.onabort = () => { database.close(); reject(transaction.error || new Error('Could not delete this local conversation.')) }
  })
}
