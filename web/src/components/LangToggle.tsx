import type { Lang } from '../i18n'

interface Props {
  lang: Lang
  onChange: (lang: Lang) => void
}

export default function LangToggle({ lang, onChange }: Props) {
  return (
    <button
      onClick={() => onChange(lang === 'zh' ? 'en' : 'zh')}
      className="flex h-8 items-center justify-center rounded-md px-2 text-sm font-medium text-gray-500 transition hover:bg-gray-100 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-100"
      title="Language / 语言"
    >
      {lang === 'zh' ? 'EN' : '中文'}
    </button>
  )
}
