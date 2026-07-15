"""CloudHelm 远端 Agent。

当前 M7-1 切片提供进程健康信息、版本/capability 查询和发往 Platform API
的 machine-auth 签名心跳。远端部署、Compose、日志和 diagnostics 由后续
M7 切片继续实现。
"""

__all__ = ["__version__"]

__version__ = "0.5.1"
