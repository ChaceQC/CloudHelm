"""数据库基础设施包。

该包只负责 SQLAlchemy Base、Engine、Session 生命周期和 Alembic 可识别
的 metadata 导出；业务查询必须放到 repositories 层，避免 API 路由直接
访问数据库细节。
"""
