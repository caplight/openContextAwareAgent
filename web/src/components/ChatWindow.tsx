import { useEffect, useRef } from 'react'
import type { ChatMessage } from '../api/client'
import MessageBubble from './MessageBubble'

interface Props {
  messages: ChatMessage[]
  t: (key: string) => string
  onRegenerate?: (assistantId: string) => void
  onEdit?: (userId: string, text: string) => void
}

export default function ChatWindow({ messages, t, onRegenerate, onEdit }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' })
  }, [messages])

  if (messages.length === 0) {
    return (
      <main className="flex flex-1 items-center justify-center">
        <p className="text-gray-400 dark:text-gray-600">{t('emptyChat')}</p>
      </main>
    )
  }

  return (
    <main className="flex-1 overflow-y-auto px-4 py-4">
      <div className="mx-auto flex max-w-3xl flex-col gap-4">
        {messages.map((m) => (
          <MessageBubble
            key={m.id}
            message={m}
            t={t}
            onRegenerate={onRegenerate}
            onEdit={onEdit}
          />
        ))}
        <div ref={bottomRef} />
      </div>
    </main>
  )
}
