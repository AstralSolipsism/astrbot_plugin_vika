# vika_mcp 标准 MCP 改造执行文档

日期: 2026-06-17
状态: 已对齐, 待执行
适用仓库: `D:\AboutDEV\vika_mcp`
目标客户端: AstrBot `D:\AboutDEV\astrbot`
对标项目: `vmoranv/jshookmcp@c29e9720bc97850fb1fe1d735ec3316723d66df4`

## 1. 结论

`vika_mcp` 要从当前自定义 HTTP MCP-style 服务, 收敛为标准 MCP server.

最终对外模型协议只保留:

- `stdio`
- `streamable_http`

不保留旧的 `/mcp/v1/tools`, `/mcp/v1/execute`, `/mcp/v1/stream/{job_id}` 作为兼容执行协议. 本轮不新增独立普通 HTTP health 路由; 如果后续运维需要 health, 必须另行设计为非 MCP 运维端点, 不能承载工具调用.

默认模型入口采用 JSHookMCP 式 search-first 模式, 但不照搬其复杂检索算法:

- 稳定元工具默认可见.
- 真实业务工具进入隐藏 registry.
- 模型通过 `search/route -> describe -> call_tool` 完成闭环.
- `vika_activate_domain` 只设置会话级 domain scope, 用于 search/route 排序和提示; 不动态注册业务工具, 不是主调用路径, 也不是权限开关.
- 大表数据默认导出为 CSV artifact 文件, 既可通过 MCP artifact search/read 像代码搜索一样读取, 也可由具备代码执行能力的 agent 用 pandas 等工具分析.
- 写入采用按"一次写入计划"确认的两阶段提交, 不做逐条确认.

## 2. 当前事实

### 2.1 vika_mcp 当前状态

当前服务由 FastAPI 暴露自定义路由:

- `server.py` 创建 FastAPI app, 注册 `ToolRegistry`, 挂载 `routes.py`.
- `routes.py` 暴露 `/mcp/v1/tools`, `/mcp/v1/execute`, `/mcp/v1/stream/{job_id}`.
- `mcp/executor.py` 提供自定义 job/stream 机制.
- `mcp/types.py` 的 `ToolSpec` 已包含 `name`, `description`, `input_schema`, `output_schema`, `examples`, `available`, `tags`.
- `tools/vika_tools.py` 当前注册 Vika 业务工具, 包括 catalog, schema, records, fields, views, attachments, datasheets.

这不是标准 MCP 协议. AstrBot 不能直接把 `/mcp/v1/execute` 当作 MCP server 使用.

### 2.2 官方 MCP Python SDK 命名冲突

当前仓库存在顶层目录 `mcp/`. 在源码目录下运行时, Python 会优先导入本仓库的 `mcp`, 导致官方 SDK 的导入失败:

```powershell
python -c "from mcp.server.fastmcp import FastMCP"
```

当前会失败, 因为解析到的是 `D:\AboutDEV\vika_mcp\mcp\__init__.py`.

因此标准 MCP 改造的第一步必须是内部包改名:

- `mcp/` -> `runtime/`

不保留第二个内部 runtime 命名候选, 避免执行时在包名上分叉. `runtime` 表达的是工具注册、校验、执行运行时, 不是协议本身.

### 2.3 AstrBot 能给大模型看到什么

AstrBot 的 MCP 接入路径是标准 MCP:

- `astrbot/core/agent/mcp_client.py` 使用 `mcp.ClientSession.initialize()`, `list_tools()`, `call_tool()`.
- `MCPTool` 只把 MCP tool 的 `name`, `description`, `inputSchema` 转成 AstrBot `FunctionTool`.
- `outputSchema` 不进入大模型工具 schema.
- `tool_schema_mode=full` 是默认值.
- `skills_like` 模式第一轮只给 name/description, 第二轮再给参数 schema.

所以模型操作手册不能依赖 `output_schema`. 必须放在:

- 默认可见元工具的 description
- `vika_guide` 的返回内容
- `vika_describe_tool` 的返回内容

### 2.4 AstrBot 的大输出保护不能作为主防线

AstrBot 有工具结果溢出保护, 阈值约 27,500 estimated tokens. 但它只有在配置了 `tool_result_overflow_dir` 和可用 file-read tool 时才会把大结果写文件. 这不是 vika_mcp 可以依赖的稳定边界.

vika_mcp 必须在服务端自己控制:

- inline 结果大小
- 单次查询记录数
- 字段裁剪
- 大表导出
- artifact search/read

## 3. JSHookMCP 对标结论

JSHookMCP 的关键模式:

- `search` profile 默认只注册少量元工具.
- `search_tools` 用于从大量隐藏/非默认工具中检索候选.
- `describe_tool` 返回目标工具 schema 和说明.
- `call_tool` 作为稳定代理, 解决客户端没有及时刷新动态工具列表的问题.
- `activate_domain` 和 `activate_tools` 可以动态注册工具, 但 `call_tool` 是客户端兼容桥.
- 工具按 domain/profile 管理, 并携带 read/write/destructive 等注解.
- 对大结果有 offload 机制.

vika_mcp 应复制产品模式, 不复制全部复杂度:

| JSHookMCP 模式 | vika_mcp 采用方式 |
| --- | --- |
| `search_tools` | `vika_search_tools`, 检索隐藏业务工具和工作流 |
| `route_tool` | `vika_route_task`, 给自然语言任务返回步骤 |
| `describe_tool` | `vika_describe_tool`, 返回 schema, 示例, 风险, 数据量策略 |
| `call_tool` | `vika_call_tool`, 直接执行隐藏 registry 中的工具 |
| `activate_domain` | `vika_activate_domain`, 只设置会话 domain scope, 不动态注册业务工具, 不提升真实写权限 |
| profile | 产品运行只实现 `search`; 不提供用户可配置的 `full` profile |
| offloader | artifact-first, 大表不先进上下文再 offload |

不能照搬的点:

- JSHookMCP 的 `search_tools` 默认可自动激活域; vika_mcp 对 `write` 域不能这样做.
- JSHookMCP 的 BM25/vector/boost 栈对 vika_mcp 过重; vika_mcp 先用可解释的字段加权检索.
- JSHookMCP 的动态工具列表刷新不是主路径; AstrBot 场景必须把 `vika_call_tool` 作为唯一业务工具调用闭环.

参考:

- JSHookMCP README: https://github.com/vmoranv/jshookmcp
- JSHookMCP 配置文档: https://vmoranv.github.io/jshookmcp/guide/configuration
- MCP Python SDK README: https://github.com/modelcontextprotocol/python-sdk

## 4. 目标

1. 标准 MCP 化: 支持 `stdio` 和 `streamable_http`.
2. 架构统一: 一个工具 registry, 一个执行路径, 一个模型操作手册.
3. 模型可探索: 模型能从表名、链接、自然语言意图出发, 定位表、看 schema、查询小样本、导出大表、搜索 artifact.
4. 输出可控: 默认不会把大表、大 schema、大节点树塞进上下文.
5. 写入可用且安全: 批量写入按一次写入计划确认, 不逐条确认, 也不允许模型探索性真实写入.
6. AstrBot 可用: AstrBot 能通过标准 MCP 初始化、列工具、调工具, 不需要修改 AstrBot 才能完成核心流程.

## 5. 非目标

- 不保留 `/mcp/v1/*` 自定义协议作为兼容路径.
- 不同时维护旧 HTTP execute 和标准 MCP 两套工具语义.
- 不默认暴露全部 Vika 业务工具给大模型.
- 不提供产品运行时 `full` profile; hidden registry 只能通过元工具访问.
- 不让 `records.read_all` 成为模型默认入口.
- 不依赖 AstrBot 的上下文压缩或大结果溢出保护兜底.
- 不做逐条写入确认.
- 不重写 `astral_vika` SDK.
- 不在本轮改造里追求高级向量检索; 先做可解释、可测试的检索.

## 6. 目标架构

```text
AstrBot / MCP Client
        |
        | stdio or streamable_http
        v
standard MCP server
        |
        v
visible meta tools
        |
        | search / route / describe / call_tool
        v
hidden Vika tool registry
        |
        v
VikaClient / astral_vika
        |
        +--> small inline results
        +--> artifact files for large table data
        +--> write operation store for preview/commit
```

核心原则:

- 协议层只做标准 MCP.
- 业务工具不直接等于模型可见工具.
- 模型默认看到的是稳定元工具和少量高层入口.
- hidden registry 中的业务工具仍可被 `vika_call_tool` 调用, 但必须经过 schema 校验、风险策略和结果策略.

## 7. 默认可见工具

默认 `search` profile 暴露以下工具:

| 工具 | 用途 |
| --- | --- |
| `vika_guide` | 返回短操作手册和必须遵守的流程 |
| `vika_resolve_datasheet` | 从 ID, URL, 表名, 空间名, 路径, 自然语言描述定位表 |
| `vika_search_tools` | 按任务关键词检索隐藏工具 |
| `vika_route_task` | 给自然语言任务返回推荐步骤和下一步 |
| `vika_describe_tool` | 返回隐藏工具的 schema, 示例, 风险, 输出策略 |
| `vika_call_tool` | 调用隐藏 registry 中的工具 |
| `vika_list_domains` | 列出 domain, 风险和默认可见策略 |
| `vika_activate_domain` | 会话级激活/提示域, 不改变真实写权限 |
| `vika_artifact_head` | 读取 artifact 文件头部/摘要 |
| `vika_artifact_search` | 在 artifact 内搜索字段值/关键词 |
| `vika_artifact_read` | 按行号/窗口读取 artifact |
| `vika_artifact_status` | 查询导出任务或 artifact 状态 |

产品运行时只提供 `search` profile. 开发测试如需直接枚举 hidden registry, 使用测试 helper 或内部调试脚本, 不通过 MCP `list_tools` 暴露业务工具.

## 8. Domain 模型

Domain 按任务语义、风险和数据体量划分, 不按 SDK 前缀划分.

| Domain | 典型能力 | 默认可见 | 自动执行 |
| --- | --- | --- | --- |
| `connection` | status, healthcheck, spaces list | hidden, route/call_tool 访问 | 只读可执行 |
| `discovery` | catalog, nodes, resolve datasheet | `vika_resolve_datasheet` 可见, 其余 hidden | 只读可执行 |
| `schema` | schema, fields.get, views.get | hidden, route/call_tool 访问 | 只读可执行, 受大小限制 |
| `query` | 小样本记录查询, records.get | hidden, 由 call_tool 调用 | 只读可执行, 强上限 |
| `export` | records export, artifact manifest | hidden, route 后调用 | 只读可执行, 返回 artifact |
| `write` | records/fields/datasheets/attachments create/update/delete | hidden | 只能 preview, commit 需确认 |
| `admin` | cache clear, 维护诊断 | hidden | 默认不自动 |

注意:

- `records.query` 和 `records.delete` 不能因为同属 `records` 前缀就放进同一个安全域.
- `activate_domain(write)` 不能打开真实写权限, 也不能让 write 业务工具出现在 MCP `list_tools` 中.
- `admin` 不能被自然语言搜索轻易误触发 destructive 操作.

## 9. 指定表定位主路径

新增高层工具 `vika_resolve_datasheet`.

### 9.0 Vika 作用域

本 MCP 最终对接指定 workbench 范围, 不默认探索 token 可访问的所有空间.

运行配置必须提供:

- `VIKAMCP_VIKA__API_TOKEN`: Vika API token.
- `VIKAMCP_VIKA__WORKBENCH_URL`: 目标 workbench URL. 当前目标为 `https://vika.cn/workbench/fod6mElQf7PFD`.
- `VIKAMCP_VIKA__WORKBENCH_SPACE_ID`: folder workbench 所在 space id. folder URL 必须提供该值; 禁止通过遍历 token 可见空间来推断.

`vika_resolve_datasheet`, catalog refresh, schema, query, export, write 都必须受该 workbench scope 约束:

- 有 URL/ID 输入时, 必须校验目标是否属于配置的 workbench scope.
- 无 `space_id` 时, 只能在配置 workbench scope 内发现候选.
- 不得因为 token 可访问其他空间, 就跨出配置 workbench scope 探索.
- 集成测试也使用同一个 workbench scope.

输入线索:

- `datasheet_id`
- Vika URL
- 表名
- 空间名
- 文件夹路径
- 可选 `space_id`
- 用户自然语言描述

返回结构:

- `selected`: 置信度足够高时给出唯一表
- `candidates`: 多候选时给出小列表
- `need_user_choice`: 是否必须让用户二选一
- `match_basis`: 匹配依据
- `next_actions`: 下一步建议, 通常是 `schema` 或 `query/export`

行为规则:

1. 有 `datasheet_id` 或 URL 时, 先解析并校验目标是否属于配置 workbench scope.
2. folder workbench 必须配置 `VIKAMCP_VIKA__WORKBENCH_SPACE_ID`; 没有该值时返回明确配置错误, 禁止遍历 token 可见 spaces 推断.
3. 有表名时, 只在配置 workbench scope 内加载节点并匹配候选.
4. 候选唯一且置信度高, 直接 selected.
5. 候选多个, 禁止猜测, 返回候选让模型问用户.
6. 定位成功后, 默认下一步是 `schema`, 再决定 `query` 或 `export`.

## 10. 查询和导出边界

### 10.1 inline query

`query` 域只服务小结果:

- 默认 `page_size <= 50`.
- 硬上限 `page_size <= 100`.
- inline JSON 序列化后硬上限 `VIKAMCP_INLINE_MAX_CHARS=20000`; 超过则不返回 records, 改返回 export 建议和参数草案.
- 必须支持 `fields` 字段裁剪.
- 返回记录必须带 `has_more`, `next_page_token`, `total`.
- 超过 inline 字符数或记录数上限时, 拒绝返回全量, 并提示改用 export.

### 10.2 read_all 降级

`records.read_all` 不作为默认模型入口.

只允许作为内部 export 实现细节. 不允许在任何产品 profile 下通过 MCP `list_tools` 或 `vika_search_tools` 暴露给模型.

### 10.3 export artifact

新增 hidden 工具 `vika_export_records`. 不使用别名工具名, 避免模型和实现产生两套入口.

输入:

- `datasheet_id`
- `view_id`
- `formula`
- `fields`
- `sort`
- `format`: 默认 `csv`; 可显式选择 `jsonl`; 本阶段不暴露 `xlsx`
- `max_records`
- `max_pages`

返回:

- `artifact_id`
- `path`
- `format`
- `record_count`
- `field_names`
- `content_inline: false`
- `next_actions`: 后续调用 `vika_artifact_search`, `vika_artifact_read`, `vika_artifact_head`

artifact 文件固定写入:

```text
artifacts/
  exports/
    {artifact_id}.csv
    {artifact_id}.jsonl   # 仅在显式请求 jsonl 时生成
    {artifact_id}.manifest.json
```

manifest 至少包含:

- datasheet_id
- space_id
- view_id
- query/filter
- field list
- record count
- created_at
- source tool args hash

artifact 读取策略:

- `artifact_head`: 默认返回前 20 行, 硬上限 100 行.
- `artifact_search`: 搜索关键词、字段名、字段值, 默认返回 20 个命中, 硬上限 100 个命中, 每个片段硬上限 300 字符.
- `artifact_read`: 按 line range/window 读取, 默认最多 100 行, 硬上限 500 行, 总字符硬上限 40000.
- artifact 工具只能读取 `artifacts/exports/` 下由本服务创建的文件; 禁止任意路径读取.
- CSV 是默认格式, 用于 pandas/Excel 风格分析; JSONL 用于机器读取; XLSX 不在本阶段暴露.

## 11. 写入安全边界

写入采用两阶段:

1. preview
2. commit

不是逐条确认. 审批粒度是一次写入计划.

### 11.1 preview

模型调用写工具时默认只能 preview. preview 返回:

- `operation_id`
- `operation_type`
- `datasheet_id`
- `target_label`: 必填; 优先使用表名/路径, 无法取得时使用 `datasheet_id`
- `record_count`
- `validation_summary`
- `risk_level`
- `payload_hash`
- `expires_at`
- `confirmation_context`
- `confirmation_brief`
- `ask_user_instruction`

模型必须把 `confirmation_context` 和 `confirmation_brief` 当作事实源, 用一句自然语言向用户确认. 不得向用户展示原始 payload、样本记录、完整字段列表或调试结构:

```text
将向《客户跟进表》新增 238 条客户记录，属于批量写入操作。是否执行?
```

### 11.2 commit

commit 必须提供:

- `operation_id`
- `confirmed_payload_hash`: 必须等于 preview 返回的 `payload_hash`
- `confirmed_by_user`: 必须为 `true`
- `user_confirmation_summary`: 可选, 仅用于审计

服务端必须校验:

- operation 未过期.
- payload hash 未变化.
- 目标表未变化.
- 操作类型未变化.
- `confirmed_payload_hash` 与 operation 存储的 `payload_hash` 完全一致.
- 该 operation 未被 commit 过; commit 必须幂等, 重复提交同一 `operation_id` 返回同一结果或明确的 `already_committed`.

### 11.3 批量边界

- 同一表、同一操作类型、同一 payload hash 可以一次确认.
- 跨多个表必须拆成多个 operation.
- 批量删除、字段删除、表结构变更必须提高风险等级, 摘要必须明确影响范围.
- 直接 MCP 参数写入硬上限: 单次最多 500 条记录且序列化 payload 不超过 1 MB.
- 超过直接写入上限时, 必须走 staged payload artifact, preview 返回校验报告, 用户确认一次导入计划.
- preview operation 默认 TTL 为 15 分钟; 可配置但硬上限 60 分钟.

## 12. 模型操作手册

操作手册分三层.

### 12.1 `vika_guide`

固定返回短手册, 不依赖当前任务.

必须包含:

```text
默认流程:
1. 不知道 datasheet_id 时先调用 vika_resolve_datasheet.
2. 定位表后先获取 schema.
3. 只需要少量样本时用 query.
4. 需要大范围读取时用 export, 再 artifact_search/read.
5. 写入先 preview, 根据 confirmation_context/brief 用一句自然语言向用户确认, 再用 payload hash commit.
6. 不要调用 read_all 获取大表.
7. 不要猜 datasheet_id.
```

### 12.2 默认可见工具 description

description 必须是可执行指令, 不是一句短描述.

例如 `vika_call_tool`:

```text
Execute a hidden Vika tool by name after vika_describe_tool. Use this instead of waiting for the client tool list to refresh. Write-domain tools only create preview operations. Commit is a separate call that requires operation_id, confirmed_payload_hash, and confirmed_by_user=true after one-sentence user confirmation.
```

### 12.3 `vika_describe_tool`

返回:

- name
- domain
- description
- input_schema
- examples
- risk_level
- read/write/destructive 标记
- result_policy
- failure_recovery
- suggested_next_actions

## 13. 工具检索设计

第一版使用可解释检索, 不做向量.

索引字段:

- tool name
- domain
- tags
- aliases
- description
- schema property names
- 中文操作词
- 场景词

中文 alias 必须覆盖:

- 查找/搜索/定位 -> discovery/query
- 字段/列/表头 -> schema
- 视图 -> schema/query
- 导出/全量/批量读取 -> export
- 新增/写入/创建 -> write preview
- 更新/修改 -> write preview
- 删除 -> write preview high risk

`vika_search_tools` 返回小结果:

- top_k 默认 5, 硬上限 10.
- 每个候选只返回 name, domain, brief, risk, active/hidden, next_step.
- 不返回完整 schema; schema 由 `vika_describe_tool` 返回.

`vika_route_task` 返回步骤:

- 适合自然语言任务.
- 必须给出 recommended sequence.
- 不自动 commit 写操作.

## 14. 标准 MCP 实现边界

### 14.1 包改名

必须先把内部 `mcp/` 改名为 `runtime/`.

编辑点:

- `mcp/` -> `runtime/`
- `from .mcp...` -> `from .runtime...`
- `from ..mcp...` -> `from ..runtime...`
- `pyproject.toml` packages: `vika_mcp.runtime`
- tests 中所有 `vika_mcp.mcp` 引用同步修改

验收:

```powershell
python -c "from mcp.server.fastmcp import FastMCP; print(FastMCP)"
```

在仓库根目录必须导入官方 SDK, 而不是本地包.

### 14.2 新增依赖

在 `pyproject.toml` 和 `requirements.txt` 增加官方 MCP Python SDK:

```text
mcp==1.12.4
```

执行时先安装并验证该锁定版本. 如果包仓库中该版本不可用, 必须先更新本文档的锁定版本和验证记录, 再继续编码. 当前官方示例使用:

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Demo", json_response=True)
mcp.run(transport="streamable-http")
```

### 14.3 新入口

新增文件固定为:

- `standard_server.py`: 构建 FastMCP server.
- `runtime/build_registry.py`: 构建隐藏业务 registry.
- `runtime/meta_tools.py`: 注册默认可见元工具.
- `runtime/artifacts.py`: artifact 存储和读取.
- `runtime/write_plans.py`: preview/commit operation store.

`__main__.py` 改为:

```powershell
python -m vika_mcp --transport stdio
python -m vika_mcp --transport streamable-http --host 127.0.0.1 --port 8080
```

`streamable-http` 启动路径固定为 `/mcp`. `host/port/path` 的 SDK 注入方式必须按锁定 SDK 版本验证, 但对外 URL 不再漂移.

### 14.4 移除旧协议

删除:

- `routes.py`
- `runtime/executor.py` 的对外 job stream 角色
- `server.py` 中 FastAPI app 和 `/mcp/v1/*` 挂载
- README 中旧 HTTP API 说明

本轮不保留普通 HTTP health 路由. 运维 health 如后续需要, 必须另起文档决策, 且不得复用 MCP 工具执行入口.

## 15. AstrBot 配置目标

### 15.0 鉴权边界

鉴权分两层, 执行时不得混淆:

1. Vika API 鉴权: 上游维格表 API token, 必需. 通过 `VIKAMCP_VIKA__API_TOKEN` 提供, 不写入仓库文件, 不写入测试夹具, 不在日志输出明文 token.
2. MCP transport 鉴权: 保护 `streamable_http` MCP server 本身. `stdio` 不需要 transport 鉴权. `streamable_http` 默认只绑定 `127.0.0.1`; 如果绑定非 localhost, 必须配置独立的 `VIKAMCP_MCP_BEARER_TOKEN`, 并要求客户端使用 `Authorization: Bearer <token>`. 该 token 不能复用 Vika API token.

### 15.1 stdio

```json
{
  "mcpServers": {
    "vika": {
      "command": "python",
      "args": ["-m", "vika_mcp", "--transport", "stdio"],
      "env": {
        "VIKAMCP_VIKA__API_TOKEN": "your-token",
        "VIKAMCP_VIKA__WORKBENCH_URL": "https://vika.cn/workbench/fod6mElQf7PFD",
        "VIKAMCP_VIKA__WORKBENCH_SPACE_ID": "your-workbench-space-id",
        "VIKAMCP_TOOL_PROFILE": "search"
      }
    }
  }
}
```

### 15.2 streamable_http

```json
{
  "mcpServers": {
    "vika": {
      "url": "http://127.0.0.1:8080/mcp",
      "transport": "streamable_http",
      "headers": {
        "Authorization": "Bearer your-mcp-transport-token-if-enabled"
      }
    }
  }
}
```

不使用:

```text
/mcp/v1/tools
/mcp/v1/execute
/mcp/v1/stream/{job_id}
```

## 16. 执行顺序

### Phase 1: 消除 SDK 命名冲突

1. `mcp/` 改名为 `runtime/`.
2. 更新 imports 和 package metadata.
3. 增加官方 `mcp` dependency.
4. 验证官方 SDK import.
5. 跑现有测试, 先保证业务 registry 未破坏.

### Phase 2: 抽象工具定义

1. 新增 `ToolDefinition` 数据结构, 取代当前模型层使用的 `ToolSpec`; `ToolSpec` 只允许作为迁移前旧代码名, 不作为新协议概念继续扩展.
2. `ToolDefinition` 必须包含 domain/risk/exposure/result_policy/aliases/annotations.
3. 把当前 `tools/vika_tools.py` 注册的业务工具迁入 hidden registry.
4. 迁移 handler 实现到统一 registry, 不复制业务逻辑.

### Phase 3: 标准 MCP server

1. 新增 FastMCP server 构建.
2. 注册默认可见元工具.
3. 实现 `stdio` 启动.
4. 实现 `streamable_http` 启动.
5. 删除旧 `/mcp/v1/*` 对外入口.

### Phase 4: JSHook 式元工具

1. `vika_guide`
2. `vika_search_tools`
3. `vika_route_task`
4. `vika_describe_tool`
5. `vika_call_tool`
6. `vika_list_domains`
7. `vika_activate_domain`
8. `vika_resolve_datasheet`

验收重点:

- 默认 list_tools 不出现 30 个业务工具.
- `vika_call_tool` 能调用 hidden registry 中的只读工具.
- `vika_describe_tool` 能返回 hidden 工具 schema.
- 客户端不刷新工具列表也能完成 `describe -> call_tool`.

### Phase 5: 数据量控制和 artifact

1. 给 inline query 加默认和硬上限.
2. 将 `records.read_all` 移出默认模型路径.
3. 实现 export artifact.
4. 实现 artifact head/search/read/status.
5. 所有大结果工具必须返回 artifact 引用, 不返回全量 JSON.

### Phase 6: 写入 preview/commit

1. 为 create/update/delete 建立 write operation store.
2. preview 生成 `operation_id`, `payload_hash`, `confirmation_context`, `confirmation_brief`, `ask_user_instruction`.
3. commit 校验 operation/token/hash/TTL.
4. 批量写入按一次写入计划确认.
5. 删除和结构变更提高风险等级.

### Phase 7: AstrBot 实测

1. 用 stdio 配置接入 AstrBot.
2. 用 streamable_http 配置接入 AstrBot.
3. 检查 AstrBot 工具列表只显示稳定元工具.
4. 让模型完成:
   - 定位表
   - 获取 schema
   - 小样本查询
   - 大表导出后搜索
   - 写入 preview, 根据事实源向用户生成一句确认话术, 再用 payload hash commit

## 17. 测试计划

### 17.1 单元测试

- 官方 `mcp` SDK 不被本地包遮蔽.
- registry 可列出 hidden 和 visible 工具.
- `search` profile 默认只暴露元工具.
- 产品启动不支持 `full` profile 暴露业务工具.
- `vika_search_tools` top_k 有硬上限.
- `vika_describe_tool` 能描述 hidden 工具.
- `vika_call_tool` 校验参数并调用 hidden 工具.
- `records.query` 默认 page_size 和硬上限生效.
- inline 结果超过 20000 字符时不会返回全量 records.
- 超过 inline 上限时返回 export 建议.
- artifact manifest 正确生成.
- artifact search/read 有行数和字符数上限.
- artifact 工具拒绝读取 `artifacts/exports/` 外路径.
- write preview 生成稳定 payload hash.
- write commit 拒绝过期、hash 变化、目标表变化、`confirmed_payload_hash` 不一致的 operation.

### 17.2 协议测试

- stdio: initialize -> list_tools -> call `vika_guide`.
- stdio: `resolve -> describe -> call_tool`.
- streamable_http: initialize -> list_tools -> call `vika_guide`.
- streamable_http: export -> artifact_search -> artifact_read.
- integration opt-in: 使用 `VIKAMCP_VIKA__WORKBENCH_URL`, `VIKAMCP_VIKA__WORKBENCH_SPACE_ID` 和环境变量 token 完成 resolve/schema/query/export.
- integration writes opt-in: 只在 `_vika_mcp_integration_test` 中 preview/commit/cleanup 本次 run id 记录.

### 17.3 AstrBot smoke

- AstrBot 能启动 MCP server.
- AstrBot `MCPTool` 中只出现默认可见工具.
- `tool_schema_mode=full` 可完成主路径.
- `skills_like` 可完成主路径或至少不会因为缺 schema 卡死.
- 大表导出不会把全量记录塞入 tool result.

### 17.4 真实 Vika 集成测试

真实集成测试允许执行, 但必须显式 opt-in, 并且不得把 token 写入仓库.

必需环境变量:

- `VIKAMCP_VIKA__API_TOKEN`: Vika API token.
- `VIKAMCP_VIKA__WORKBENCH_URL`: 目标 workbench URL, 当前目标为 `https://vika.cn/workbench/fod6mElQf7PFD`.
- `VIKAMCP_VIKA__WORKBENCH_SPACE_ID`: 目标 folder workbench 所属 space id; 当前测试环境为 `spcBxkW6UiuzT`.
- `VIKAMCP_INTEGRATION=1`: 显式开启真实集成测试.

写入测试额外要求:

- `VIKAMCP_INTEGRATION_ALLOW_WRITES=1`: 显式允许真实写入.
- 写入测试只能操作专用测试表, 默认表名固定为 `_vika_mcp_integration_test`.
- 如果专用测试表不存在且当前 token 允许创建表, 测试可以创建该表.
- 测试记录必须带 `vika_mcp_test_run_id` 字段或等价唯一 run id 字段.
- 清理只能删除本次 run id 创建的记录; 不删除非测试记录, 不删除非测试表.
- 如果无法创建或定位专用测试表, 写入 commit 集成测试必须 skip, 但 preview 单元测试仍必须覆盖.

## 18. 验收标准

改造完成必须满足:

1. `python -m pytest -q` 通过.
2. `python -m vika_mcp --transport stdio` 可被 MCP client initialize.
3. `python -m vika_mcp --transport streamable-http` 可被 MCP client initialize.
4. `list_tools` 默认只返回稳定元工具和必要高层工具.
5. 模型无需看到全部业务工具, 也能通过 `search/describe/call_tool` 调用 hidden 工具.
6. 给定表名或 URL, `vika_resolve_datasheet` 能返回 selected 或候选列表, 不胡猜.
7. 小查询 inline 有硬上限.
8. Workbench scope 检查 `datasheet_id`, `space_id`, `node_id`, 和 `folder_id`.
9. 所有 write-capable hidden tools 都有 `domain=write`.
10. 大表读取走 artifact.
11. Export 要求 `max_records`, 硬上限 100000, 默认 CSV, 并在 manifest 记录 artifact format.
12. `ArtifactStore` 和 `WritePlanStore` 都是 runtime-owned services, 不由单个 tool 临时创建或模块全局共享.
13. 写入只能先 preview; commit 必须绑定同一个 operation, 且 `confirmed_payload_hash` 与 preview `payload_hash` 完全匹配.
14. README 不再宣传 `/mcp/v1/*` 作为 MCP API.
15. 真实集成测试不会在仓库、日志或 artifact manifest 中泄露 Vika API token.

## 19. 风险和处理

| 风险 | 处理 |
| --- | --- |
| 官方 SDK 被本地 `mcp/` 遮蔽 | 第一阶段改名, 并加 import 测试 |
| 模型不知道怎么用元工具 | 三层手册: guide, description, describe_tool |
| 动态激活后客户端不刷新工具列表 | 主路径使用 `vika_call_tool` |
| catalog 空导致表定位失败 | `resolve_datasheet` 可受限 refresh, 多候选时问用户 |
| 大表结果爆上下文 | query 硬上限 + export artifact |
| 批量写入确认太繁琐 | 按一次写入计划确认, 不逐条确认 |
| 写入计划被篡改 | payload hash + TTL + operation_id 校验 |
| `full` profile 诱导工具爆炸 | 产品运行不提供 `full` profile; hidden registry 只能通过元工具访问 |
| Vika API token 泄露 | token 只通过环境变量注入, 日志和 manifest 必须脱敏 |

## 20. 后续文档更新

实现完成后更新:

- `README.md`: 标准 MCP 启动方式, AstrBot 配置示例.
- `docs/astrbot-usage.md`: AstrBot 接入和模型工作流.
- `docs/tool-guide.md`: 模型可见工具和 hidden tool catalog 说明.
- `docs/artifacts.md`: export/artifact 文件格式和读取规则.
- `docs/write-safety.md`: preview/commit 写入安全规则.

## 21. 执行防漂移闭环

以下事项已经闭环, 执行时不得重新开分支:

- 协议: 只实现标准 MCP `stdio` 和 `streamable_http`; 不保留 `/mcp/v1/*`.
- 包名: 内部 `mcp/` 固定改名为 `runtime/`.
- profile: 产品运行只提供 `search`; 不提供用户可配置 `full`.
- 默认工具面: MCP `list_tools` 默认只出现稳定元工具和必要高层工具.
- 业务调用: hidden 业务工具只能经 `vika_call_tool` 调用.
- 动态激活: `vika_activate_domain` 不动态注册业务工具, 只设置会话 domain scope.
- 表定位: 指定表入口固定为 `vika_resolve_datasheet`.
- Vika 作用域: 所有发现、查询、导出、写入都必须受 `VIKAMCP_VIKA__WORKBENCH_URL` 和 `VIKAMCP_VIKA__WORKBENCH_SPACE_ID` 限制.
- 大表读取: 默认走 `vika_export_records` 和 artifact 工具; `records.read_all` 只允许作为内部实现细节.
- artifact 格式: 默认 `csv`, 可显式 `jsonl`; 本阶段不做 `xlsx`.
- 写入确认: 按一次写入计划确认, commit 使用 `operation_id + confirmed_payload_hash + confirmed_by_user`.
- health: 本轮不新增普通 HTTP health 路由.

执行中只允许因为以下原因更新本文档:

- 官方 MCP Python SDK 的锁定版本要求不同启动 API, 但对外 CLI 和 AstrBot 配置目标不变.
- `astral_vika` 实际 API 限制要求调整单次批量上限, 但仍必须保留 preview/commit、artifact、大输出硬上限.
- AstrBot 实测发现 `skills_like` 或 `streamable_http` 行为与当前代码不一致, 需要补充验证步骤, 但不能恢复旧 `/mcp/v1/*` 双轨.

除以上情况外, 执行者应直接修改代码和测试, 不再回到产品边界讨论.
