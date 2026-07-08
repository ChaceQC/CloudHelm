/**
 * `/health` 响应结构。
 *
 * 字段与 `packages/shared-contracts/openapi/cloudhelm.openapi.yaml`
 * 保持一致，后续可由 OpenAPI 生成类型替换手写类型。
 */
export interface HealthResponse {
  service: string
  status: 'ok'
  version: string
  environment: string
  timestamp: string
}
