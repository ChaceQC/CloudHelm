/**
 * 执行异步决策，并仅在成功后通知上层刷新任务列表。
 *
 * 需求、设计和审批决策会同时修改 Task 状态或阶段。详情刷新不能替代左侧
 * 任务列表刷新；同时，失败请求不得触发一次误导性的状态回读。
 */
export async function refreshAfterSuccess<TArgs extends unknown[], TResult>(
  operation: (...args: TArgs) => Promise<TResult>,
  onChanged: () => void,
  ...args: TArgs
): Promise<TResult> {
  const result = await operation(...args)
  onChanged()
  return result
}
