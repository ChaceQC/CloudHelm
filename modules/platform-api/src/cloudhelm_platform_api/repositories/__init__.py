"""数据库访问层。

Repository 只封装 SQLAlchemy 查询与持久化，不包含状态流转、事件写入或
审批规则；这些业务行为由 services 层负责。
"""
