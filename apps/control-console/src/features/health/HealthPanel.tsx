import { useCallback, useEffect, useState } from 'react'
import { getHealth } from './healthApi'
import type { HealthResponse } from '../../shared/types/health'

type HealthState =
  | { status: 'loading' }
  | { status: 'ready'; data: HealthResponse }
  | { status: 'error'; message: string }

/**
 * 平台 API 紧凑健康状态。
 *
 * 组件只展示 `/health` 的真实返回或真实错误，不使用模拟数据。
 * 重新检查动作复用同一个回调，避免交互逻辑分散在页面层。
 */
export function HealthPanel() {
  const [state, setState] = useState<HealthState>({ status: 'loading' })

  const refresh = useCallback(async () => {
    setState({ status: 'loading' })
    try {
      const data = await getHealth()
      setState({ status: 'ready', data })
    } catch (error) {
      const message = error instanceof Error ? error.message : '未知错误'
      setState({ status: 'error', message })
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  return (
    <section className={`system-status ${state.status}`} aria-label="Platform API 状态">
      <span className="status-dot" aria-hidden="true" />
      {state.status === 'loading' ? <span>API 检查中</span> : null}
      {state.status === 'error' ? <span title={state.message}>API 离线</span> : null}
      {state.status === 'ready' ? (
        <span title={`${state.data.service} · ${state.data.environment} · ${state.data.timestamp}`}>
          API {state.data.status} · v{state.data.version}
        </span>
      ) : null}
      <button type="button" className="icon-button" onClick={refresh} aria-label="重新检查 Platform API">
        ↻
      </button>
    </section>
  )
}
