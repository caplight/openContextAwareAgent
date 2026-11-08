import { useState } from 'react'
import type { ToolCall } from '../api/client'

interface Props {
  call: ToolCall
  t: (key: string) => string
}

function toolIcon(name: string): string {
  if (name.startsWith('k8s')) return '🖥️'
  if (name === 'kb_search') return '📚'
  if (name === 'web_search') return '🌐'
  return '🔧'
}

const STATUS_STYLE: Record<ToolCall['status'], string> = {
  running: 'text-blue-500 dark:text-blue-400',
  success: 'text-emerald-600 dark:text-emerald-400',
  error: 'text-red-600 dark:text-red-400',
}

const STATUS_LABEL: Record<ToolCall['status'], string> = {
  running: 'statusRunning',
  success: 'statusSuccess',
  error: 'statusError',
}

export default function ToolCallCard({ call, t }: Props) {
  const [showArgs, setShowArgs] = useState(false)
  const [showOutput, setShowOutput] = useState(false)

  return (
    <div className="mb-2 overflow-hidden rounded-lg border border-gray-200 dark:border-gray-800">
      <div className="flex items-center gap-2 bg-gray-50 px-3 py-2 dark:bg-gray-900">
        <span className="text-sm">{toolIcon(call.name)}</span>
        <span className="font-mono text-xs font-semibold text-gray-800 dark:text-gray-200">
          {call.name}
        </span>
        <span className={`text-xs font-medium ${STATUS_STYLE[call.status]}`}>
          {call.status === 'running' ? (
            <span className="inline-flex items-center gap-1">
              <span className="h-2 w-2 animate-pulse rounded-full bg-blue-500" />
              {t(STATUS_LABEL[call.status])}
            </span>
          ) : (
            t(STATUS_LABEL[call.status])
          )}
        </span>
        {call.durationMs != null && (
          <span className="ml-auto text-xs text-gray-400">{call.durationMs}ms</span>
        )}
      </div>

      <div className="px-3 py-2 text-xs">
        <button
          onClick={() => setShowArgs((v) => !v)}
          className="mb-1 font-medium text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
        >
          {t('args')} ▾
        </button>
        {showArgs && (
          <pre className="mb-2 overflow-x-auto rounded bg-gray-100 p-2 font-mono text-xs text-gray-700 dark:bg-gray-800 dark:text-gray-300">
            {JSON.stringify(call.args, null, 2)}
          </pre>
        )}

        {call.output != null && (
          <>
            <button
              onClick={() => setShowOutput((v) => !v)}
              className="mb-1 font-medium text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
            >
              {t('output')} ▾
            </button>
            {showOutput && (
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded bg-gray-100 p-2 font-mono text-xs text-gray-700 dark:bg-gray-800 dark:text-gray-300">
                {call.output}
              </pre>
            )}
          </>
        )}
      </div>
    </div>
  )
}
