# Git、工作区与受限构建开发

本文对应 [P1.2 实施说明](../implementation/p1-2-engineering.md)。本轮工程链路正在接续实施，实际可用范围以 [P1.2 证据索引](../acceptance/p1/p1-2.md) 为准。Hub 的身份、数据库和进程入口见 [Hub 开发说明](p1-hub.md)。

## 1. 当前基线与隔离范围

本机开发环境是 WSL `Ubuntu-24.04`，仓库路径 `/mnt/e/Project/CloudHelm`。Python `3.12.13`、uv `0.11.29` 和根 `uv.lock` 固定解释器与依赖；安装和运行在 WSL 内执行。

当前开发源码为 `0.2.0`，DBOS 工作流应用为 `cloudhelm-hub/0.2.0`，业务迁移为 `0002_p1_2`。仅为本轮准备新隔离开发库；旧版安装必须另行完成受控升级，`database.manage initialize` 会拒绝版本不匹配的现有安装。

工作文件、受管 Git 元数据、候选、下载缓存、制品和执行临时目录具有独立位置与用途。受控运行数据放在 Linux 原生私有目录，不能放在 `/mnt/e` 的仓库工作树内；配置仅传受保护文件引用，不向命令参数、日志或公开输出写入密钥。

## 2. 工程授权

工程动作必须显式授予：工作区写入为 `workspace.write`，候选提交为 `candidate.submit`，构建请求为 `operation.request`。它们受既有 P0 角色上界约束，通过现有项目角色管理事务授予 developer 绑定。

既有 owner、角色和 Agent 委托不会因软件升级自动获得新动作。owner 如需执行工程动作，同样需要显式 developer 绑定；旧角色与委托保存的动作列表保持原意。每次推进及原结果回读都核对当前授权，撤权后不能依赖旧成功回执继续操作。

## 3. 受控 Runner 能力检查

固定能力探针只接受维护操作 `probe_capabilities`，不接收 Task、项目、任意命令、任意挂载或自报授权。它使用受限 rootless BuildKit，保留 process sandbox，以实际执行和宿主进程证据判断能力。

```bash
cd /mnt/e/Project/CloudHelm
/home/cloudhelm/.local/bin/uv run --frozen --no-sync python -m scripts.p1.probe_runner
```

探针在私有运行目录保存原操作、InputSet 和报告；公开输出只含有界事实与固定错误类别。失败按原操作核对，不使用 privileged、关闭 process sandbox 或挂入宿主 Docker socket 绕过限制。探针仅覆盖其固定限额，真实构建与制品加载需要各自的容量证据。

## 4. 当前限制

当前低层 Git 仅支持经受控登记的 managed bare 与独立工作文件；外部认证、LFS、submodule、完整 Git 模式和来源迁移按明确限制拒绝。Git OID 与内容 SHA-256 分别保存，初始文件回执不能表示可变工作区当前状态。

固定候选、缓存/数据、业务构建入口和制品运行验证正在接入，尚不提供完成或验收结论。完整共享宿主资源协议、Release、远端部署、Desktop 和人工验收按后续工作包交付。
