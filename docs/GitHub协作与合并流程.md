# GitHub 协作与合并流程

## 1. 仓库与分支

- 仓库：[ChaceQC/CloudHelm](https://github.com/ChaceQC/CloudHelm)，本次按用户明确要求建立公开仓库。
- remote 使用 `origin`，克隆地址为 `https://github.com/ChaceQC/CloudHelm.git`。
- 默认主分支为 `main`；日常开发在 `dev` 或用户明确指定的当前开发分支。
- 首次初始化空仓库时，`main` 和 `dev` 从同一个已检查的初始提交建立并推送初始引用。分支建立后启用保护，后续进入 `main` 的变更一律通过 PR。
- 正常开发可直接向开发分支提交与推送，不为每次提交另建 PR 或工作分支；通常在阶段交付时创建 `dev → main` PR。
- 实现、自动验证、人工验收和发布分别记录。提交或推送不代表功能已经验收，合并到 `main` 不自动创建 tag 或 Release。

## 2. 每个小步的提交

开始前阅读 `AGENTS.md`、`docs/design/README.md`、D06《实施计划与验收》和当前任务涉及的详细设计。任务级 `PROJECT_PLAN.md` 建立后同时阅读，依其任务编号执行。

每个可验证小步完成后：

1. 同步受影响契约、设计、使用说明与 `PROJECT_PROGRESS.md`；检查 `README.md`、`AGENTS.md`、`AGENT.md`（若存在）和子目录 README 是否需要调整。
2. 查看 `git status` 和本次差异，确认提交范围；保留用户其他改动。
3. 运行与本次改动相关的必要验证，记录实际结果和未验证范围。文档及 Git 配置变更不运行无关业务测试。
4. 按明确路径暂存，检查暂存差异及 `.gitignore` 是否正确排除本地文件。
5. 使用中文提交说明 commit，并 push 当前开发分支；失败时记录原因与当前状态，修复后继续。

```powershell
git status --short --branch
git diff
git add <本次改动的文件路径>
git diff --cached --stat
git diff --cached --check -- . ':!docs/archive/**'
git commit -m "docs: 同步当前任务的设计与进度"
git push
```

`docs/archive/` 保存被设计书引用的历史基线和校验清单；这些源资料保持原始字节，不通过换行或格式整理改写。运行备份、秘密、依赖、构建产物和 `.thesis-work/` 不入库。公开模板只使用占位值。

## 3. GitHub Actions 与检查结论

当前工作流为 `.github/workflows/check.yml`，工作流名称是 **仓库验证**，job 和必需检查名称均为 **check**，界面通常显示为 `仓库验证 / check`。

当前检查覆盖必需文件、UTF-8 文本、入库范围、`.thesis-work/` 忽略规则、提交差异格式，以及 P0/参照工程的锁定依赖、Python 源码语法、契约导入、参照 OpenAPI 一致性和前端构建。收费模型、数据库/容器及故障实验由对应记录保存；这些 CI 检查不表示完整 SDK 接缝、容器部署或功能验收通过。

后续业务工程出现时，按实际变更为 `check` 增加必要构建、契约和规则验证；原生客户端隔离、真实机器部署和人工验收使用对应阶段的独立证据，不以普通 CI 通过替代。

## 4. 分支保护

|分支|保护规则|
|---|---|
|`main`|要求 PR；严格必需检查 `check`，来源为 GitHub Actions；规则对管理员生效；禁止强制推送和删除|
|`dev`|禁止强制推送和删除；不要求 PR 或推送前状态检查|

保护通过 GitHub 仓库设置启用，并读取实际配置核对。若账户权限或 GitHub 套餐不支持所需规则，写入 `PROJECT_PROGRESS.md` 并报告限制，不能把文档要求写成已经启用。

不得使用 `--admin`、临时关闭保护、强制推送、删除重建分支或先合并再等待检查来绕过规则。改变合并策略需有明确用户授权，并同步规范。

## 5. 合并到 main

1. push 当前开发分支，并创建指向 `main` 的 PR。说明具体行为变化、验证结果和仍待验收范围。
2. 获取最新远端状态，确认 PR 分支包含目标 `main` 的最新提交；若未包含，先在开发分支正常合并 `origin/main`、处理冲突、验证并 push。
3. 确认 PR 最新提交的 GitHub Actions 全部成功，必需检查 `check` 已通过。失败、运行中、取消、跳过或没有检查均不能合并。
4. 有新增提交或目标分支更新时，重新核对提交、包含关系和检查结论。检查通过只说明技术门禁成立；合并执行仍须处于用户授权范围。
5. 正常合并 PR，随后更新本地分支。日常复用 `dev` 时优先采用 merge commit，保留提交祖先关系；不删除 `dev`。

```powershell
git fetch origin
git switch dev
git merge --no-edit origin/main
git push origin dev
gh pr create --base main --head dev --title "交付当前阶段" --body-file <PR说明文件>
gh pr checks <PR编号> --required
```

只有在上述最新提交与全部 Actions 结论核对完成、且用户已授权合并时，执行正常 PR 合并。不得使用合并命令的管理员绕过选项。

## 6. 版本与发布

软件版本采用 `X.Y.Z`，tag 与发布名称采用 `vX.Y.Z`。非正式阶段使用 `v0.y.z`，正式稳定发布从 `v1.0.0` 开始。

总体设计 `v4.7`、专题 `v4.7.0` 与软件、SDK、数据库 schema、工作流应用和执行协议版本分别管理。当前建立 Git 仓库不生成软件版本、tag 或 Release。

仅在用户授权发布时维护版本元数据、发布文档、tag 和 Release；发布状态必须有对应产物与实际结果。
