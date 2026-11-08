import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { streamChat } from './client'
import type { ChatEvent } from './client'

function sseBody(chunks: string[]) {
  // 用 ReadableStream 模拟 SSE 流，支持分块到达
  const encoder = new TextEncoder()
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c))
      controller.close()
    },
  })
}

function mockFetch(body: ReadableStream<Uint8Array>) {
  return vi.fn().mockResolvedValue({
    ok: true,
    body,
  } as unknown as Response)
}

describe('streamChat (SSE 客户端)', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('解析完整 SSE 事件序列', async () => {
    const events: ChatEvent[] = []
    vi.stubGlobal(
      'fetch',
      mockFetch(
        sseBody([
          'data: {"type":"meta","session_id":"s","model":"m","run_id":"r"}\n\n',
          'data: {"type":"text_delta","delta":"hi"}\n\n',
          'data: {"type":"done","answer":"hi"}\n\n',
        ]),
      ),
    )

    await streamChat('q', null, (e) => events.push(e))

    expect(events).toEqual([
      { type: 'meta', session_id: 's', model: 'm', run_id: 'r' },
      { type: 'text_delta', delta: 'hi' },
      { type: 'done', answer: 'hi' },
    ])
  })

  it('事件分块到达时正确重组', async () => {
    const events: ChatEvent[] = []
    // 一个事件被拆成多个 chunk
    vi.stubGlobal(
      'fetch',
      mockFetch(
        sseBody([
          'data: {"type":"reasoning_',
          'delta","delta":"think',
          'ing"}\n\ndata: {"type":"reasoning_end"}\n\n',
        ]),
      ),
    )

    await streamChat('q', null, (e) => events.push(e))

    expect(events).toEqual([
      { type: 'reasoning_delta', delta: 'thinking' },
      { type: 'reasoning_end' },
    ])
  })

  it('非 ok 响应抛错', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 500 } as unknown as Response),
    )
    await expect(streamChat('q', null, () => {})).rejects.toThrow(/500/)
  })

  it('传递 session_id 到请求体', async () => {
    const fetchMock = mockFetch(sseBody(['data: {"type":"done"}\n\n']))
    vi.stubGlobal('fetch', fetchMock)

    await streamChat('q', 'session-123', () => {})

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/chat')
    expect(JSON.parse(init.body)).toEqual({ message: 'q', session_id: 'session-123' })
  })
})
