import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import OnboardingWizard from './OnboardingWizard'

vi.mock('../api/client', () => ({
  uploadDocument: vi.fn(),
  seedQuestions: vi.fn(),
  runEvaluation: vi.fn(),
  suggest: vi.fn(),
  applySuggestion: vi.fn(),
}))

import {
  uploadDocument,
  seedQuestions,
  runEvaluation,
  suggest,
  applySuggestion,
} from '../api/client'

const t = (k: string) => k

const mockedUpload = vi.mocked(uploadDocument)
const mockedSeed = vi.mocked(seedQuestions)
const mockedEval = vi.mocked(runEvaluation)
const mockedSuggest = vi.mocked(suggest)
const mockedApply = vi.mocked(applySuggestion)

function renderWizard() {
  return render(<OnboardingWizard t={t} onClose={vi.fn()} />)
}

async function uploadToSeed(container: HTMLElement, user: ReturnType<typeof userEvent.setup>) {
  const input = container.querySelector('input[type="file"]') as HTMLInputElement
  const file = new File(['pdf'], 'a.pdf', { type: 'application/pdf' })
  await user.upload(input, file)
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedUpload.mockResolvedValue({ filename: 'a.pdf', chunk_count: 10 })
  mockedSeed.mockResolvedValue({
    questions: [
      { question: '问题1', expected_answer: '答1' },
      { question: '问题2', expected_answer: '答2' },
    ],
  })
  mockedEval.mockResolvedValue({
    results: [
      {
        question: '问题1',
        expected_answer: '答1',
        answer: '答案1',
        contexts: ['ctx1'],
        faithfulness: 0.8,
        context_precision: 0.7,
      },
      {
        question: '问题2',
        expected_answer: '答2',
        answer: '答案2',
        contexts: ['ctx2'],
        faithfulness: 0.6,
        context_precision: 0.5,
      },
    ],
  })
})

describe('OnboardingWizard', () => {
  it('初始显示上传步骤', () => {
    renderWizard()
    expect(screen.getByText('evalUploadTitle')).toBeInTheDocument()
  })

  it('上传后进入种子问题步骤', async () => {
    const user = userEvent.setup()
    const { container } = renderWizard()
    await uploadToSeed(container, user)

    expect(await screen.findByDisplayValue('问题1')).toBeInTheDocument()
    expect(mockedUpload).toHaveBeenCalled()
    expect(mockedSeed).toHaveBeenCalled()
  })

  it('种子问题可编辑', async () => {
    const user = userEvent.setup()
    const { container } = renderWizard()
    await uploadToSeed(container, user)

    const inputs = await screen.findAllByRole('textbox')
    await user.clear(inputs[0])
    await user.type(inputs[0], '修改后的问题')
    expect(inputs[0]).toHaveValue('修改后的问题')
  })

  it('种子问题可删除', async () => {
    const user = userEvent.setup()
    const { container } = renderWizard()
    await uploadToSeed(container, user)

    await screen.findByDisplayValue('问题1')
    const deleteButtons = screen.getAllByTitle('evalDelete')
    await user.click(deleteButtons[0])

    expect(screen.queryByDisplayValue('问题1')).not.toBeInTheDocument()
    expect(screen.getByDisplayValue('问题2')).toBeInTheDocument()
  })

  it('开始评分 → 展示答案', async () => {
    const user = userEvent.setup()
    const { container } = renderWizard()
    await uploadToSeed(container, user)
    await screen.findByDisplayValue('问题1')

    await user.click(screen.getByRole('button', { name: 'evalStartRating' }))

    expect(await screen.findByText('答案1')).toBeInTheDocument()
    expect(mockedEval).toHaveBeenCalled()
  })

  it('评分后生成建议', async () => {
    mockedSuggest.mockResolvedValue({
      suggestion: {
        param: 'top_k',
        current: 5,
        recommended: 8,
        reason: '更高',
        confidence: 0.6,
        category: 'weak',
      },
    })
    const user = userEvent.setup()
    const { container } = renderWizard()
    await uploadToSeed(container, user)
    await screen.findByDisplayValue('问题1')
    await user.click(screen.getByRole('button', { name: 'evalStartRating' }))
    await screen.findByText('答案1')

    // 评分
    await user.click(screen.getAllByRole('button', { name: /evalUp/ })[0])
    // 生成建议
    await user.click(screen.getByRole('button', { name: 'evalGenerateSuggestion' }))

    expect(await screen.findByText('evalSuggestionTitle')).toBeInTheDocument()
    expect(screen.getByText('top_k 5 → 8')).toBeInTheDocument()
  })

  it('确认采纳 → 完成', async () => {
    mockedSuggest.mockResolvedValue({
      suggestion: {
        param: 'top_k',
        current: 5,
        recommended: 8,
        reason: '更高',
        confidence: 0.6,
        category: 'weak',
      },
    })
    mockedApply.mockResolvedValue({ top_k: 8 })
    const user = userEvent.setup()
    const { container } = renderWizard()
    await uploadToSeed(container, user)
    await screen.findByDisplayValue('问题1')
    await user.click(screen.getByRole('button', { name: 'evalStartRating' }))
    await screen.findByText('答案1')
    await user.click(screen.getAllByRole('button', { name: /evalUp/ })[0])
    await user.click(screen.getByRole('button', { name: 'evalGenerateSuggestion' }))
    await screen.findByText('evalSuggestionTitle')

    await user.click(screen.getByRole('button', { name: 'evalApply' }))

    expect(await screen.findByText('evalDoneTitle')).toBeInTheDocument()
    expect(mockedApply).toHaveBeenCalled()
  })

  it('无建议时显示提示', async () => {
    mockedSuggest.mockResolvedValue({ suggestion: null })
    const user = userEvent.setup()
    const { container } = renderWizard()
    await uploadToSeed(container, user)
    await screen.findByDisplayValue('问题1')
    await user.click(screen.getByRole('button', { name: 'evalStartRating' }))
    await screen.findByText('答案1')
    await user.click(screen.getAllByRole('button', { name: /evalUp/ })[0])
    await user.click(screen.getByRole('button', { name: 'evalGenerateSuggestion' }))

    expect(await screen.findByText('evalNoSuggestion')).toBeInTheDocument()
  })
})
