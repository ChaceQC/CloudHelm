"""业务服务层。

Service 负责状态流转、输入关联校验、事务提交和事件写入。API 路由只负责
HTTP 参数与 DTO，Repository 只负责数据库访问。
"""
