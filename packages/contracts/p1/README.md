# Hub 基础契约

本目录维护 Hub 的固定请求、公共投影与内部交接类型。设计依据为 [P1.1 实施说明](../../../docs/implementation/p1-1-foundation.md) 与 [P1.2 工程实施说明](../../../docs/implementation/p1-2-engineering.md)，运行与维护入口见 [开发说明](../../../docs/development/p1-hub.md)。实现、开发验证和产品验收分别记录，类型校验不授予权限或证明执行事实。

|文件|职责|
|---|---|
|`commands.py`|有界持久命令结果、事件信封和两类 Task workflow 的交接身份；持久结果上限为 65536 个 UTF-8 字节|
|`identity_contracts.py`、`identity_requests.py`|当前身份、项目/角色投影、项目管理与受控维护请求；公共投影排除凭据及摘要|
|`task_requests.py`|Task 创建声明和启动/完成/取消/核对请求；目标、准确来源、预算与资源范围显式固定|
|`task_results.py`|Task、阻断对象及命令响应；创建失败不会返回虚构 Task 身份|
|`task_facts.py`|受控来源登记及 Task 消费事实的内部元数据，不能作为公共 HTTP 授权/完成输入|
|`task_internal.py`|域内推进与首次工程 InputSet 绑定请求；初次绑定只消费登记引用，不产生候选或验收结论|
|`workspace_git.py`、`workspace_records.py`|精确 Git 身份、独立文件清单、来源/工作区记录与物理候选；Git OID、文件清单和元数据摘要分别管理|
|`runner_contracts.py`|固定维护探针操作及逐能力事实；拒绝业务目标、任意命令、挂载或自报授权|
|`build_artifacts.py`|单一 linux/amd64 OCI 归档的内容回执、存储边界与工程引用；不代表 BuildRun 或运行验收成功|
|`source_requests.py`、`source_records.py`、`reference_requests.py`|固定参照导入意图、可信来源回执和初次真实工程 Task 输入；公共调用者不提交实物成功声明|
|`workspace_requests.py`、`workspace_uploads.py`、`workspace_candidates.py`|工作区版本/写入代次、32KiB UTF-8 文件入口及物理候选冻结；源码 bytes 只进入受控 staging，命令保存内容摘要|
|`build_requests.py`、`build_records.py`|BuildRun 的候选/输入/配方/锁/工具链及运行契约绑定，三角色制品内容与可信执行观察分别登记|
|`engineering_commands.py`|project/workspace/build 的同事务 DBOS 交接；工作流仅接收稳定 operation_id|
|`development_storage.py`、`development_environment.py`、`npm_cache.py`|受控开发实例修订、实际存储准入、环境生命周期及缓存键；注册和契约均不代替物理核验|
|`hub-openapi.json`|由实际 FastAPI factory 导出的 HTTP 结构快照，与当前实现一致性单独核验|

所有固定模型拒绝额外字段。API 还检查原始 JSON 重复键、非法数值和请求边界；真实主体、scope、action、当前授权及请求摘要由服务端解析和构造，不能用客户端自报的 `caller`、角色、`allowed` 或完成布尔值放行。

项目 developer 绑定可显式授予 `workspace.write`、`candidate.submit`、`operation.request`。旧 owner/角色/委托不因动作枚举扩展自动得到新权限；原结果回读仍须当前权。首次 InputSet 绑定使用 Task 元数据权限，不替代后续工程动作授权。

身份、工程引用及 Task 控制规则显式复用 [P0 决定契约](../p0/README.md)，沿用 `p0-decisions-r1` 与 `cloudhelm-jcs-sha256-r1` 的含义；新增路由绑定独立的固定请求 schema 修订。软件版本、业务迁移、DBOS SDK、工作流应用和 API/schema 修订独立管理，P0 历史字节不重算或改写。

命令先核对当前权限，再查完整主体/委托/项目/资源/幂等键。同键同摘要返回原命令身份、HTTP 状态和响应体，回读原结果同样要求当前访问权；同键异摘要返回冲突。新转换才检查预期版本。Task 完成和取消的新键命中 completed 时返回唯一原报告，启动的新键仍须满足 draft 来源约束。

`202 accepted` 表示可靠接收，不能表示 DBOS 工作流、Task 或物理操作已完成。查询接口读取当前业务投影；原命令回执保留原时点的结果，不回写成最新状态。事件 `event_id` 代表业务事实，Outbox 的存在不代表已经外发，也不把其数据库序号当作未来 Desktop 的同步游标。

完整完成报告只由当前持久事实构造，包含固定输入、集成来源、必需检查和证据。缺少真实来源、候选、验收或存在未核对的相关写意图时继续阻断。取消仅核对取消所需的当前权限、封闭/历史和物理事实，不以缺少开发验收材料阻止其受限收尾。人测结论保持真实值；Agent 不替人填通过或跳过。

完成命令的回执携带稳定 `completion_report_id`；完整报告通过同一 Task 的 `/completion-report` 入口按当前权限读取。同键重投和已完成的新键返回均指向同一份报告，不重新生成内容。

工作区当前 binding 可以递增，初次 `WorkspaceFiles` 的原字节及其 binding 保持不可变。记录要求固定归属、来源和 base commit 相等，初次 revision/generation 不超过当前值；旧严格读取器需要同步此校验。对应约束经新迁移 `0003_p1_2_builds` 调整，旧迁移和旧证据不改写。

`content_verified` 只表示已核验 OCI 内容。BuildRun 的 `succeeded` 还必须具有可信执行终结事实，以及 frontend/backend/postgres 三角色的 manifest、config、实际 loaded image ID 一致性。未收尾或未知的工作区/构建操作参与 Task 完成及取消门禁；物理候选、成功构建均不自动生成最终集成验收或人类结论。

OCI 内容回执的 `image_id` 保持 config digest 语义。执行观察单独保存 `loaded_image_id` 与 `docker_identity_kind`：当前 Docker 29 containerd 存储实际使用 manifest digest 标识镜像，须同时核对其 Descriptor、平台、RootFS 和运行配置。默认 `oci_config` 兼容旧协议记录，不能把两个不同身份直接互相替代。
