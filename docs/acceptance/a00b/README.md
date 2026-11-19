# A00b 候选读取固定输入

本页交给 A01/A02 使用。架构细化方案 `docs/architecture/2026-11-19-agent-architecture-detailed-design.md` §3.3、§10.1 和 §10.2 是样例依据，源稿 SHA-256 为 `7078d0c9c8548e2ebd8f76adf74d678df352280635022fe0746107287b283370`。[候选读取独立断言](candidate-read-assertions.md)由独立验收负责人在生成候选前冻结，SHA-256 为 `d6934eae43065f6aca256fb0873d167b8d8b9522c6684dafb3ebabd74b568b24`；集成负责人保管实际输入与回执。候选仓库不包含这份断言。

## Git 对象与预期

来源为 [A00a 隔离安装](../../development/a00-isolated-install.md)中的便签参照导入 `source-import-60597fd121b0407e8e47d62a3246f955`。项目 `a00b-notes`，受管来源 `source-60597fd121b0407e8e47d62a3246f955`、修订 `1`，空 `source_prefix`、SHA-1 对象库；`refs/heads/main` 是该私有项目的目标引用。清单为 `p1-workspace-manifest-r1`，SHA-256 覆盖按路径排序的模式、字节数和文件内容摘要，与 Git 树 ID 分别记录。

|输入|Git 提交 SHA|Git 树 ID|树清单 SHA-256（不含 `sha256:` 前缀）|独立预期|
|---|---|---|---|---|
|B0|`7ec1ab83bdc963b4d6521d832f7f53f7a874dc11`|`44fb9a050992e7e0e858f8eee535e0d8d151b628`|`31a82fa9e1e04c27a8df2f6a35b04c7a482ab0aecdccee174b958d1d71ea3974`|便签按 ID 升序，32 个文件|
|D1|`c72c844960a774a4dd6563b0987888a9591a8dcc`|`6b67f080cd9afe43874084f9b7e2b2e3904874f3`|`06e5c5368097f6481a6034ff556876d768f6913996d1e6a2804ba297ee6ab3a3`|从 B0 只将 `backend/app/routes.py` 的 `id.asc()` 改为 `id.desc()`，无目标文件|
|T1|`dcd1e3e2978bd677751c472b98bd12ff48986d3a`|`069d65be20518666659d2dd61b69454de2fde4f2`|`ece47c45b0003d73409b6ed46cd8704cf91046bbbb117373a6950812e00c65a2`|从 B0 只新增 `docs/a00b-target-only.txt`，33 个文件|
|M1|`dc11bcde39fc6b30e4f04e7af1e2194e48476df7`|`654b2649d2f46284e444b056251d980dd912cdc2`|`73883f4752a17ab5999bedce4f19228b5650d4e3b45bf0999f20420e5adf03ac`|父提交依次是 T1、D1；能读首个目标文件；T1 → M1 的差异仅含排序修改|
|T2|`3fa79bae0d6e1f4f7e9dfd8a72430a7f4a16e330`|`bb3e57d71fae8731f7aa636c9db7ecbcd529e5ee`|`59065f50c9609c4f9aec85620305cc8cf7669329491f43c740dbc50039b00283`|从 T1 只新增 `docs/a00b-target-moved.txt`，D1 和 Task 来源不变|
|M2|`78b615717490a72169753e5104691947160c6b4d`|`454f1c4ca00569b5be99e37ab435b289411e85db`|`77176a89a2f1a3d7b416ee680b3a6736ebf9b4562b69efe6eeb51cf506ab959d`|父提交依次是 T2、D1；可读两个目标文件；T2 → M2 的差异仍仅含排序修改|

## 业务与输入引用

两个尝试属于同一队列条目 `merge-entry-24c6bc56d98c41ffb6783230a3d9cadf` 和 Task `1f795039b9a14775bf2ade304f238f1d`。D1 的工作区为 `workspace-c2f6116be7c347019555e47ef3f66061`，冻结候选 `candidate-fbc8a4fab2fc4b8c8116dea5a28baf01`。同项目另有 Task `41d3893babf54f2b89c2f15d789305b4`，用于 A02e 错作用域输入。

|阶段|最终候选 ID|尝试 ID|对应构建 InputSet ID|
|---|---|---|---|
|M1|`integration-candidate-c4007da80a900b7b102dacaf943619b8e1223c0df77bc2a6e057ef766de4574c`|`merge-attempt-24c6bc56d98c41ffb6783230a3d9cadf`|`build-inputs-36a8af5c153a5774cf626aebefcc63d02aa705dcb06fa443845561d81577446e`|
|M2|`integration-candidate-602b29ddecf01a03fcb730e57fadfb6645583bec301bd04b749f2e62bfaddfef`|`merge-attempt-0f75e1246ee443f8843f50f45e707589`|`build-inputs-9778ef93293a028449c575a3be3022a53902871d0de75e6c78b9303654f67411`|

- 两轮共享已登记的 Task `source_input_set_ref`：`input_set / collaboration / reference-engineering-f16b44dd6fd10b88cb9453ad6e32e01c003ae9056dcd1d16d44170e361078d3c / p1-reference-task-input-r1`，引用摘要 `sha256:5a23074bf7b33c119e2462e2ac93b5ea49d08511219e1e4068ed65eec3068fea`。[便签正式资产](../reference/README.md#新资产登记及历史边界)绑定 `reference-public-assets-r2`，bundle `sha256:5142b355dcf055da498e8705864c789e82c15b656f1ffe3e4ca8c7afc5b0855f`，与本页的独立读断言分开。
- 构建 InputSet 由现有构建解析在各尝试当前时只读装配，集合摘要为 `sha256:` 加各 ID 的 64 位十六进制后缀。两轮构建定义相同，候选引用与 InputSet 不同。A00b 未登记 BuildRun，未生成构建后固定候选或报告的 InputSet。

## 后续验证入口

隔离项目当前目标为 T2，队列当前为 M2。原 M1 尝试与 Git 对象完整保留；T1 → T2 更新后对同一队列条目执行 `retry`，旧 M1 再进入构建输入解析时返回 `integration_attempt_not_current`。A02e 仍须验证目录、文件、差异、错 Task 拒绝及结果采纳，特别是实际目标变化后旧输入不能用于当前接受；本步没有报告或批准可供复用。

WSL 本机交接目录为 `/home/cloudhelm/.local/state/cloudhelm/a00a/a00b/`。`M1.json` 和 `M2.json` 保存完整候选、尝试、输入与摘要；同名 `.bundle` 和 `.dump` 分别固定 Git 引用和隔离库。摘要如下，完整校验值也保存在对应 JSON 中。运行产物均留在私有目录。

|阶段|回执 JSON SHA-256|Git bundle SHA-256|数据库快照 SHA-256|
|---|---|---|---|
|M1（目标 T1）|`1622a703fa364dc3ee1bc2626c852557acf1835f1e64f4c63d7f0db9cf38fa28`|`b2fab8b19a1e193d3042b130e8e5b0c9cb9b7457ff8f7a7c238a93b6fcf05e11`|`ef07dbefe4c29091bad3a98d7622c5366714e99edf3596b8cdf01c227acf330d`|
|M2（目标 T2）|`77c3cdd67f489e2bf6723a990a9eebd236cf377bec5c3fa69484c95098aeb34b`|`37acd5c640aa8b335283650817ab7e3b5991243eee48adb22221cd3be7904706`|`2ebecfcd4bc6301b9c57d587c09ff0e6ff80391c5c630ddc3859fa47167c9fa3`|

A02e 核对固定身份时配对使用同阶段的库快照和 Git bundle；需实际演练 T1 → T2 时，从 M1 恢复到单独验证副本，再以预期旧 SHA 更新目标，不能倒拨当前安装。若重新执行准备命令，相同 T2、D1 会形成新的尝试身份；准确对照本页的 M2 时使用原 M2 检查点。当前只核对了检查点的生成、摘要和目标引用，未演练数据库恢复。架构重构的真实构建、原生 Desktop 和独立交付环境另行准备。运行结果见 [A00b 进度](../../../PROJECT_PROGRESS.md#2026-11-19a00b-固定候选读取样例)。
