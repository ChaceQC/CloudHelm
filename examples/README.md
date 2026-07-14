# examples

本目录保存毕业设计演示所需的 sample repo、演示 issue、演示脚本和验收证据。

- `sample-repo-python/`：M6 本地开发闭环使用的受控 FastAPI fixture。基线只提供
  `/health`、Prometheus `/metrics` 和对应 pytest；注册、登录、个人资料能力由
  `demo-issues/001-auth-profile.md` 描述，初始代码有意不实现这些目标功能。

CloudHelm 执行 Scaffold 时会把 fixture 复制到受控工作区，再在副本中初始化独立
Git 仓库；本目录本身不保存嵌套 `.git`、虚拟环境、缓存或构建产物。
