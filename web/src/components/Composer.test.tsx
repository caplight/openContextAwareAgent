import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Composer from './Composer'

const t = (k: string) => k

describe('Composer', () => {
  it('空输入禁用发送', () => {
    render(<Composer onSend={vi.fn()} onStop={vi.fn()} streaming={false} t={t} />)
    expect(screen.getByRole('button', { name: 'send' })).toBeDisabled()
  })

  it('输入后点击发送', async () => {
    const user = userEvent.setup()
    const onSend = vi.fn()
    render(<Composer onSend={onSend} onStop={vi.fn()} streaming={false} t={t} />)

    await user.type(screen.getByRole('textbox'), 'hello')
    await user.click(screen.getByRole('button', { name: 'send' }))

    expect(onSend).toHaveBeenCalledWith('hello')
  })

  it('Enter 发送（不 shift）', async () => {
    const user = userEvent.setup()
    const onSend = vi.fn()
    render(<Composer onSend={onSend} onStop={vi.fn()} streaming={false} t={t} />)

    await user.type(screen.getByRole('textbox'), 'hello{Enter}')

    expect(onSend).toHaveBeenCalledWith('hello')
  })

  it('Shift+Enter 不发送（换行）', async () => {
    const user = userEvent.setup()
    const onSend = vi.fn()
    render(<Composer onSend={onSend} onStop={vi.fn()} streaming={false} t={t} />)

    await user.type(screen.getByRole('textbox'), 'a{Shift>}{Enter}{/Shift}b')

    expect(onSend).not.toHaveBeenCalled()
  })

  it('streaming 时显示停止按钮而非发送', () => {
    const onStop = vi.fn()
    render(<Composer onSend={vi.fn()} onStop={onStop} streaming={true} t={t} />)

    expect(screen.getByRole('button', { name: 'stop' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'send' })).not.toBeInTheDocument()
  })

  it('点击停止触发 onStop', async () => {
    const user = userEvent.setup()
    const onStop = vi.fn()
    render(<Composer onSend={vi.fn()} onStop={onStop} streaming={true} t={t} />)

    await user.click(screen.getByRole('button', { name: 'stop' }))
    expect(onStop).toHaveBeenCalled()
  })
})
