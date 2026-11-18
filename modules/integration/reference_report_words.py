"""Chinese report text for the frozen reference-http-checks-r1 catalog."""

REFERENCE_CHECK_WORDS: dict[str, tuple[str, str, str]] = {
    # Baseline: setup and HTTP entry points.
    "REF-02-04.marker_cleanup_before": (
        "baseline",
        "运行前清理测试标记",
        "从列表精确匹配预留测试标题（含持久化标记），按 ID 删除匹配项；每次删除返回 204 或 404。",
    ),
    "REF-06.health_200": (
        "baseline",
        "服务存活接口可访问",
        "访问 GET /health 返回 HTTP 200。",
    ),
    "REF-06.ready_200": (
        "baseline",
        "正常环境下服务就绪",
        "访问 GET /ready 返回 HTTP 200。",
    ),
    "REF-01.static_root_html_200": (
        "baseline",
        "首页返回静态 HTML",
        "访问 GET / 返回 HTTP 200，响应类型包含 text/html，且响应非空并可用 UTF-8 解码。",
    ),
    "REF-01.same_origin_javascript_bundle_200": (
        "baseline",
        "首页引用的同源脚本可下载",
        "首页引用的同源脚本中，至少一个返回 HTTP 200、非空内容和 JavaScript 或 ECMAScript 响应类型。",
    ),
    # Baseline: note creation, reads, edits, and deletion.
    "REF-02-03.create_201_server_integer_id": (
        "baseline",
        "创建便签并由服务端分配 ID",
        "提交标题和正文时不提供 ID；POST /api/notes 返回 201 和带整数 ID 的便签对象。",
    ),
    "REF-03.create_returns_title_body_utc_timestamps": (
        "baseline",
        "创建响应包含原文和 UTC 时间",
        "创建返回的标题和正文与提交值一致；便签对象的创建和更新时间为带 UTC 时区的 ISO 8601 时间。",
    ),
    "REF-02.read_200_and_values": (
        "baseline",
        "按 ID 读取已创建的便签",
        "GET /api/notes/{id} 返回 200 和便签对象，包含整数 ID、字符串标题和正文，以及 UTC 创建和更新时间。",
    ),
    "REF-02.read_values": (
        "baseline",
        "读回的标题和正文与创建时一致",
        "逐项比对读取返回的标题和正文，二者均与创建时提交的值相同。",
    ),
    "REF-02.patch_single_field_accepted": (
        "baseline",
        "允许只修改标题",
        "PATCH /api/notes/{id} 只提交新标题，接口返回 200 或 204。",
    ),
    "REF-02.patch_response_object": (
        "baseline",
        "修改接口返回 200 时包含便签对象",
        "仅在 PATCH 返回 200 时检查响应，其中含整数 ID、字符串标题和正文，以及 UTC 创建和更新时间。",
    ),
    "REF-02.patch_persisted_values_read_200": (
        "baseline",
        "修改后仍可按 ID 读取便签",
        "再次 GET /api/notes/{id} 返回 200 和符合字段类型要求的便签对象。",
    ),
    "REF-02.patch_values": (
        "baseline",
        "新标题已保存，正文仍为原值",
        "重新读取后，标题等于提交的新标题，正文等于创建时的正文。",
    ),
    "REF-02.patch_empty_rejected_422": (
        "baseline",
        "拒绝空的修改请求",
        "PATCH 发送空 JSON 对象时，接口返回 422。",
    ),
    "REF-02.patch_unknown_field_rejected_422": (
        "baseline",
        "拒绝未知修改字段",
        "PATCH 只发送未定义的字段时，接口返回 422。",
    ),
    "REF-02.patch_null_rejected_422": (
        "baseline",
        "拒绝把标题改成 null",
        "PATCH 发送值为 null 的标题字段时，接口返回 422。",
    ),
    "REF-02.delete_204": (
        "baseline",
        "删除已创建的便签",
        "DELETE /api/notes/{id} 返回 204。",
    ),
    "REF-02.deleted_read_404": (
        "baseline",
        "删除后无法再读取便签",
        "删除后用同一个 ID 发起 GET 请求，接口返回 404。",
    ),
    "REF-02.missing_get_404": (
        "baseline",
        "读取不存在的便签返回 404",
        "对不存在的测试 ID 发起 GET 请求，接口返回 404。",
    ),
    "REF-02.missing_patch_404": (
        "baseline",
        "修改不存在的便签返回 404",
        "对不存在的测试 ID 发送只修改标题的 PATCH 请求，接口返回 404。",
    ),
    "REF-02.missing_delete_404": (
        "baseline",
        "删除不存在的便签返回 404",
        "对不存在的测试 ID 发起 DELETE 请求，接口返回 404。",
    ),
    # Baseline: input validation and returned values.
    "REF-03.title_trimmed_on_create": (
        "baseline",
        "允许提交首尾有空白的标题",
        "提交首尾带空格、制表符和换行的测试标题，创建接口返回 201 和便签对象。",
    ),
    "REF-03.title_trimmed_value": (
        "baseline",
        "创建响应中的标题已去除首尾空白",
        "创建直接返回的标题与预期的去除首尾空白后的标题完全相同。",
    ),
    "REF-03.trimmed_title_read_back": (
        "baseline",
        "可按 ID 读回带空白标题创建的便签",
        "用创建返回的 ID 读取便签，接口返回 200 和符合字段类型要求的便签对象。",
    ),
    "REF-03.trimmed_title_persisted": (
        "baseline",
        "读回的标题仍无首尾空白",
        "读取返回的标题与预期的去除首尾空白后的标题完全相同。",
    ),
    "REF-03.title_1_accepted": (
        "baseline",
        "接受 1 字符标题",
        "尝试以 1 字符的测试标题创建便签，接口返回 201 和便签对象。",
    ),
    "REF-03.title_1_accepted_length": (
        "baseline",
        "返回标题长度为 1 字符",
        "创建响应中的标题恰为 1 字符，ID 为整数。",
    ),
    "REF-03.title_120_accepted": (
        "baseline",
        "接受 120 字符标题",
        "尝试以 120 字符的测试标题创建便签，接口返回 201 和便签对象。",
    ),
    "REF-03.title_120_accepted_length": (
        "baseline",
        "返回标题长度为 120 字符",
        "创建响应中的标题恰为 120 字符，ID 为整数。",
    ),
    "REF-03.title_121_rejected_422": (
        "baseline",
        "拒绝 121 字符标题",
        "尝试以 121 字符的测试标题创建便签，接口返回 422。",
    ),
    "REF-03.empty_title_rejected_422": (
        "baseline",
        "拒绝只有空白的标题",
        "以仅含空格和制表符的标题提交创建请求，接口返回 422。",
    ),
    "REF-03.missing_post_title_rejected_422": (
        "baseline",
        "拒绝省略标题的创建请求",
        "创建时只提交正文、没有标题字段，接口返回 422。",
    ),
    "REF-03.body_4000_accepted": (
        "baseline",
        "接受 4000 字符正文",
        "尝试以 4000 字符的测试正文创建便签，接口返回 201 和便签对象。",
    ),
    "REF-03.body_4000_retained": (
        "baseline",
        "返回正文长度为 4000 字符",
        "创建响应中的正文长度恰为 4000 字符。",
    ),
    "REF-03.body_4001_rejected_422": (
        "baseline",
        "拒绝 4001 字符正文",
        "尝试以 4001 字符的测试正文创建便签，接口返回 422。",
    ),
    "REF-03.post_body_defaults_empty": (
        "baseline",
        "省略正文时返回空字符串",
        "只提交标题时，创建返回 201 和便签对象，其中正文是空字符串。",
    ),
    # Baseline: list shape, sort order, and teardown.
    "REF-02-04.list_json_array_sorted_utc": (
        "baseline",
        "初始列表为按 ID 升序的 JSON 数组",
        "GET /api/notes 返回 200 和便签数组；列表中的 ID 唯一且升序，各项的创建和更新时间使用 UTC。",
    ),
    "REF-04.create_reverse_lexical_order_record": (
        "baseline",
        "创建一条标题字典序靠前的便签",
        "第二条测试便签的输入标题在字典序上早于第一条；创建返回 201 和便签对象。",
    ),
    "REF-04.reverse_lexical_pair_list_sorted_by_id": (
        "baseline",
        "以相反标题顺序写入后列表仍按 ID 排序",
        "创建两条测试便签后重读列表，接口返回 200 和便签数组，其中 ID 唯一且按升序排列。",
    ),
    "REF-04.reverse_lexical_pair_order": (
        "baseline",
        "两条测试便签都在列表中，较小 ID 在前",
        "两条便签的 ID 互不相同，列表中都能找到，且 ID 较小的一条排在前面。",
    ),
    "REF-04.list_sorted_after_writes": (
        "baseline",
        "写入和删除后列表仍按 ID 升序",
        "再次请求列表返回 200 和有效便签数组，其中 ID 唯一且按升序排列。",
    ),
    "REF-04.list_contains_live_boundary_records": (
        "baseline",
        "列表包含仍保留的六条测试便签",
        "按标题找到排序用的第二条，以及去空白标题、1 和 120 字符标题、4000 字符正文、未提交正文对应的样本。",
    ),
    "REF-02-04.marker_cleanup_after": (
        "baseline",
        "运行后清理本轮创建的便签和测试标记",
        "删除本轮记下的便签 ID，以及标题与预留测试标题完全相同的记录；每次删除返回 204 或 404。",
    ),
    # Seed: prepare the fixed note that the next phase will read.
    "REF-04.seed_ready_200": (
        "seed",
        "写入持久化标记前服务就绪",
        "写入前访问 GET /ready 返回 HTTP 200。",
    ),
    "REF-04.seed_clear_exact_reserved_marker": (
        "seed",
        "清理已有的持久化标记",
        "从列表找出与固定标记标题完全相同的便签，按 ID 删除；每次删除返回 204 或 404。",
    ),
    "REF-04.seed_create_fixed_persistence_marker": (
        "seed",
        "写入固定的持久化标记",
        "创建返回 201 和便签对象，响应的标题与正文分别等于该轮使用的固定标记值。",
    ),
    # After restart: read and remove precisely the seeded marker.
    "REF-04.persisted_marker_present_after_api_restart": (
        "verify-persisted",
        "重启后的检查阶段可读回持久化标记",
        "列表中恰有一条便签的标题与固定标记标题相同，且正文与预设内容一致。",
    ),
    "REF-04.persisted_marker_cleanup_exact": (
        "verify-persisted",
        "核对后精确清理持久化标记",
        "按已找到的标记 ID 和列表中精确匹配固定标记标题的便签 ID 清理；每次删除返回 204 或 404。",
    ),
    # Fault observation: compare the liveness and readiness endpoints.
    "REF-06.health_200_while_dependency_unavailable": (
        "not-ready",
        "依赖不可用时进程仍存活",
        "在依赖不可用的验收环境中，GET /health 仍返回 HTTP 200。",
    ),
    "REF-06.ready_503_while_dependency_unavailable": (
        "not-ready",
        "依赖不可用时服务报告未就绪",
        "在依赖不可用的验收环境中，GET /ready 返回 HTTP 503。",
    ),
}
