import { useState } from 'react'
import type { Session } from '../api/client'

interface Props {
  sessions: Session[]
  currentId: string | null
  onNew: () => void
  onSwitch: (id: string) => void
  onDelete: (id: string) => void
  onRename: (id: string, title: string) => void
  t: (key: string) => string
}

export default function SessionSidebar({
  sessions,
  currentId,
  onNew,
  onSwitch,
  onDelete,
  onRename,
  t,
}: Props) {
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')

  function startRename(s: Session) {
    setEditingId(s.id)
    setDraft(s.title)
  }

  function commitRename(id: string) {
    const title = draft.trim()
    if (title) onRename(id, title)
    setEditingId(null)
  }

  function handleDelete(id: string) {
    if (window.confirm(t('confirmDelete'))) onDelete(id)
  }

  return (
    <aside className="flex w-64 shrink-0 flex-col border-r border-gray-200 bg-gray-50 dark:border-gray-800 dark:bg-gray-900">
      <div className="p-3">
        <button
          onClick={onNew}
          className="flex w-full items-center justify-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-100 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
        >
          <span className="text-base leading-none">+</span>
          {t('newChat')}
        </button>
      </div>

      <div className="px-3 pb-2 text-xs font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">
        {t('sessions')}
      </div>

      <nav className="flex-1 space-y-1 overflow-y-auto px-2 pb-3">
        {sessions.length === 0 && (
          <p className="px-2 py-2 text-sm text-gray-400 dark:text-gray-600">
            {t('emptySessions')}
          </p>
        )}
        {sessions.map((s) => {
          const active = s.id === currentId
          if (editingId === s.id) {
            return (
              <div key={s.id} className="px-1 py-1">
                <input
                  autoFocus
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onBlur={() => commitRename(s.id)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') commitRename(s.id)
                    if (e.key === 'Escape') setEditingId(null)
                  }}
                  className="w-full rounded-md border border-blue-400 bg-white px-2 py-1 text-sm outline-none dark:bg-gray-800"
                />
              </div>
            )
          }
          return (
            <div
              key={s.id}
              onClick={() => onSwitch(s.id)}
              className={`group flex cursor-pointer items-center justify-between rounded-lg px-2 py-2 text-sm transition ${
                active
                  ? 'bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300'
                  : 'text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800'
              }`}
            >
              <span className="min-w-0 flex-1 truncate">
                {s.title || t('untitled')}
              </span>
              <span className="ml-1 hidden shrink-0 gap-1 group-hover:flex">
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    startRename(s)
                  }}
                  title={t('rename')}
                  className="rounded p-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
                >
                  ✎
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    handleDelete(s.id)
                  }}
                  title={t('delete')}
                  className="rounded p-1 text-gray-400 hover:text-red-500"
                >
                  ✕
                </button>
              </span>
            </div>
          )
        })}
      </nav>
    </aside>
  )
}
