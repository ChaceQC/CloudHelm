# CI 失败自动修复流程

> 来源：[设计书 10 章](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：定义端到端业务流程、参与模块和关键产物。
## 实现检查点

- 入口 API 是否存在。
- Orchestrator 状态迁移是否完整。
- Agent 输出是否结构化保存。
- Tool Gateway 是否记录工具调用和审批。
- 控制台是否能展示实时状态、产物和错误。

## 设计书摘录

### 10.3 CI 失败自动修复流程

```text
1. CI webhook 推送失败事件。
2. Orchestrator 创建 ci_failure_fix 任务。
3. Tester Agent 拉取失败 job 日志。
4. Planner Agent 判断失败类型：
   - 单元测试失败
   - 类型检查失败
   - lint 失败
   - 依赖安装失败
   - 环境配置失败
5. Coder Agent 修改代码或配置。
6. Sandbox 中复现并运行测试。
7. 创建修复 PR。
8. Reviewer Agent 给出审查结论。
9. 人类确认是否合并。
```
