import { useCallback, useEffect, useRef, useState } from 'react'
import SessionSidebar from './components/SessionSidebar'
import ChatWindow from './components/ChatWindow'
import Composer from './components/Composer'
import ThemeToggle from './components/ThemeToggle'
import LangToggle from './components/LangToggle'
import { makeT } from './i18n'
import type { Lang } from './i18n'
import {
  streamChat,
  listSessions,
  getSession,
  renameSession as renameSessionApi,
  deleteSession as deleteSessionApi,
  cancelChat,
} from './api/client'
import type { ChatEvent, ChatMessage, Session, StoredMessage } from './api/client'

function loadStored<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key)
    return v ? (v as T) : fallback
  } catch {
    return fallback
  }
}

function newId(): string {
  return crypto.randomUUID()
}

/** 把持久化消息转成前端 ChatMessage（补 tool 临时 id）。 */
function storedToChat(m: StoredMessage): ChatMessage {
  return {
    id: m.id,
    role: m.role,
    content: m.content,
    toolCalls: (m.tool_trace ?? []).map((tc, i) => ({
      id: `${m.id}-tool-${i}`,
      name: tc.name,
      args: tc.args,
      output: tc.output,
      status: (tc.status as 'success' | 'error' | 'running') || 'success',
      durationMs: tc.duration_ms,
    })),
  }
}

/** 把单个 SSE 事件应用到当前 assistant 消息（immutable）。 */
function applyEvent(msg: ChatMessage, event: ChatEvent): ChatMessage {
  switch (event.type) {
    case 'reasoning_start': {
      const reasoning = [...(msg.reasoning ?? []), { step: event.step, content: '' }]
      return { ...msg, reasoning }
    }
    case 'reasoning_delta': {
      const reasoning = msg.reasoning ?? []
      if (reasoning.length === 0) return msg
      const last = {
        ...reasoning[reasoning.length - 1],
        content: reasoning[reasoning.length - 1].content + event.delta,
      }
      return { ...msg, reasoning: [...reasoning.slice(0, -1), last] }
    }
    case 'tool_start': {
      const toolCalls = [
        ...(msg.toolCalls ?? []),
        { id: event.id, name: event.name, args: event.args, status: 'running' as const },
      ]
      return { ...msg, toolCalls }
    }
    case 'tool_end': {
      const toolCalls = (msg.toolCalls ?? []).map((c) =>
        c.id === event.id
          ? { ...c, status: 'success' as const, output: event.output, durationMs: event.duration_ms }
          : c,
      )
      return { ...msg, toolCalls }
    }
    case 'text_delta':
      return { ...msg, content: msg.content + event.delta }
    case 'citations':
      return { ...msg, citations: [...(msg.citations ?? []), ...event.sources] }
    case 'done':
    case 'error':
      return { ...msg, streaming: false, ...(event.type === 'error' ? { error: event.message } : {}) }
    default:
      return msg
  }
}

export default function App() {
  const [lang, setLang] = useState<Lang>(() => loadStored<Lang>('lang', 'en'))
  const [theme, setTheme] = useState<'dark' | 'light'>(() =>
    loadStored<'dark' | 'light'>('theme', 'dark'),
  )
  const t = makeT(lang)

  const [sessions, setSessions] = useState<Session[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [streaming, setStreaming] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const runIdRef = useRef<string | null>(null)

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
    try {
      localStorage.setItem('theme', theme)
    } catch {
      /* ignore */
    }
  }, [theme])

  useEffect(() => {
    try {
      localStorage.setItem('lang', lang)
    } catch {
      /* ignore */
    }
  }, [lang])

  const refreshSessions = useCallback(async () => {
    try {
      setSessions(await listSessions())
    } catch {
      /* ignore */
    }
  }, [])

  // 初始化：加载会话列表，默认恢复最近一个会话
  useEffect(() => {
    ;(async () => {
      const list = await listSessions()
      setSessions(list)
      if (list.length > 0) {
        try {
          const data = await getSession(list[0].id)
          setSessionId(list[0].id)
          setMessages(data.messages.map(storedToChat))
        } catch {
          /* ignore */
        }
      }
    })()
  }, [])

  const switchTo = useCallback(
    async (id: string) => {
      if (streaming) return
      try {
        const data = await getSession(id)
        setSessionId(id)
        setMessages(data.messages.map(storedToChat))
      } catch {
        /* ignore */
      }
    },
    [streaming],
  )

  const newSession = useCallback(() => {
    if (streaming) return
    setSessionId(null)
    setMessages([])
  }, [streaming])

  const handleDelete = useCallback(
    async (id: string) => {
      await deleteSessionApi(id)
      await refreshSessions()
      if (id === sessionId) {
        setSessionId(null)
        setMessages([])
      }
    },
    [sessionId, refreshSessions],
  )

  const handleRename = useCallback(
    async (id: string, title: string) => {
      await renameSessionApi(id, title)
      await refreshSessions()
    },
    [refreshSessions],
  )

  const send = useCallback(
    async (text: string) => {
      if (!text.trim() || streaming) return

      const userMsg: ChatMessage = { id: newId(), role: 'user', content: text }
      const assistantId = newId()
      const assistantMsg: ChatMessage = {
        id: assistantId,
        role: 'assistant',
        content: '',
        streaming: true,
        reasoning: [],
        toolCalls: [],
        citations: [],
      }
      setMessages((prev) => [...prev, userMsg, assistantMsg])
      setStreaming(true)

      const controller = new AbortController()
      abortRef.current = controller

      try {
        await streamChat(
          text,
          sessionId,
          (event) => {
            if (event.type === 'meta') {
              if (event.session_id) setSessionId(event.session_id)
              runIdRef.current = event.run_id
            }
            setMessages((prev) => {
              const idx = prev.findIndex((m) => m.id === assistantId)
              if (idx === -1) return prev
              const next = [...prev]
              next[idx] = applyEvent(next[idx], event)
              return next
            })
          },
          controller.signal,
        )
      } catch (e) {
        if ((e as Error).name !== 'AbortError') {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? { ...m, streaming: false, error: (e as Error).message }
                : m,
            ),
          )
        }
      } finally {
        setStreaming(false)
        abortRef.current = null
        runIdRef.current = null
        setMessages((prev) =>
          prev.map((m) => (m.id === assistantId ? { ...m, streaming: false } : m)),
        )
        await refreshSessions()
      }
    },
    [sessionId, streaming, refreshSessions],
  )

  const stop = useCallback(() => {
    const rid = runIdRef.current
    if (rid) cancelChat(rid).catch(() => {})
    abortRef.current?.abort()
  }, [])

  const regenerate = useCallback(
    (assistantId: string) => {
      if (streaming) return
      const idx = messages.findIndex((m) => m.id === assistantId)
      if (idx < 0) return
      let userIdx = -1
      for (let i = idx - 1; i >= 0; i--) {
        if (messages[i].role === 'user') {
          userIdx = i
          break
        }
      }
      if (userIdx < 0) return
      const userContent = messages[userIdx].content
      setMessages((prev) => prev.slice(0, userIdx))
      send(userContent)
    },
    [messages, streaming, send],
  )

  const editMessage = useCallback(
    (userId: string, newText: string) => {
      if (streaming) return
      const idx = messages.findIndex((m) => m.id === userId)
      if (idx < 0) return
      setMessages((prev) => prev.slice(0, idx))
      send(newText)
    },
    [messages, streaming, send],
  )

  return (
    <div className="flex h-full bg-white text-gray-900 dark:bg-gray-950 dark:text-gray-100">
      <SessionSidebar
        sessions={sessions}
        currentId={sessionId}
        onNew={newSession}
        onSwitch={switchTo}
        onDelete={handleDelete}
        onRename={handleRename}
        t={t}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-gray-200 px-4 py-3 dark:border-gray-800">
          <div className="min-w-0">
            <h1 className="truncate text-lg font-semibold">{t('appTitle')}</h1>
            <p className="truncate text-xs text-gray-500 dark:text-gray-400">{t('appCaption')}</p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <LangToggle lang={lang} onChange={setLang} />
            <ThemeToggle theme={theme} onChange={setTheme} t={t} />
          </div>
        </header>
        <ChatWindow
          messages={messages}
          t={t}
          onRegenerate={regenerate}
          onEdit={editMessage}
        />
        <Composer onSend={send} onStop={stop} streaming={streaming} t={t} />
      </div>
    </div>
  )
}
