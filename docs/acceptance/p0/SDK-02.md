# SDK-02 真实模型请求接缝验证卡

> 状态：部分验证；SDK-02 退出条件未满足
>
> 记录日期：2026-10-13（Asia/Shanghai）
>
> 依据：D01 §6、§8；D02 §11、§12.2；D03 §8；D06 §2.2
> 范围：P0.1-02 的模型请求与 SDK 请求边界探测，不代表 CloudHelm 产品 Runtime 已实现。

## 环境、输入与安全上限

- 执行环境：WSL Ubuntu 24.04.4 LTS，仓库映射 /mnt/e/Project/CloudHelm，uv 管理的 Python 3.12.13。
- 组件：PydanticAI 2.55.0、OpenAI SDK 3.29.0、HTTPX 0.28.1、DBOS 3.2.0、SQLAlchemy 2.1.4。
- 协议：当前 Codex 配置中的自定义 provider，Responses API，https://s2a.chacewebsite.cn/v1；配置凭据字段为 experimental_bearer_token。卡片、终端输出和 journal 均不保存凭据或配置正文。
- 探测模型：按本任务明确授权固定为 gpt-6-luna，reasoning 为 max。真实请求前配置中的交互默认模型为 gpt-6.1-sol；门禁拒绝该不匹配配置一次，HTTP 请求数为 0。随后仅覆盖模型为本任务授权值，继续使用当前自定义 provider 的 endpoint、协议和凭据。
- 固定输入：正常结构化响应询问 readiness check 确认事项；validator 场景要求 accepted=true；摘要场景使用脚本内固定的一句部署检查事实；压缩后续接和恢复场景使用模型生成摘要及已提交 SDK 消息历史。原始响应与输入正文不写入 journal，只保留请求摘要。
- 探测数量边界：主会话首轮自行设置 12 次真实 HTTP 探测上限；该数字不是用户设定的金额限额。SDK-02-C2 新增固定 6 次，SDK-02-C3-STREAM 再新增 1 次；当前任务真实出站累计 19 次。每次 max_output_tokens=512；C3 关闭 SDK 和 Agent 重试。输出 token 预留是探测数量上限，不代表金额预算。
- 金额：供应商响应未提供费用金额或可核验单价，所有费用结论保持 unknown/null。不从 token 数估算费用。

## 方法与结果

OpenAIResponsesModel 经 OpenAIProvider 使用自定义 AsyncOpenAI 客户端；HTTPX 传输层在每次网络尝试前检查目标 host/path、固定模型与 reasoning、显式输出上限、当前 provider 配置及凭据是否仍与本次授权快照一致。此探测级门禁不代表业务权限服务或 CloudHelm 费用服务。

持久 journal 已实现于忽略目录 .thesis-work/runtime-data/p0-sdk02.sqlite3。单个 SQLite 事务写入稳定 request ID、输入摘要、输出上限和预算预留并提交后才调用传输层；收到 HTTP 响应及解析到 usage 后追加结果行。请求正文、Authorization 头、凭据、完整对话和响应正文均不落盘。事务提交后断线且没有结果行时，查询状态为 unknown；同一批次/场景/请求序号/重试序号重启时沿用 batch ID，重复身份会阻止重放。

首轮 12 次真实请求发生在 journal 加入之前，只有当时进程内的传输记录，不能追认成发送前持久登记。随后建立独立的 SDK-02-C2 候选键，在该批每次真实出站前以新 SQLite 连接确认预留提交可见，并将确认事件写入 journal。该候选证明真实 provider 出站前持久预登记；它不补写首轮历史，也不证明产品权限/费用服务已就绪。

| 能力 | 实际观测 | 逐能力结论 |
|---|---|---|
| 正常 Responses 结构化输出 | 两批各 1 次 HTTP 200。第二批记录到供应商 usage：输入 3,580、输出 31、总计 3,611、cached input 0。 | PydanticAI OpenAIResponsesModel / OpenAIProvider 接口可直接复用。真实请求的持久预登记未验证。 |
| 校验修复 | 每批 2 次 HTTP 200。validator 有意拒绝首个结构化结果，再由 PydanticAI 发起修复请求；第二批两次 usage 分别为 3,585/25/3,610 与 3,637/236/3,873（input/output/total）。 | ModelRetry 路径可由受支持接口承载，CloudHelm Runtime 需要薄适配。拒绝由本地 validator 注入，不代表观察到了供应商返回 schema-invalid JSON。 |
| SDK 自动重试 | 本地 MockTransport 注入 503；max_retries=1 观察到两次模拟 HTTP 尝试，两条稳定记录分别预留 64 token，均追加 HTTP 503 结果。第二次独立进程查询到原 batch 和两条结果，并在 handler 前阻止重放。供应商真实批次未触发重试。 | OpenAI SDK 重试可被传输边界逐次拦截；需把该门禁接入产品请求登记入口。真实供应商故障行为未验证。 |
| 摘要压缩 | 每批一条固定摘要请求，HTTP 200。第二批 usage：输入 3,595、输出 37、总计 3,632。后续 Epoch 另有一条 HTTP 200，请求 usage 为 3,601/366/3,967。 | 摘要生成和新 Epoch 请求可用两个独立 PydanticAI 请求薄适配。冻结摘要/输入引用和产品费用登记未验证。 |
| 恢复后新请求 | 每批使用 AgentRunResult.all_messages() 建立恢复历史，再以新 Agent 发出一条 HTTP 200；第二批 usage：输入 3,998、输出 55、总计 4,053。 | SDK 消息历史续接可直接复用。此项不是 DBOS worker 崩溃或持久 checkpoint 恢复证据。 |
| DBOS 接入 | 锁定版本公开 pydantic_ai.durable_exec.dbos.DBOSDurability；本卡未启动 DBOS workflow 或数据库 checkpoint 实验。 | 官方接入接口存在；与逐请求门禁、检查点及真实崩溃恢复的组合未验证，不能判为通过。 |
| 费用门禁 | 输出 token 额度会在发 HTTP 前预留；无供应商金额/价格证据。 | 数量上限不等于金额准入。CloudHelm 真实费用预留入口继续阻塞，金额保持 unknown/null。 |

真实 HTTP 数量汇总：第一次配置不匹配拦截 0 次；首轮前 6 次 HTTP 200（当时 usage 解析器未识别 gzip 响应，usage 保持 unknown）；首轮后 6 次 HTTP 200，6 条响应均取得供应商 usage；SDK-02-C2 再发 6 次 HTTP 200，6 条响应均取得供应商 usage，并均有发送前预留可见事件；SDK-02-C3-STREAM 发出 1 次 HTTP 200，并取得 SSE、最终 usage 和 provider 标识。当前任务合计 19 次真实 HTTP，失败 0 次。另有本地模拟 HTTP 503 共 4 次（journal 版本前 2 次、journal 首次写入 2 次），以及本地响应丢失 1 次；重启后的模拟请求均在 handler 前阻断。模拟结果不计作供应商能力。

附加的本地响应丢失注入在 request record 和预算预留提交后产生一条 ReadError；journal 将该记录保留为 unknown。随后独立进程保持原 batch ID，并在 MockTransport handler 前阻止重复身份的请求；此路径没有供应商 HTTP。

第二批六条带供应商 usage 的安全记录 ID：

| 场景/请求序号 | request_record_id | input / output / total / cached input |
|---|---|---|
| normal_structured_response | mr_488ebc3f9b6a337e58808b79 | 3580 / 31 / 3611 / 0 |
| validator_repair #1 | mr_512ab497f17f26f67382f892 | 3585 / 25 / 3610 / 3456 |
| validator_repair #2 | mr_a8df7b02c7461a8f9aaacbd6 | 3637 / 236 / 3873 / 2432 |
| context_compaction_summary | mr_14365fdb45c64ac9d668ac08 | 3595 / 37 / 3632 / 3456 |
| post_compaction_new_epoch | mr_417f2138147841430962dea6 | 3601 / 366 / 3967 / 2432 |
| restored_history_new_request | mr_6f46895b44f9705861579795 | 3998 / 55 / 4053 / 2432 |

上述六条供应商 usage 合计为 input 21,996、output 750、total 22,746、cached input 14,208。该汇总只反映供应商 token 字段，不是费用金额。

第一批六条进程内记录的 request ID 分别为：mr_0a79187050a6108340812dd3、mr_70ab26bbe4d680a0c79c8359、mr_68de2d370de645f15a64c996、mr_3b2134c521cb8d2afdb51763、mr_213d5d3f9083a1d1da46ea1c、mr_7b29f6b4a88002d6fa3d2a3b。这些请求的传输记录曾输出于本地进程日志，但未持久保存；其 usage 在该次探测中记为 unknown。

## SDK-02-C2 候选真实出站验证

候选修订 SDK-02-C2 使用独立 probe_key p0-sdk02-authorized-live-candidate-2 和 batch_id c3eaa9b3360140b29cab6fbea8673c65。真实批次开始于 2026-10-13 04:46:56 UTC；SQLite batch 行建立于 04:47:12 UTC；首条预留记录建立于 04:47:13 UTC，末条于 04:47:39 UTC；HTTP/usage 结果行时间为 04:47:18 至 04:47:43 UTC。批次最大 6 次请求、3072 输出 token 预留；实际预留 6 次。

每次 HTTP 前，传输层先在事务中提交 reservation，再用新 SQLite 连接读取并核对 batch ID、request ID、request digest、单请求 token 上限和批次计数；成功后追加 preflight_commit_visible 事件，之后才进入 HTTPX transport。六条记录均输出并写入该确认事件。

| 场景/序号 | request_record_id | 供应商 response id（当次进程捕获） | input / output / total / cached input |
|---|---|---|---|
| normal_structured_response | mr_9ca106cbdb691a2e49d06610 | resp_0ce551ce53f24c99016acdb7d477e4819d992e3464b3799c4a | 3580 / 104 / 3684 / 3456 |
| validator_repair #1 | mr_10072a9582b69e423924b197 | resp_0cc14ef82861f1a8016acdb7d7a414819eaf37bf492eff5155 | 3585 / 25 / 3610 / 3456 |
| validator_repair #2 | mr_6f082ec981012b8720faca5d | resp_0cc14ef82861f1a8016acdb7dae008819ebc560b41f4e517a1 | 3637 / 174 / 3811 / 3456 |
| context_compaction_summary | mr_35a92a3f5de7b60a7a693f1f | resp_05aca7c7d5866250016acdb7e2415c819cb2ab8726190ccdda | 3595 / 38 / 3633 / 3456 |
| post_compaction_new_epoch | mr_0fb5eb8e3c2223e63876ce91 | resp_086ba0421eb610e2016acdb7e73f68819db6e3ee1a2462dd23 | 3602 / 319 / 3921 / 2432 |
| restored_history_new_request | mr_68bb0aa06c61edb4b4c9cb4c | resp_086ba0421eb610e2016acdb7ebe760819d800f837da191eb62 | 3952 / 326 / 4278 / 2432 |

SDK-02-C2 的 6 条 usage 合计 input 21,951、output 986、total 22,937、cached input 18,688。金额仍为 unknown/null。批次结果表有 6 条 preflight_commit_visible、6 条 http_response_received 和 6 条 vendor_usage_observed；每个 request ID 的保留上限为 512，HTTP status 均为 200。第二次运行同一 --live 命令时从相同 batch ID 读取 6 条记录，输出 replay=existing_records、real_http_requests=0，退出码 1 表示预期阻断。

当次 PydanticAI 输出中的 C2 response id 未进入 journal：usage stream 在 ModelResponse 提供 provider_response_id 之前已追加 usage 结果，之后仅更新进程内记录。因此 C2 journal 的 provider_response_id 非空数为 0。SDK v3.29.0 离线 default_headers 名称为 Accept、Content-Type、OpenAI-Organization、OpenAI-Project、User-Agent、X-Stainless-Arch、X-Stainless-Async、X-Stainless-Lang、X-Stainless-Package-Version、X-Stainless-OS、X-Stainless-Runtime、X-Stainless-Runtime-Version；C2 探测器只读取 x-stainless-retry-count，未记录每个实际请求的完整 headers，也未捕获 x-request-id、request-id 或 correlation header。Authorization 值不记录。主会话随后转述用户确认服务端已有请求记录，但首 18 次请求为同步请求；C3 持久记录了 provider response id 和响应头 x-request-id。

## SDK-02-C3-STREAM 候选真实流式验证

候选修订 SDK-02-C3-STREAM 使用固定 probe_key p0-sdk02-authorized-live-candidate-3-stream 和 batch_id 352bf8f9f2834e109b1bee96b3a3af50，预留上限 1 次请求/512 输出 token。UTC 记录：探测命令启动 2026-10-13 05:08:31；batch 行建立 05:08:46；request record 及发送前独立连接确认 05:08:47–05:08:48；HTTP response 05:08:52；usage、provider 标识和最终结果写入 05:08:53。第二次启动同命令读回原记录并在 provider 配置解析和 HTTP 前阻断，真实 HTTP 为 0。

本次使用 PydanticAI 2.55.0 的 Agent.run_stream_events，不以 asyncio 并发冒充流式调用。transport 在发送前核验请求 body 中 stream=true，并拒绝非流式 body；AsyncOpenAI max_retries=0、Agent retries=0。真实请求记录 stream_requested=1、HTTP 200、Content-Type=text/event-stream，包含 response.completed。最终 history/result 只在 PydanticAI event stream 成功结束后取得；发生中断时 journal 保留 unknown，不把 partial event history 标为 complete。

| 证据 | 实际值 |
|---|---|
| request_record_id | mr_98eb13f2567899157603cdff |
| stream / HTTP / Content-Type | true / 200 / text/event-stream |
| Responses SSE event counts | response.created 1；response.in_progress 1；response.output_item.added 1；response.content_part.added 1；response.output_text.delta 7；response.output_text.done 1；response.content_part.done 1；response.output_item.done 1；response.completed 1 |
| PydanticAI event counts | PartStartEvent 1；FinalResultEvent 1；PartDeltaEvent 6；PartEndEvent 1；AgentRunResultEvent 1 |
| provider usage | input 3,543 / output 11 / total 3,554 / cached input 0 |
| provider_response_id | resp_0f0a09b094895ada016acdbce0fb8c81a08b81d9c80444dd3e |
| response header x-request-id | 8dde08d5-059d-46ac-b910-20bb93a7e589, 65a47d88-0fe3-48b4-be44-11b5807192f2 |
| preflight/journal | preflight_commit_visible 1；http_response_received 1；vendor_usage_observed 1；provider_metadata_observed 1；stream_final_result_observed 1 |
| 金额 | unknown/null |

event output 仅记录事件名称和计数，不保留或输出 delta 文本。x-request-id accessor 返回的值按原响应头字段持久保存；没有另外记录请求 header 集合。已验证的 C3 response ID 和 x-request-id 在第二次进程启动后从 journal 读回相同值。C2 旧记录未补写或重解释。

此一条请求不包含工具调用或副作用回调；断流故障分支未在本候选追加请求中注入。工具/回调及断流行为的实测归 SDK-03；C3 仅证明正常 SSE 流、终止事件、final result、usage 和标识落盘。

## 可复核命令与证据

以下命令均在 WSL 仓库根目录执行：

~~~bash
uv run python -m py_compile scripts/p0/model_boundary.py scripts/p0/probe_model.py
uv run python scripts/p0/probe_model.py
uv run python scripts/p0/probe_model.py --fault-check
uv run python scripts/p0/probe_model.py --live
uv run python scripts/p0/probe_model.py --live-stream
git check-ignore -v .thesis-work/runtime-data/p0-sdk02.sqlite3
~~~

py_compile、默认诊断及本地故障检查通过。默认诊断报告 live=disabled、真实 HTTP 为 0，且不读取 provider 凭据。journal 首次写入结果为 mode=first_write_and_reopen、模拟 HTTP 2、持久记录 2；另一次进程启动结果为 mode=restart_replay_blocked、模拟 HTTP 0、持久记录 2，batch ID 保持不变。gzip JSON 与 Responses SSE usage parser 固定样例通过。.thesis-work/runtime-data/p0-sdk02.sqlite3 由根 .gitignore 排除；SQLite schema 仅包含 probe batch、request record 和追加结果字段，没有正文或凭据字段。

首轮两批和 SDK-02-C2 使用固定命令 uv run python scripts/p0/probe_model.py --live；首轮两次各发出 6 次，C2 发出 6 次，C2 后的重开验证没有发出 HTTP。C3 使用 uv run python scripts/p0/probe_model.py --live-stream 发出 1 次流式 HTTP；再次运行从 journal 读回同一条记录并在 HTTP 前阻断。第一次配置默认模型不匹配造成的前置拒绝未发出 HTTP。所有输出只含 request ID、usage、HTTP status、异常类型、Content-Type 和事件名称/计数；未输出响应正文、delta 文本或凭据。

附加未知结果记录 ID 为 mr_c4da71a51ece1d03946d8a51，batch ID 为 96e6fe516e554dffb99fafa080111e78；重启查询仍返回同一 ID、http_status=null、transport_error_type=ReadError、journal_outcome=unknown。

## 阻塞入口、责任角色与复核点

用户随后确认 s2a 请求记录可见，并指出原请求显示同步；该观察与原 18 次 Agent.run 非流式调用一致。C3 实际 stream=true/SSE 证据及持久 response/request ID 已单列，未把先前非流式请求改写成流式通过。

- 阻塞入口：CloudHelm Runtime 中要求 D01 持久 ModelRequestRecord 和当前业务门禁的真实模型调用、SDK 重试、压缩和恢复路径。当前 SQLite 仅为忽略目录中的 P0 诊断 journal，不是产品存储、业务预算服务或 DBOS 持久调度。
- 阻塞原因：首轮 12 次真实请求都发生在 SQLite journal 实现前，不能追认发送前持久登记；C2 和 C3 均有真实出站前可见证据。真实金额准入仍缺少价格/费用证据，且产品级当前业务权限、持久 DBOS workflow/checkpoint 组合未由本卡证明。流式工具回调和断流没有在 C3 中实测。
- 解决责任：Runtime/预算负责人接入当前业务权限、持久请求记录和费用预留；workflow/DBOS 负责人验证官方 DBOS 接入下的检查点恢复；独立验收负责人复核证据及支持范围。
- 复核点：以新授权的固定 InputSet 在真实供应商出站前检查 journal commit；分别制造 HTTP 错误、响应丢失和进程恢复，验证 unknown 与重复身份阻断；接入供应商费用证据前继续保持金额 unknown；DBOS worker 崩溃恢复应归 SDK-06/相应工作包取证。
- 退出结论：C2 的 6 次请求及 C3 的 1 次 SSE 请求均有 SQLite 预留提交可见和结果证据；C3 持久保存供应商 response ID 与响应 x-request-id。SDK-02 整体仍未通过金额准入及产品 DBOS/权限集成门槛。不得据此开放 CloudHelm 产品模型入口，也不替代 P0.1-07 集成复核或人类验收。
