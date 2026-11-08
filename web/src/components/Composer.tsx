import { useState } from 'react'
import type { KeyboardEvent } from 'react'

interface Props {
  onSend: (text: string) => void
  onStop: () => void
  streaming: boolean
  t: (key: string) => string
}

export default function Composer({ onSend, onStop, streaming, t }: Props) {
  const [value, setValue] = useState('')

  function handleSend() {
    const text = value.trim()
    if (!text || streaming) return
    onSend(text)
    setValue('')
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="border-t border-gray-200 p-4 dark:border-gray-800">
      <div className="mx-auto flex max-w-3xl items-end gap-2">
        <textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={t('inputPlaceholder')}
          rows={1}
          className="max-h-40 flex-1 resize-none rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-500 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-100 dark:focus:border-blue-400"
        />
        {streaming ? (
          <button
            onClick={onStop}
            className="flex h-9 shrink-0 items-center justify-center gap-1.5 rounded-lg bg-red-600 px-4 text-sm font-medium text-white transition hover:bg-red-700"
          >
            <span className="h-2.5 w-2.5 rounded-sm bg-white" />
            {t('stop')}
          </button>
        ) : (
          <button
            onClick={handleSend}
            disabled={!value.trim()}
            className="flex h-9 shrink-0 items-center justify-center rounded-lg bg-blue-600 px-4 text-sm font-medium text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {t('send')}
          </button>
        )}
      </div>
    </div>
  )
}
