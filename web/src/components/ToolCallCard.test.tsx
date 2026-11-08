import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ToolCallCard from './ToolCallCard'
import type { ToolCall } from '../api/client'

const t = (k: string) => k

describe('ToolCallCard', () => {
  it('渲染 running 状态（脉冲指示器）', () => {
    const call: ToolCall = { id: '1', name: 'kb_search', args: { query: 'k8s' }, status: 'running' }
    render(<ToolCallCard call={call} t={t} />)
    expect(screen.getByText('kb_search')).toBeInTheDocument()
    expect(screen.getByText('statusRunning')).toBeInTheDocument()
  })

  it('渲染 success 状态 + 耗时', () => {
    const call: ToolCall = {
      id: '1',
      name: 'k8s_get',
      args: {},
      status: 'success',
      durationMs: 123,
      output: 'result',
    }
    render(<ToolCallCard call={call} t={t} />)
    expect(screen.getByText('statusSuccess')).toBeInTheDocument()
    expect(screen.getByText('123ms')).toBeInTheDocument()
  })

  it('渲染 error 状态', () => {
    const call: ToolCall = { id: '1', name: 'web_search', args: {}, status: 'error' }
    render(<ToolCallCard call={call} t={t} />)
    expect(screen.getByText('statusError')).toBeInTheDocument()
  })

  it('图标按工具名映射', () => {
    const { rerender } = render(
      <ToolCallCard call={{ id: '1', name: 'k8s_get', args: {}, status: 'success' }} t={t} />,
    )
    expect(screen.getByText('🖥️')).toBeInTheDocument()

    rerender(
      <ToolCallCard call={{ id: '2', name: 'kb_search', args: {}, status: 'success' }} t={t} />,
    )
    expect(screen.getByText('📚')).toBeInTheDocument()

    rerender(
      <ToolCallCard call={{ id: '3', name: 'web_search', args: {}, status: 'success' }} t={t} />,
    )
    expect(screen.getByText('🌐')).toBeInTheDocument()
  })

  it('入参默认折叠，点击展开', async () => {
    const user = userEvent.setup()
    const call: ToolCall = { id: '1', name: 'k8s_get', args: { kind: 'node' }, status: 'success' }
    render(<ToolCallCard call={call} t={t} />)
    expect(screen.queryByText(/"kind"/)).not.toBeInTheDocument()

    await user.click(screen.getByText(/args/))
    expect(screen.getByText(/"kind"/)).toBeInTheDocument()
  })

  it('输出默认折叠，点击展开', async () => {
    const user = userEvent.setup()
    const call: ToolCall = {
      id: '1',
      name: 'k8s_get',
      args: {},
      status: 'success',
      output: 'NAME\nfake-node-0',
    }
    render(<ToolCallCard call={call} t={t} />)
    expect(screen.queryByText(/fake-node/)).not.toBeInTheDocument()

    await user.click(screen.getByText(/output/))
    expect(screen.getByText(/fake-node/)).toBeInTheDocument()
  })
})
