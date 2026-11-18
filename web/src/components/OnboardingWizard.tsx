import { useMemo, useState } from 'react'
import {
  applySuggestion,
  runEvaluation,
  seedQuestions,
  suggest,
  uploadDocument,
} from '../api/client'
import type {
  EvaluationResult,
  Rating,
  RatingValue,
  SeedQuestion,
  Suggestion,
} from '../api/client'

type Step = 'upload' | 'seed' | 'rating' | 'suggest' | 'done'

interface Props {
  t: (key: string) => string
  onClose: () => void
}

/** 置信度（后端 rating.compute_confidence 的前端等价：1 - e^(-n/12)）。 */
function confidence(n: number): number {
  return n <= 0 ? 0 : 1 - Math.exp(-n / 12)
}

const RATING_OPTIONS: { value: RatingValue; icon: string; key: string }[] = [
  { value: 'up', icon: '👍', key: 'evalUp' },
  { value: 'down', icon: '👎', key: 'evalDown' },
  { value: 'copied', icon: '📋', key: 'evalCopied' },
  { value: 'regenerated', icon: '🔄', key: 'evalRegenerated' },
]

const STEPS: Step[] = ['upload', 'seed', 'rating', 'suggest', 'done']
const STEP_KEYS = ['evalStepUpload', 'evalStepSeed', 'evalStepRating', 'evalStepSuggest', 'evalStepDone']

export default function OnboardingWizard({ t, onClose }: Props) {
  const [step, setStep] = useState<Step>('upload')
  const [questions, setQuestions] = useState<SeedQuestion[]>([])
  const [results, setResults] = useState<EvaluationResult[]>([])
  const [ratings, setRatings] = useState<Record<string, RatingValue>>({})
  const [suggestion, setSuggestion] = useState<Suggestion | null>(null)
  const [appliedTopK, setAppliedTopK] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const stepIndex = STEPS.indexOf(step)
  const ratedCount = useMemo(
    () => Object.keys(ratings).filter((q) => ratings[q] !== undefined).length,
    [ratings],
  )
  const conf = confidence(ratedCount)

  async function handleUpload(file: File) {
    setLoading(true)
    setError(null)
    try {
      await uploadDocument(file)
      const { questions: qs } = await seedQuestions()
      setQuestions(qs)
      setStep('seed')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  function updateQuestion(idx: number, text: string) {
    setQuestions((prev) => prev.map((q, i) => (i === idx ? { ...q, question: text } : q)))
  }

  function removeQuestion(idx: number) {
    setQuestions((prev) => prev.filter((_, i) => i !== idx))
  }

  async function handleStartRating() {
    setLoading(true)
    setError(null)
    try {
      const { results: rs } = await runEvaluation(questions)
      setResults(rs)
      setStep('rating')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  function rate(question: string, value: RatingValue) {
    setRatings((prev) => ({ ...prev, [question]: value }))
  }

  async function handleSuggest() {
    setLoading(true)
    setError(null)
    try {
      const ratingList: Rating[] = Object.entries(ratings).map(([question, rating]) => ({
        question,
        rating,
      }))
      const { suggestion: s } = await suggest(questions, ratingList)
      setSuggestion(s)
      setStep('suggest')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  async function handleApply() {
    if (!suggestion) return
    setLoading(true)
    setError(null)
    try {
      const { top_k } = await applySuggestion(suggestion)
      setAppliedTopK(top_k)
      setStep('done')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex h-full flex-col bg-gray-50 dark:bg-gray-900">
      {/* 步骤指示器 */}
      <div className="flex items-center gap-2 border-b border-gray-200 px-4 py-3 dark:border-gray-800">
        {STEPS.map((s, i) => (
          <div key={s} className="flex items-center gap-2">
            <div
              className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold ${
                i < stepIndex
                  ? 'bg-emerald-500 text-white'
                  : i === stepIndex
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-200 text-gray-500 dark:bg-gray-800 dark:text-gray-400'
              }`}
            >
              {i + 1}
            </div>
            <span
              className={`text-sm ${
                i === stepIndex ? 'font-semibold text-gray-900 dark:text-gray-100' : 'text-gray-400'
              }`}
            >
              {t(STEP_KEYS[i])}
            </span>
            {i < STEPS.length - 1 && <span className="text-gray-300 dark:text-gray-700">—</span>}
          </div>
        ))}
        <button
          onClick={onClose}
          className="ml-auto text-sm text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
        >
          ✕
        </button>
      </div>

      {/* 主体 */}
      <div className="flex-1 overflow-y-auto px-6 py-6">
        {error && (
          <div className="mb-4 rounded-md bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300">
            {error}
          </div>
        )}

        {/* Step 1: 上传 */}
        {step === 'upload' && (
          <div className="flex flex-col items-center justify-center gap-6 py-16">
            <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
              {t('evalUploadTitle')}
            </h2>
            <p className="max-w-md text-center text-sm text-gray-500 dark:text-gray-400">
              {t('evalUploadHint')}
            </p>
            <label className="flex cursor-pointer flex-col items-center gap-3 rounded-xl border-2 border-dashed border-gray-300 px-12 py-10 transition hover:border-blue-400 dark:border-gray-700 dark:hover:border-blue-500">
              <span className="text-3xl">📄</span>
              <span className="text-sm font-medium text-gray-600 dark:text-gray-300">
                {t('evalUploadBtn')}
              </span>
              <input
                type="file"
                accept=".pdf,.docx,.md,.txt,.rst"
                className="hidden"
                disabled={loading}
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  if (f) void handleUpload(f)
                }}
              />
            </label>
            {loading && <p className="text-sm text-gray-500">{t('evalLoading')}</p>}
          </div>
        )}

        {/* Step 2: 种子问题 */}
        {step === 'seed' && (
          <div className="flex flex-col gap-4">
            <p className="text-sm text-gray-500 dark:text-gray-400">{t('evalSeedHint')}</p>
            <div className="flex flex-col gap-2">
              {questions.map((q, i) => (
                <div key={i} className="flex items-center gap-2">
                  <input
                    value={q.question}
                    onChange={(e) => updateQuestion(i, e.target.value)}
                    className="flex-1 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-100"
                  />
                  <button
                    onClick={() => removeQuestion(i)}
                    className="text-gray-400 hover:text-red-500"
                    title={t('evalDelete')}
                  >
                    🗑
                  </button>
                </div>
              ))}
            </div>
            <button
              onClick={() => void handleStartRating()}
              disabled={loading || questions.length === 0}
              className="mt-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {t('evalStartRating')}
            </button>
          </div>
        )}

        {/* Step 3: 评分 */}
        {step === 'rating' && (
          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-3">
              <div className="h-2 flex-1 overflow-hidden rounded-full bg-gray-200 dark:bg-gray-800">
                <div
                  className="h-full rounded-full bg-emerald-500 transition-all"
                  style={{ width: `${results.length ? (ratedCount / results.length) * 100 : 0}%` }}
                />
              </div>
              <span className="whitespace-nowrap text-xs text-gray-500">
                {ratedCount}/{results.length} · {Math.round(conf * 100)}%
              </span>
            </div>

            {results.map((r, i) => {
              const active = ratings[r.question]
              return (
                <div
                  key={i}
                  className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-800"
                >
                  <p className="font-medium text-gray-900 dark:text-gray-100">{r.question}</p>
                  <p className="mt-2 whitespace-pre-wrap text-sm text-gray-700 dark:text-gray-300">
                    {r.answer}
                  </p>
                  {r.contexts.length > 0 && (
                    <details className="mt-2 text-xs text-gray-400">
                      <summary>{t('evalSources')} ({r.contexts.length})</summary>
                      <ul className="mt-1 list-disc pl-5 text-gray-500">
                        {r.contexts.map((c, j) => (
                          <li key={j} className="truncate">
                            {c}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                  <div className="mt-3 flex gap-2">
                    {RATING_OPTIONS.map((opt) => (
                      <button
                        key={opt.value}
                        onClick={() => rate(r.question, opt.value)}
                        className={`flex items-center gap-1 rounded-md border px-3 py-1.5 text-sm transition ${
                          active === opt.value
                            ? 'border-blue-500 bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300'
                            : 'border-gray-300 text-gray-600 hover:border-gray-400 dark:border-gray-700 dark:text-gray-300'
                        }`}
                      >
                        <span>{opt.icon}</span>
                        <span>{t(opt.key)}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )
            })}

            <button
              onClick={() => void handleSuggest()}
              disabled={loading || ratedCount === 0}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {t('evalGenerateSuggestion')}
            </button>
          </div>
        )}

        {/* Step 4: 建议 */}
        {step === 'suggest' && (
          <div className="flex flex-col items-center justify-center gap-5 py-12">
            {suggestion ? (
              <>
                <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
                  {t('evalSuggestionTitle')}
                </h2>
                <div className="rounded-lg border border-gray-200 bg-white p-6 text-center dark:border-gray-800 dark:bg-gray-800">
                  <p className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                    top_k {suggestion.current} → {suggestion.recommended}
                  </p>
                  <p className="mt-2 text-sm text-gray-600 dark:text-gray-300">{suggestion.reason}</p>
                  <div className="mt-4">
                    <div className="h-2 overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700">
                      <div
                        className="h-full rounded-full bg-emerald-500"
                        style={{ width: `${Math.round(suggestion.confidence * 100)}%` }}
                      />
                    </div>
                    <p className="mt-1 text-xs text-gray-500">
                      {t('evalConfidence')}: {Math.round(suggestion.confidence * 100)}%
                    </p>
                  </div>
                </div>
                <div className="flex gap-3">
                  <button
                    onClick={() => void handleApply()}
                    disabled={loading}
                    className="rounded-md bg-emerald-600 px-5 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
                  >
                    {t('evalApply')}
                  </button>
                  <button
                    onClick={onClose}
                    className="rounded-md border border-gray-300 px-5 py-2 text-sm text-gray-600 hover:bg-gray-100 dark:border-gray-700 dark:text-gray-300"
                  >
                    {t('evalSkip')}
                  </button>
                </div>
              </>
            ) : (
              <>
                <p className="text-gray-600 dark:text-gray-300">{t('evalNoSuggestion')}</p>
                <button
                  onClick={onClose}
                  className="rounded-md border border-gray-300 px-5 py-2 text-sm text-gray-600 hover:bg-gray-100 dark:border-gray-700 dark:text-gray-300"
                >
                  {t('evalDone')}
                </button>
              </>
            )}
          </div>
        )}

        {/* Step 5: 完成 */}
        {step === 'done' && (
          <div className="flex flex-col items-center justify-center gap-5 py-16">
            <span className="text-5xl">🎉</span>
            <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
              {t('evalDoneTitle')}
            </h2>
            <p className="text-sm text-gray-600 dark:text-gray-300">
              {t('evalDoneMsg')} top_k = {appliedTopK}
            </p>
            <button
              onClick={onClose}
              className="rounded-md bg-blue-600 px-5 py-2 text-sm font-medium text-white hover:bg-blue-700"
            >
              {t('evalDone')}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
