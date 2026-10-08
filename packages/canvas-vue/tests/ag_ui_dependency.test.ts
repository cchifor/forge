import { HttpAgent } from '@ag-ui/client'
import { EventType } from '@ag-ui/core'
import { expect, it, vi } from 'vitest'

it('consumes a complete SSE response with the installed AG-UI client and core', async () => {
  const threadId = 'compatibility-thread'
  const runId = 'compatibility-run'
  const messageId = 'assistant-message'
  const events = [
    { type: EventType.RUN_STARTED, threadId, runId },
    { type: EventType.TEXT_MESSAGE_START, messageId, role: 'assistant' },
    { type: EventType.TEXT_MESSAGE_CONTENT, messageId, delta: 'Hello ' },
    { type: EventType.TEXT_MESSAGE_CONTENT, messageId, delta: 'world' },
    { type: EventType.TEXT_MESSAGE_END, messageId },
    { type: EventType.RUN_FINISHED, threadId, runId },
  ]
  // Only the network boundary is replaced; the dependency's SSE decoder,
  // event validation, subscriber dispatch, and message reducer all run.
  const fetchResponse = vi.fn(async (_url: string, _init: RequestInit) =>
    new Response(events.map(event => `data: ${JSON.stringify(event)}\n\n`).join(''), {
      headers: { 'content-type': 'text/event-stream' },
    }),
  )
  const agent = new HttpAgent({
    url: 'https://example.test/agent',
    threadId,
    initialMessages: [{ id: 'user-message', role: 'user', content: 'Say hello' }],
    fetch: fetchResponse,
  })
  const deltas: string[] = []
  const onFinished = vi.fn()

  await agent.runAgent({ runId }, {
    onTextMessageContentEvent: ({ event }) => { deltas.push(event.delta) },
    onRunFinishedEvent: onFinished,
  })

  expect(fetchResponse).toHaveBeenCalledOnce()
  const [url, request] = fetchResponse.mock.calls[0]!
  expect(url).toBe('https://example.test/agent')
  expect(request.method).toBe('POST')
  expect(JSON.parse(request.body as string)).toMatchObject({
    threadId,
    runId,
    messages: [{ id: 'user-message', role: 'user', content: 'Say hello' }],
  })
  expect(deltas).toEqual(['Hello ', 'world'])
  expect(agent.messages).toEqual([
    { id: 'user-message', role: 'user', content: 'Say hello' },
    { id: messageId, role: 'assistant', content: 'Hello world' },
  ])
  expect(onFinished).toHaveBeenCalledOnce()
  expect(onFinished).toHaveBeenCalledWith(expect.objectContaining({ outcome: 'success' }))
})
