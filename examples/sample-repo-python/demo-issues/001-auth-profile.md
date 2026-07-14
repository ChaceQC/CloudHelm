# Demo Issue 001：实现注册、登录与个人资料

## 背景

当前 sample service 只有 `/health` 和 `/metrics`，没有用户或认证能力。本 issue
用于验证 CloudHelm M6 能否根据稳定验收标准，在受控工作区中产生真实代码、
测试、review、安全扫描、branch、commit 和本地等价 PR record。

下列 AC 编号是需求、测试报告和 review 报告的稳定追踪键；实现过程中不得重命名
或复用为其他含义。

## 范围

实现：

- 用户注册。
- 用户登录并签发 Bearer access token。
- 当前用户读取个人资料。
- 当前用户修改显示名称。
- 持久化用户数据，并为新增能力补充黑盒与白盒测试。

不实现：

- 邮箱验证、密码找回、第三方登录。
- refresh token、角色/权限、管理员接口。
- 头像上传、用户搜索和其他用户资料查看。

## HTTP 契约

### `POST /auth/register`

请求：

```json
{
  "email": "user@example.com",
  "password": "correct-horse-battery-staple",
  "display_name": "Demo User"
}
```

成功响应：`201 Created`

```json
{
  "id": "稳定用户 ID",
  "email": "user@example.com",
  "display_name": "Demo User",
  "created_at": "RFC 3339 UTC 时间"
}
```

### `POST /auth/login`

请求：

```json
{
  "email": "user@example.com",
  "password": "correct-horse-battery-staple"
}
```

成功响应：`200 OK`

```json
{
  "access_token": "签名后的不透明字符串",
  "token_type": "bearer",
  "expires_in": 1800
}
```

### `GET /profile`

请求头：`Authorization: Bearer <access_token>`

成功响应：`200 OK`，响应字段与注册成功时的公开用户资料相同。

### `PATCH /profile`

请求头：`Authorization: Bearer <access_token>`

请求：

```json
{
  "display_name": "Updated Name"
}
```

成功响应：`200 OK`，返回更新后的公开用户资料。

## 稳定验收标准

- **AC-AUTH-001 注册成功**：合法 email、8 到 128 字符密码和去除首尾空白后
  1 到 50 字符的 `display_name` 应创建持久化用户并返回 `201`；响应不得包含
  明文密码、密码摘要或 access token。
- **AC-AUTH-002 邮箱规范化与唯一性**：注册和登录都应先去除 email 首尾空白并
  转为小写；重复 email 注册返回 `409`，错误码为
  `email_already_registered`，且不得新增第二条用户记录。
- **AC-AUTH-003 注册校验**：email 格式错误、密码过短/过长、空白显示名称或
  显示名称超长均返回 `422`，不得写入用户记录。
- **AC-AUTH-004 登录成功**：正确凭据返回 `200`、`token_type=bearer` 和
  `expires_in=1800`；access token 能访问 `/profile`。
- **AC-AUTH-005 登录失败不泄露账号状态**：不存在的 email 与错误密码都返回
  `401` 和相同错误码 `invalid_credentials`，响应信息不得区分账号是否存在。
- **AC-PROFILE-001 鉴权边界**：`/profile` 的 GET/PATCH 缺少、损坏或过期
  Bearer token 时均返回 `401`，错误码为 `invalid_access_token`。
- **AC-PROFILE-002 读取资料**：有效 token 的 `GET /profile` 只返回 token
  所属用户的 `id`、规范化 email、`display_name` 和 `created_at`。
- **AC-PROFILE-003 更新资料**：有效 token 可把 `display_name` 更新为去除
  首尾空白后的 1 到 50 字符值；非法值返回 `422` 且原值保持不变。
- **AC-SEC-001 密码保护**：持久化层只保存成熟密码哈希算法产生的摘要；代码、
  API、日志、异常和测试产物均不得输出明文密码或 token。
- **AC-OBS-001 可观测性**：新增四个端点继续经过现有 HTTP 指标中间件，
  `/metrics` 使用路由模板和状态码记录请求，不得把 email、用户 ID 或 token
  放入 Prometheus 标签。
- **AC-TEST-001 回归与覆盖**：新增 pytest 覆盖注册、重复注册、注册边界、
  登录成功/失败、token 鉴权、资料读取/更新和持久化；现有 health/metrics
  测试继续通过，测试不得连接真实外部服务或污染开发者数据。

## 完成证据

- 每条 AC 在测试报告中映射为 `passed`、`failed` 或 `not_covered`。
- 真实 pytest、review 和安全扫描结果均引用同一次工作区变更。
- diff 中包含实现、迁移/持久化配置（如适用）、依赖锁文件和测试。
- 不以 mock 返回、固定 token、内存常量用户或跳过校验替代生产路径实现。
