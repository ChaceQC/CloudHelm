const apiBaseUrl = import.meta.env.VITE_CLOUDHELM_API_BASE_URL as string | undefined

/**
 * 拼接 API URL。
 *
 * API 地址必须通过 Vite 环境变量提供，避免把本机端口、域名或后续
 * 演示环境地址硬编码到业务组件中。
 */
function buildApiUrl(path: string): string {
  if (apiBaseUrl === undefined || apiBaseUrl.trim() === '') {
    throw new Error('缺少 VITE_CLOUDHELM_API_BASE_URL，无法请求平台 API。')
  }

  const normalizedBaseUrl = apiBaseUrl.replace(/\/+$/, '')
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  return `${normalizedBaseUrl}${normalizedPath}`
}

/**
 * 执行 GET 请求并解析 JSON 响应。
 *
 * 当前 M1 不引入额外 HTTP client，使用浏览器原生 fetch 即可满足
 * `/health` 验证；后续接入鉴权、trace_id 和错误结构后再扩展本封装。
 */
export async function apiGet<TResponse>(path: string): Promise<TResponse> {
  const response = await fetch(buildApiUrl(path), {
    method: 'GET',
    headers: {
      Accept: 'application/json',
    },
  })

  if (!response.ok) {
    throw new Error(`平台 API 请求失败：HTTP ${response.status}`)
  }

  return (await response.json()) as TResponse
}
