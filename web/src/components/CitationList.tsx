import type { Source } from '../api/client'

interface Props {
  sources: Source[]
  t: (key: string) => string
}

export default function CitationList({ sources, t }: Props) {
  if (sources.length === 0) return null

  return (
    <div className="mt-3 border-t border-gray-200 pt-2 dark:border-gray-800">
      <p className="mb-1 text-xs font-semibold text-gray-500 dark:text-gray-400">{t('sources')}</p>
      <ul className="space-y-1">
        {sources.map((s, i) => (
          <li key={i} className="text-xs">
            {s.url ? (
              <a
                href={s.url}
                target="_blank"
                rel="noreferrer"
                className="text-blue-600 hover:underline dark:text-blue-400"
              >
                {s.title || s.url}
              </a>
            ) : (
              <span className="text-gray-600 dark:text-gray-400">{s.title}</span>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
