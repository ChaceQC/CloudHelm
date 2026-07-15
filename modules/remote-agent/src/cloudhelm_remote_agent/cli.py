"""Remote Agent HTTP 服务和 heartbeat worker 命令行入口。"""

import argparse
import asyncio
import logging
import signal

from pydantic import ValidationError
from pydantic_settings import SettingsError
import uvicorn

from cloudhelm_remote_agent.config import Settings, get_settings
from cloudhelm_remote_agent.credentials import read_machine_secret
from cloudhelm_remote_agent.exceptions import CredentialError
from cloudhelm_remote_agent.heartbeat import HeartbeatClient
from cloudhelm_remote_agent.main import create_app

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    """使用不包含请求正文和凭据的基础日志格式。"""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # HTTPX/HTTPCore 的 INFO 请求日志会包含完整控制面 URL；Remote Agent
    # journal 只保留本模块的稳定错误码和状态，不记录管理入口。
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    logging.getLogger("httpcore2").setLevel(logging.WARNING)


async def _run_heartbeat(settings: Settings) -> None:
    """安装停止信号并运行 heartbeat 循环。"""

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in ("SIGINT", "SIGTERM"):
        shutdown_signal = getattr(signal, signal_name, None)
        if shutdown_signal is None:
            continue
        try:
            loop.add_signal_handler(shutdown_signal, stop_event.set)
        except (NotImplementedError, RuntimeError):
            # Windows 默认事件循环由 KeyboardInterrupt 取消任务，AsyncClient
            # 上下文仍会完成关闭。
            continue
    await HeartbeatClient(settings).run_forever(stop_event)


def _load_settings() -> Settings | None:
    """读取配置并把校验失败收敛为稳定、脱敏日志。"""

    try:
        return get_settings()
    except (SettingsError, ValidationError):
        logger.error("remote_agent_configuration_invalid")
        return None


def heartbeat_main() -> int:
    """运行独立 heartbeat worker；返回适合 console script 的退出码。"""

    _configure_logging()
    settings = _load_settings()
    if settings is None:
        return 2
    try:
        # 启动时先失败快检；循环中仍会每次重读，以支持凭据原子轮换。
        read_machine_secret(settings.credential_file)
    except CredentialError as exc:
        logger.error("remote_agent_startup_failed code=%s", exc.code)
        return 2
    try:
        asyncio.run(_run_heartbeat(settings))
    except KeyboardInterrupt:
        logger.info("heartbeat_worker_stopped")
    return 0


def _serve(settings: Settings, host: str, port: int) -> int:
    """启动仅含运行信息端点的 Uvicorn 服务。"""

    uvicorn.run(
        create_app(settings),
        host=host,
        port=port,
        log_config=None,
    )
    return 0


def main() -> int:
    """解析 ``serve``/``heartbeat`` 子命令并运行对应进程。"""

    parser = argparse.ArgumentParser(prog="cloudhelm-remote-agent")
    subcommands = parser.add_subparsers(dest="command", required=True)
    serve_parser = subcommands.add_parser("serve", help="启动只读 HTTP 运行信息接口。")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=9443)
    subcommands.add_parser("heartbeat", help="启动 Platform API heartbeat worker。")
    arguments = parser.parse_args()

    _configure_logging()
    settings = _load_settings()
    if settings is None:
        return 2
    if arguments.command == "heartbeat":
        try:
            read_machine_secret(settings.credential_file)
        except CredentialError as exc:
            logger.error("remote_agent_startup_failed code=%s", exc.code)
            return 2
        try:
            asyncio.run(_run_heartbeat(settings))
        except KeyboardInterrupt:
            logger.info("heartbeat_worker_stopped")
        return 0
    return _serve(settings, arguments.host, arguments.port)
