import { useState } from 'react'
import type { ReasoningStep } from '../api/client'

interface Props {
  steps: ReasoningStep[]
  t: (key: string) => string
  streaming?: boolean
}

export default function ReasoningBlock({ steps, t, streaming }: Props) {
  const [open, setOpen] = useState(false)
  const content = steps.map((s) => s.content).join('\n\n')

  return (
    <div className="mb-2">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-xs font-medium text-gray-500 transition hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
      >
        <svg viewBox="0 0 24 24" className={`h-3.5 w-3.5 transition-transform ${open ? 'rotate-90' : ''}`} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M9 18l6-6-6-6" />
        </svg>
        <span>{t('thinking')}</span>
        {streaming && <span className="animate-pulse">…</span>}
      </button>
      {open && (
        <div className="mt-1.5 whitespace-pre-wrap rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs leading-relaxed text-gray-600 dark:border-gray-800 dark:bg-gray-900 dark:text-gray-400">
          {content}
        </div>
      )}
    </div>
  )
}
