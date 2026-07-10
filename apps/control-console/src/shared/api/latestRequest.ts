/**
 * 只允许最后一次异步请求提交状态。
 *
 * React hook 在 Project/Task 快速切换时可能同时存在多个 fetch；使用递增
 * token 可以忽略先发后到的旧响应，避免跨项目数据显示串线。
 */
export class LatestRequestGate {
  private sequence = 0

  begin(): number {
    this.sequence += 1
    return this.sequence
  }

  isCurrent(token: number): boolean {
    return token === this.sequence
  }

  invalidate(): void {
    this.sequence += 1
  }
}
