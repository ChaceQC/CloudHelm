import { apiGet } from '../../shared/api/apiClient'
import type { HealthResponse } from '../../shared/types/health'

/**
 * 读取平台 API 健康状态。
 *
 * 返回值完全来自后端 `/health`，用于证明 M1 前后端已通过真实接口连接。
 */
export function getHealth(): Promise<HealthResponse> {
  return apiGet<HealthResponse>('/health')
}
