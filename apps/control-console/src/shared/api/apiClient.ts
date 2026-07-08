import type { ApiErrorResponse, JsonValue } from '../types/api'

const apiBaseUrl = import.meta.env.VITE_CLOUDHELM_API_BASE_URL as string | undefined

type QueryParams = Record<string, string | number | boolean | null | undefined>

interface ApiRequestOptions {
  method?: 'GET' | 'POST'
  body?: unknown
  query?: QueryParams
}

/**
 * 平台 API 错误。
 *
 * 组件层可读取 `code`、`traceId` 与 `detail` 给用户展示稳定错误信息，
 * 而不是只看到浏览器原始 HTTP 错误。
 */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly detail: JsonValue | null
  readonly traceId: string | null

  constructor(status: number, payload: ApiErrorResponse | null, fallbackMessage: string, traceId: string | null) {
    super(payload?.message ?? fallbackMessage)
    this.name = 'ApiError'
    this.status = status
    this.code = payload?.code ?? 'http_error'
    this.detail = payload?.detail ?? null
    this.traceId = payload?.trace_id ?? traceId
  }
}

/**
 * 拼接 API URL。
 *
 * API 地址必须通过 Vite 环境变量提供，避免把本机端口、域名或后续
 * 演示环境地址硬编码到业务组件中。
 */
export function buildApiUrl(path: string, query?: QueryParams): string {
  if (apiBaseUrl === undefined || apiBaseUrl.trim() === '') {
    throw new Error('缺少 VITE_CLOUDHELM_API_BASE_URL，无法请求平台 API。')
  }

  const normalizedBaseUrl = apiBaseUrl.replace(/\/+$/, '')
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  const url = new URL(`${normalizedBaseUrl}${normalizedPath}`)

  Object.entries(query ?? {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value))
    }
  })

  return url.toString()
}

/**
 * 执行平台 API 请求并解析 JSON 响应。
 *
 * 本封装统一处理 base URL、查询参数、JSON 请求体、`X-Trace-Id` 和
 * `code/message/detail/trace_id` 错误结构。M3 不引入额外 HTTP client，
 * 以降低前端依赖和维护成本。
 */
export async function apiRequest<TResponse>(path: string, options: ApiRequestOptions = {}): Promise<TResponse> {
  const response = await fetch(buildApiUrl(path, options.query), {
    method: options.method ?? 'GET',
    headers: {
      Accept: 'application/json',
      ...(options.body === undefined ? {} : { 'Content-Type': 'application/json' }),
    },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })

  if (!response.ok) {
    const traceId = response.headers.get('X-Trace-Id')
    let payload: ApiErrorResponse | null = null

    try {
      payload = (await response.json()) as ApiErrorResponse
    } catch {
      payload = null
    }

    throw new ApiError(response.status, payload, `平台 API 请求失败：HTTP ${response.status}`, traceId)
  }

  return (await response.json()) as TResponse
}

export function apiGet<TResponse>(path: string, query?: QueryParams): Promise<TResponse> {
  return apiRequest<TResponse>(path, { method: 'GET', query })
}

export function apiPost<TResponse>(
  path: string,
  body?: unknown,
  query?: QueryParams,
): Promise<TResponse> {
  return apiRequest<TResponse>(path, { method: 'POST', body: body ?? {}, query })
}
