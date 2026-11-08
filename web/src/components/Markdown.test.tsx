import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import Markdown from './Markdown'

describe('Markdown', () => {
  it('渲染 GFM 表格', () => {
    render(<Markdown>{'| a | b |\n|---|---|\n| 1 | 2 |'}</Markdown>)
    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(screen.getByText('a')).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()
  })

  it('渲染代码块', () => {
    const { container } = render(<Markdown>{'```python\nprint("hi")\n```'}</Markdown>)
    // 高亮会把代码拆成多个 span，检查 code 元素文本
    const code = container.querySelector('code')
    expect(code).toBeInTheDocument()
    expect(code!.textContent).toContain('print')
  })

  it('渲染无序列表', () => {
    render(<Markdown>{'- item1\n- item2'}</Markdown>)
    expect(screen.getByText('item1')).toBeInTheDocument()
    expect(screen.getByText('item2')).toBeInTheDocument()
  })

  it('渲染链接', () => {
    render(<Markdown>{'[docs](https://k8s.io)'}</Markdown>)
    expect(screen.getByRole('link')).toHaveAttribute('href', 'https://k8s.io')
  })

  it('渲染粗体', () => {
    render(<Markdown>{'**bold**'}</Markdown>)
    expect(screen.getByText('bold')).toBeInTheDocument()
  })
})
