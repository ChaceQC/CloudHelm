import assert from 'node:assert/strict'
import test from 'node:test'

import { createReconnectingEventStream } from '../src/shared/api/taskEventStream.ts'

class FakeEventSource {
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  readonly listeners = new Map<string, (message: { data: string }) => void>()
  closed = false

  addEventListener(eventType: string, listener: (message: { data: string }) => void): void {
    this.listeners.set(eventType, listener)
  }

  close(): void {
    this.closed = true
  }

  emit(eventType: string, id: string): void {
    this.listeners.get(eventType)?.({ data: JSON.stringify({ id }) })
  }
}

test('SSE 断开后重连并按 event id 去重', async () => {
  const sources: FakeEventSource[] = []
  const received: string[] = []
  const close = createReconnectingEventStream({
    url: 'http://127.0.0.1/events',
    eventTypes: ['TaskCreated'],
    parseEvent: (message) => JSON.parse(message.data) as { id: string },
    onEvent: (event) => received.push(event.id),
    onStatus: () => undefined,
    createSource: () => {
      const source = new FakeEventSource()
      sources.push(source)
      return source
    },
    retryDelayMs: 1,
  })

  sources[0].emit('TaskCreated', 'event-1')
  sources[0].onerror?.()
  await new Promise((resolve) => setTimeout(resolve, 10))
  assert.equal(sources.length, 2)
  sources[1].emit('TaskCreated', 'event-1')
  sources[1].emit('TaskCreated', 'event-2')
  assert.deepEqual(received, ['event-1', 'event-2'])

  sources[0].onerror?.()
  await new Promise((resolve) => setTimeout(resolve, 10))
  assert.equal(sources.length, 2)
  assert.equal(sources[1].closed, false)

  close()
  sources[1].onerror?.()
  await new Promise((resolve) => setTimeout(resolve, 10))
  assert.equal(sources.length, 2)
  assert.equal(sources[1].closed, true)
})
