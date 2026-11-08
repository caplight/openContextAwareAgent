import { useState } from 'react'
import type { ChatMessage } from '../api/client'
import Markdown from './Markdown'
import ReasoningBlock from './ReasoningBlock'
import ToolCallCard from './ToolCallCard'
import CitationList from './CitationList'

interface Props {
  message: ChatMessage
  t: (key: string) => string
  onRegenerate?: (assistantId: string) => void
  onEdit?: (userId: string, text: string) => void
}

function TypingIndicator() {
  return (
    <div className="flex items-center gap-1 py-2">
      <span className="h-2 w-2 animate-bounce rounded-full bg-gray-400 [animation-delay:0ms]" />
      <span className="h-2 w-2 animate-bounce rounded-full bg-gray-400 [animation-delay:150ms]" />
      <span className="h-2 w-2 animate-bounce rounded-full bg-gray-400 [animation-delay:300ms]" />
    </div>
  )
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    /* ignore */
  }
}

function ActionButton({
  label,
  onClick,
}: {
  label: string
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className="rounded px-1.5 py-0.5 text-xs text-gray-400 transition hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-800 dark:hover:text-gray-300"
    >
      {label}
    </button>
  )
}

export default function MessageBubble({ message, t, onRegenerate, onEdit }: Props) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(message.content)

  if (message.role === 'user') {
    if (editing) {
      return (
        <div className="flex justify-end">
          <div className="w-full max-w-[80%]">
            <textarea
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  const text = draft.trim()
                  if (text) onEdit?.(message.id, text)
                }
                if (e.key === 'Escape') setEditing(false)
              }}
              className="w-full resize-none rounded-2xl border border-blue-400 bg-white px-4 py-2 text-sm text-gray-900 outline-none dark:bg-gray-800 dark:text-gray-100"
            />
            <div className="mt-1 flex justify-end gap-2 text-xs text-gray-400">
              <span>{t('editHint')}</span>
            </div>
          </div>
        </div>
      )
    }
    return (
      <div className="group flex justify-end">
        <div className="flex max-w-[80%] flex-col items-end">
          <div className="whitespace-pre-wrap rounded-2xl bg-blue-600 px-4 py-2 text-sm text-white">
            {message.content}
          </div>
          <div className="mt-1 hidden gap-1 group-hover:flex">
            <ActionButton label={t('copy')} onClick={() => copyText(message.content)} />
            <ActionButton label={t('edit')} onClick={() => setEditing(true)} />
          </div>
        </div>
      </div>
    )
  }

  const hasReasoning = message.reasoning && message.reasoning.length > 0
  const hasTools = message.toolCalls && message.toolCalls.length > 0
  const isThinking = message.streaming && !message.content

  return (
    <div className="group max-w-[85%]">
      {hasReasoning && (
        <ReasoningBlock steps={message.reasoning!} t={t} streaming={message.streaming} />
      )}
      {hasTools && (
        <div className="mb-2">
          {message.toolCalls!.map((c) => (
            <ToolCallCard key={c.id} call={c} t={t} />
          ))}
        </div>
      )}
      {message.content && <Markdown>{message.content}</Markdown>}
      {isThinking && <TypingIndicator />}
      {message.error && (
        <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600 dark:bg-red-900/20 dark:text-red-400">
          {t('streamError')}: {message.error}
        </div>
      )}
      {message.citations && message.citations.length > 0 && (
        <CitationList sources={message.citations} t={t} />
      )}
      {!message.streaming && (
        <div className="mt-1 hidden gap-1 group-hover:flex">
          <ActionButton label={t('copy')} onClick={() => copyText(message.content)} />
          {onRegenerate && (
            <ActionButton label={t('regenerate')} onClick={() => onRegenerate(message.id)} />
          )}
        </div>
      )}
    </div>
  )
}
