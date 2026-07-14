# M1-M6 成果核验报告

> 核验日期：2026-07-14 至 2026-07-15
> 核验分支：`dev`
> 核验基线：`a89b566`
> 核验修复版：项目 / Platform API / Tool Gateway / Control Console `0.5.1`，
> Agent Runtime `0.4.1`，Orchestrator `0.4.0`。
> 状态：M1-M6 在本文声明的同步本地闭环边界内核验通过；hard crash 自动恢复
> 和真实 subagent 执行调度作为明确剩余边界保留。修复代码、共享契约、控制台
> 与文档已按子系统提交并同步 `origin/dev`；本轮不创建 `v0.5.1` tag。

## 1. 核验目标

核验 M1-M6 是否同时满足：

- `AGENTS.md` 的 UTF-8、分层、真实实现、测试、文档同步和 Git 门禁。
- 用户新增的 Codex CLI 式 Agent thread、subagent 委派和摘要回传约束。
- `docs/15-detailed-design/00-mvp-scope-and-cutline.md` 的阶段边界。
- `docs/15-detailed-design/07-testing-acceptance-matrix.md` 的黑盒、白盒和证据要求。
- FastAPI OpenAPI、JSON Schema、数据库迁移、Agent/Tool 契约与控制台行为。
- M6 对 sample repo 的真实 diff、pytest/JUnit、Review、Bandit/pip-audit、
  branch、commit、format patch 和本地等价 PR record。

## 2. 当前交付边界

M1-M6 当前闭环止于本地等价 PR record：

```text
Project / Task
  -> Requirement / Architect / Planner
  -> 设计与计划审批
  -> Scaffold / Coder / Tester / Reviewer / Security
  -> branch / commit / format patch / local PR record
```

当前 Orchestrator 为显式 Python 状态机；M6 Sandbox Tool 使用 allowlist Task
workspace 与受控 `subprocess`。LangGraph、独立 Docker sandbox、真实远端
PR/CI、Release / Deploy、Remote Agent、监控告警和 SRE 属于 M7-M8，不在本次
“已交付”结论内。

Codex CLI 式协作首先作为仓库开发规则落实。产品侧 M1-M6 只交付
root/child conversation 持久化、父运行绑定、深度/active 数量门禁、父子角色
工具权限交集、摘要回传和 Task 取消级联等内部原语；没有真实 child AgentRun /
provider 调度、wait-all barrier、通用 steer/queue、conversation list/detail
API 或独立 thread UI。

## 3. 发现与处理

|级别|问题|影响|本轮处理状态|
|---|---|---|---|
|P0|Platform API pytest 默认重建开发库 `public` schema|运行测试会破坏开发数据，并行测试互相干扰|已改为会话级随机 `cloudhelm_test_<pid>_<uuid>`；显式测试库需独立 `test` 段和 `CLOUDHELM_TEST_ALLOW_SCHEMA_RESET=true`，并行与迁移回归通过|
|P1|Task cancel 写入未定义业务阶段 `Cancelled`|业务阶段契约漂移，取消前上下文丢失|已改为只更新 `status=cancelled` 并保留 `current_phase`，全量回归通过|
|P1|`local_structured` 对无关领域生成固定 CloudHelm 设计/计划|错误产物可能进入后续执行|已限定受控 auth/profile 与 CloudHelm 核验 recipe；其他领域返回 `unsupported_local_recipe`|
|P1|Requirement/Architect/Planner 风险可被后续角色降级|高风险设计或计划可能绕过审批|已按 Task、输入与输出最高风险传播；Requirement 新识别风险写回 Task，并补跨角色审批测试|
|P1|控制台 Task A→B 切换时旧请求/SSE/timer 可覆盖新详情|用户可能审批错误 Task|已增加最新 Task 请求门禁、立即隐藏旧详情和异步切换测试|
|P1|M4 start/run-next 缺少阶段前置条件|重复点击可能顺带推进下一角色或重复产物|已增加 Task 行锁与可选 `expected_phase`；客户端应始终发送当前阶段，阶段漂移返回稳定 `409`|
|P1|Tester 以整批 pytest 结果替代逐 AC 证据|未覆盖 AC 可能被误标通过|recipe 升级为 `1.1`，以稳定 `testcase_names` 逐项读取 JUnit；缺失/跳过为 `not_covered`|
|P1|Reviewer 只确认 `git.diff` 调用成功|空、截断或错误路径 patch 仍可能批准|已增加非空/未截断安全投影、路径集合、文件头、auth/profile 必需路径与 marker 门禁；Reviewer 不读取 raw secrets|
|P1|Artifact 脱敏改写 patch 原文|`implementation.diff` / format patch 可能失去 Git 可应用性|改为文件层保存原始 UTF-8 bytes/SHA，raw 只在同进程用于 Artifact/Git 门禁，ToolCall/API preview 单独脱敏；真实 E2E 两类 patch 的 `git apply --check` 均通过|
|P1|Git Tool 在内部输出已截断后再比较长度|`patch_truncated` 可能误报 `false`，下游把不完整 patch 当成完整证据|已改为先保留完整 Git 输出，再按调用上限截断并计算标记；新增大 patch 回归|
|P2|数据库错误和 ToolCall result summary 可能回显敏感内容|HTTP、审计或控制台泄露内部信息|数据库错误 detail 置空，ToolCall 结果入库前脱敏|
|P2|Timeline 仅按 conversation turn 排序|失败/取消 AgentRun 可能被排到错误位置|改为 `started_at` 优先、同时间再按 turn/ID 稳定排序|
|P2|subagent 默认允许两层递归、未验证第 7 个 active child、父子角色工具权限未取交集且摘要无长度/脱敏门禁|可能递归 fan-out、借 child 扩大工具权限、污染父线程或回传敏感原始日志|参考 Codex CLI 改为默认 `max_depth=1`、`max_threads=6`；新增第 7 个 child 拒绝；Tool Gateway 沿 lineage 强制父子 allowlist 交集并审计；摘要非空、脱敏且最多 4000 字符|
|P1|subagent 只在创建时检查上下文，终态 child、active 后代和策略漂移 replay 缺少执行期门禁|child 可能在父级失效后继续调用工具、提前完成或用旧幂等结果绕过新策略|每次 Tool Gateway 调用重验 active lineage；终态 child、active AgentRun/后代、Task paused/terminal、legacy role、跨 Task root 均拒绝；replay 比较 execution-policy fingerprint，拒绝写 `ToolCallRejected`，晚到结果保留 scope/fingerprint|
|P1|Task、Approval 与 conversation 写操作缺少统一锁顺序|并发 pause/cancel、cancel/spawn 或 design review/spawn 可能死锁、覆盖终态或遗留 active child|统一为 `Task -> AgentRun -> ToolCall -> Conversation -> Approval`；所有相关写操作先锁 Task，并补三类并发回归|
|P2|控制台未声明 favicon|浏览器每次加载产生 404 console error，影响无错误门禁|新增 `public/favicon.svg` 和 HTML icon 声明；真实浏览器复测为 0 error / 0 warning|
|边界|M4 Provider 调用期间持有 Task 行锁|并发 worker 下 pause/cancel 可能等待较久|当前单用户 MVP 以正确性优先；后续改为短事务 claim + lease|
|边界|进程 hard crash 后 active 记录没有 lease/stale reclaim|`pending/running` AgentRun/ToolCall 可能长期停留|M6 明确记录为未覆盖边界；当前只承诺进入应用错误处理后的恢复，不写成自动恢复|

## 4. 文档与契约漂移

本轮已校正：

- Project/Task 创建响应不包裹 `data`，状态码均为 `201`。
- Task 创建 DTO 不存在 `constraints`、`auto_start`；创建后需单独调用
  `/start`。
- M4 `expected_phase`、Task 行锁和阶段漂移 `409`。
- Platform API 测试数据库随机隔离及显式破坏性确认。
- Tester `testcase_names → JUnit → 单条 AC` 映射。
- Reviewer 完整安全投影 diff、changed files、文件头和 auth/profile 领域门禁；
  lossless raw bytes/SHA 仅进入 Artifact/Git 最终门禁。
- M5/M6 为显式状态机 + 受控 subprocess，不把 LangGraph/Docker sandbox
  写成当前交付。
- M7-M8 远端部署、监控与 SRE 接口/测试标记为规划内容。
- hard crash 自动恢复不在 M6 完成宣称内。
- Agent 协作参考 Codex CLI：主/root thread 负责目标、决策和汇总；显式 child
  承担有界任务；read-heavy 可并行，写共享状态的任务串行或隔离；child 只回传
  最终摘要。当前产品只实现内部 conversation/权限/生命周期原语；真实 child
  执行、wait-all、通用 steer/queue、thread API/UI 和 workspace 调度均不写成
  M1-M6 已交付。

## 5. 全量验证记录

|范围|最终结果|
|---|---|
|Orchestrator|`7 passed`|
|Agent Runtime|`61 passed, 1 skipped`；外部 provider 专项在未注入临时配置时显式 skip|
|Tool Gateway|`45 passed, 1 skipped`；Windows symlink 权限条件时显式 skip|
|Platform API|`130 passed, 1 skipped`；锁顺序与 subagent 权限/生命周期定向回归 `16 passed`；OpenAPI `version=0.5.1`、`paths=41`、`schemas=56`、`operations=47` 与共享 YAML 精确一致，`26` 个 JSON Schema 验证通过，并覆盖迁移/约束、M4/M6 API 与 E2E|
|控制台|`17 passed`；TypeScript/Vite production build 通过|
|控制台浏览器|Browser 运行时未注入后按记录切换 Playwright Edge；真实 API 页面、Task B→A 切换、Requirement/Timeline/Event Log 数据一致；桌面与 `390x844` 视口通过，console 0 error / 0 warning|
|测试数据库隔离|两个 pytest 进程并行使用不同随机数据库，结束后未残留会话数据库|
|开发库保护|数据计数保持 `projects=1 / tasks=1 / agent_runs=3 / tool_calls=0 / artifacts=0 / pull_request_records=0 / event_logs=23`；无 `cloudhelm_test_*` 残留库|
|Alembic|隔离库执行 `upgrade head -> check -> downgrade base -> upgrade head` 全通过；check 为 `No new upgrade operations detected`，最终 revision `20260714_0006`、13 张业务/版本表|
|sample repo|pytest `2 passed`；Bandit 0 finding；pip-audit 无已知漏洞，本地项目包因不在 PyPI 按预期跳过|
|真实 M4-M6 E2E|完整 auth/profile 闭环通过；`implementation.diff` 与 format patch 均通过 `git apply --check`|
|静态门禁|588 个文本文件 UTF-8 解码错误 0、BOM 0；405 个 Markdown 相对链接失效 0；84 个本轮生产源码均不超过 300 行；生产源码、配置和文档高置信凭据命中 0；`git diff --check` 通过|

## 6. 已完成的收口验证

1. 四个 Python 模块完成 `uv lock --check` 与全量 pytest。
2. Platform API 完成 Alembic upgrade/downgrade/check。
3. FastAPI `app.openapi()` 与共享 YAML 精确一致，全部 JSON Schema 验证通过。
4. sample repo pytest、Bandit、pip-audit 通过。
5. 控制台 Node test 与 production build 通过。
6. 新 M4-M6 E2E 的 `implementation.diff` 和 format patch 均验证可应用。
7. 真实浏览器完成页面身份、非空、框架 overlay、console、Task 切换、Timeline
   和移动视口检查；favicon 404 修复后复测通过。
8. 文档相对链接、UTF-8/BOM、敏感信息、生产文件体量与 `git diff --check`
   已在最终 Git 门禁中再次执行并通过。

## 7. 当前结论

M1-M6 原完成标记中存在会破坏开发数据库、固定领域输出、风险降级、旧 Task
详情竞争、Reviewer/Tester 证据不足及 patch 被脱敏破坏等实质问题。本轮已完成
修复，并通过模块全量测试、契约/迁移检查、控制台构建、sample 安全扫描和真实
M4-M6 E2E；subagent 执行期权限、幂等 replay 和全局事务锁顺序也已完成并发
回归。基于本文第 2 节边界，M1-M6 可标记为核验通过。

进程 hard crash 的 lease/stale recovery 是明确剩余边界。该项不阻断 M6
“同步本地闭环”的准确验收，但必须保留为后续 worker/recovery 设计输入，且不得
在答辩材料中描述为已自动恢复。

M4 为保证单步正确性，当前在 Provider 调用期间持有 Task 行锁；这是单用户 MVP
的已知并发取舍，不影响本轮验收。进入多 worker 阶段时应改为短事务 claim +
lease，避免 pause/cancel 长时间等待。

同理，Codex CLI 式 subagent 当前验收对象是内部会话与权限原语，不是完整多
Agent 调度器。接入真实 child provider 执行前，必须补齐 input scope、wait
policy、evidence refs、child AgentRun、超时/汇总屏障和 thread 可视化验收。
