interface EventStreamSource {
  onopen: (() => void) | null
  onerror: (() => void) | null
  addEventListener: (eventType: string, listener: (message: { data: string }) => void) => void
  close: () => void
}

interface ReconnectingEventStreamOptions<TEvent extends { id: string }> {
  url: string
  eventTypes: readonly string[]
  parseEvent: (message: { data: string }) => TEvent | null
  onEvent: (event: TEvent) => void
  onStatus: (status: 'connecting' | 'open' | 'closed' | 'error') => void
  createSource: (url: string) => EventStreamSource
  retryDelayMs?: number
}

/**
 * 创建带退避重连和 event id 去重的 SSE 客户端。
 *
 * 当前 Platform API 每次只回放已有事件后关闭连接；客户端重连时会再次收到
 * 历史事件，因此必须去重，且 cleanup 必须同时关闭连接与重连定时器。
 */
export function createReconnectingEventStream<TEvent extends { id: string }>(
  options: ReconnectingEventStreamOptions<TEvent>,
): () => void {
  const seenEventIds = new Set<string>()
  const retryDelayMs = options.retryDelayMs ?? 2000
  let stopped = false
  let source: EventStreamSource | null = null
  let retryTimer: ReturnType<typeof setTimeout> | null = null

  const connect = () => {
    if (stopped) {
      return
    }
    retryTimer = null
    options.onStatus('connecting')
    const currentSource = options.createSource(options.url)
    source = currentSource
    currentSource.onopen = () => {
      if (!stopped && source === currentSource) {
        options.onStatus('open')
      }
    }
    currentSource.onerror = () => {
      if (stopped || source !== currentSource) {
        currentSource.close()
        return
      }
      options.onStatus('error')
      currentSource.close()
      source = null
      options.onStatus('closed')
      if (retryTimer === null) {
        retryTimer = setTimeout(connect, retryDelayMs)
      }
    }
    options.eventTypes.forEach((eventType) => {
      currentSource.addEventListener(eventType, (message) => {
        if (stopped || source !== currentSource) {
          return
        }
        const event = options.parseEvent(message)
        if (event === null || seenEventIds.has(event.id)) {
          return
        }
        seenEventIds.add(event.id)
        options.onEvent(event)
      })
    })
  }

  connect()
  return () => {
    stopped = true
    if (retryTimer !== null) {
      clearTimeout(retryTimer)
      retryTimer = null
    }
    source?.close()
    source = null
    options.onStatus('closed')
  }
}
