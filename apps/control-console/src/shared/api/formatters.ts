import { ApiError } from './apiClient'
import type { JsonValue } from '../types/api'

/**
 * 转换错误为面向控制台用户的短文本。
 *
 * 保留 trace_id 便于开发者把前端错误和后端日志关联起来。
 */
export function formatApiError(error: unknown): string {
  if (error instanceof ApiError) {
    const trace = error.traceId === null ? '' : `（trace_id: ${error.traceId}）`
    return `${error.message}${trace}`
  }

  if (error instanceof Error) {
    return error.message
  }

  return '未知错误'
}

/**
 * 安全格式化 JSON 字段。
 *
 * OpenAPI、DB schema 和事件 payload 可能是对象或数组；统一缩进展示，
 * 避免组件重复处理 `null` 和序列化异常。
 */
export function formatJson(value: JsonValue | JsonValue[] | Record<string, JsonValue> | null): string {
  if (value === null) {
    return 'null'
  }

  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

export function formatDateTime(value: string | null): string {
  if (value === null || value.trim() === '') {
    return '未记录'
  }

  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}
