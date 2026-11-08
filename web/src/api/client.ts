// 后端 API 客户端：SSE 流式聊天 + 会话管理 REST。

export interface Source {
  title?: string
  url?: string
  snippet?: string
}

export interface ReasoningStep {
  step: number
  content: string
}

export interface ToolCall {
  id: string
  name: string
  args: Record<string, unknown>
  output?: string
  status: 'running' | 'success' | 'error'
  durationMs?: number
}

export type ChatEvent =
  | { type: 'meta'; session_id: string; model: string; run_id: string }
  | { type: 'reasoning_start'; step: number }
  | { type: 'reasoning_delta'; delta: string }
  | { type: 'reasoning_end' }
  | { type: 'tool_start'; id: string; name: string; args: Record<string, unknown> }
  | { type: 'tool_end'; id: string; name: string; output: string; status: string; duration_ms: number }
  | { type: 'text_delta'; delta: string }
  | { type: 'citations'; sources: Source[] }
  | { type: 'done'; answer?: string }
  | { type: 'error'; message: string }

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  reasoning?: ReasoningStep[]
  toolCalls?: ToolCall[]
  citations?: Source[]
  streaming?: boolean
  error?: string
}

export interface Session {
  id: string
  title: string
  created_at: string
  updated_at: string
}

/**
 * 流式聊天：POST /api/chat，逐条解析 SSE 事件回调。
 * 用 fetch + ReadableStream（而非 EventSource），因为 chat 是 POST，且需要 AbortController 支持停止。
 */
export async function streamChat(
  message: string,
  sessionId: string | null,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId }),
    signal,
  })
  if (!resp.ok) {
    throw new Error(`chat 请求失败: ${resp.status}`)
  }
  if (!resp.body) {
    throw new Error('响应无 body')
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let idx: number
    while ((idx = buffer.indexOf('\n\n')) >= 0) {
      const raw = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      for (const line of raw.split('\n')) {
        if (line.startsWith('data: ')) {
          const event = JSON.parse(line.slice(6)) as ChatEvent
          onEvent(event)
        }
      }
    }
  }
}

// ---------- 会话 REST ----------

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!resp.ok) throw new Error(`${url} 请求失败: ${resp.status}`)
  return resp.json() as Promise<T>
}

export const listSessions = () => req<Session[]>('/api/sessions')

export const createSession = () =>
  req<Session>('/api/sessions', { method: 'POST', body: JSON.stringify({ title: '' }) })

// 后端持久化的消息结构（tool_trace 无 id，加载历史时需补临时 id）
export interface StoredToolCall {
  name: string
  args: Record<string, unknown>
  output: string
  status: string
  duration_ms: number
}

export interface StoredMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  tool_trace: StoredToolCall[]
  created_at: string
}

export const getSession = (id: string) =>
  req<Session & { messages: StoredMessage[] }>(`/api/sessions/${id}`)

export const renameSession = (id: string, title: string) =>
  req<{ ok: boolean }>(`/api/sessions/${id}`, {
    method: 'PATCH',
    body: JSON.stringify({ title }),
  })

export const deleteSession = (id: string) =>
  req<{ ok: boolean }>(`/api/sessions/${id}`, { method: 'DELETE' })

export const cancelChat = (runId: string) =>
  req<{ ok: boolean }>(`/api/chat/${runId}/cancel`, { method: 'POST' })
