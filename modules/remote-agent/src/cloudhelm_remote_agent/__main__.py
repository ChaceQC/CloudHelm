"""支持通过 ``python -m cloudhelm_remote_agent`` 启动模块。"""

from cloudhelm_remote_agent.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
