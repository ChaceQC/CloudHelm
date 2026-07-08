import { useCallback, useEffect, useState } from 'react'
import { getHealth } from './healthApi'
import type { HealthResponse } from '../../shared/types/health'

type HealthState =
  | { status: 'loading' }
  | { status: 'ready'; data: HealthResponse }
  | { status: 'error'; message: string }

/**
 * 平台 API 健康检查面板。
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
    <section className="health-card" aria-labelledby="health-title">
      <div className="card-heading">
        <div>
          <p className="eyebrow">Platform API</p>
          <h2 id="health-title">/health 实时状态</h2>
        </div>
        <button type="button" onClick={refresh}>
          重新检查
        </button>
      </div>

      {state.status === 'loading' ? <p className="status-line">正在请求平台 API...</p> : null}

      {state.status === 'error' ? (
        <div className="status-error" role="alert">
          <strong>连接失败</strong>
          <p>{state.message}</p>
          <p className="hint">
            请确认已设置 `VITE_CLOUDHELM_API_BASE_URL`，并已启动
            `modules/platform-api`。
          </p>
        </div>
      ) : null}

      {state.status === 'ready' ? (
        <dl className="health-grid">
          <div>
            <dt>服务</dt>
            <dd>{state.data.service}</dd>
          </div>
          <div>
            <dt>状态</dt>
            <dd>{state.data.status}</dd>
          </div>
          <div>
            <dt>版本</dt>
            <dd>{state.data.version}</dd>
          </div>
          <div>
            <dt>环境</dt>
            <dd>{state.data.environment}</dd>
          </div>
          <div className="wide">
            <dt>服务端时间</dt>
            <dd>{state.data.timestamp}</dd>
          </div>
        </dl>
      ) : null}
    </section>
  )
}
