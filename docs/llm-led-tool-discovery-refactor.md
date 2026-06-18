# LLM 主导工具发现架构修正专项文档

## 1. 目标

本专项修正 `vika_search_tools` / `vika_route_task` 的职责错位问题。

目标不是继续修正则、补关键词、扩业务词表，而是把工具发现架构改成:

- LLM 负责理解用户自然语言、识别业务对象、抽取表名/业务名/筛选意图.
- MCP 负责暴露工具能力目录、参数契约、风险边界、执行流程和安全校验.
- `vika_search_tools` 只检索 MCP 工具能力, 不解释用户业务语义.
- `vika_route_task` 保留为结构化 workflow 编排工具, 不能继续做自然语言解析器.

完成后, 用户说 `查询员工目录`、`导出线下门店`、`更新隐患记录` 时, LLM 自己理解:

- `datasheet_query = "员工目录"` / `"线下门店"` / `"隐患记录"`
- 操作类别是 query/export/update
- 先调用 `vika_resolve_datasheet(query=...)`
- 再通过能力索引找到 `vika.records.query` / `vika_export_records` / `vika.records.update`

MCP 不再尝试用正则判断 `目录` 是系统目录还是业务表名, 也不再清洗 `线下` 这种业务词.

## 2. 当前问题

当前实现把 MCP 做成了半个自然语言理解器:

- `runtime/meta_tools.py` 中有 `_classify_task_intent`, `_record_action_match`, `_subject_hint_after_action`, `_clean_subject_hint`, `_system_object_kind`, `_is_catalog_discovery_intent`.
- `route_task("查询员工目录")` 可能因为裸 `目录` 被判成 catalog discovery, 而不是查询业务表.
- `route_task("查询线下")` 会把 `下` 当语气词删掉, 生成错误的 `subject_hint="线"`.
- 文档中仍要求 route/search 返回 `subject_hint` / `datasheet_query`, 这会继续诱导 agent 在 MCP 内部修自然语言解析.

这些不是孤立 bug, 而是架构边界错误:

- MCP 不知道用户业务域, 不能可靠判断任意中文业务词.
- 越补正则, 误伤越多.
- LLM 本来就具备语义理解能力, MCP 内部重复做弱 NLU 反而降低可靠性.

## 3. 统一职责边界

### 3.1 LLM 职责

LLM 必须负责:

- 理解用户自然语言任务.
- 抽取业务对象或表名, 例如 `员工目录`, `资产目录`, `线下门店`, `客户跟进表`.
- 判断高层操作类型, 例如查询、导出、新增、更新、删除、查看字段、上传附件.
- 将业务对象原样传给 `vika_resolve_datasheet(query=...)`.
- 根据 MCP 返回的工具能力目录选择具体 hidden tool.
- 写入前用 preview 的 `confirmation_context` / `confirmation_brief` 向用户一句话确认, commit 时传 hash.

LLM 不应期待 MCP 替它理解用户业务领域.

### 3.2 MCP 职责

MCP 必须负责:

- 给出稳定、明确、可执行的操作手册.
- 提供表定位工具 `vika_resolve_datasheet`.
- 提供能力索引 `vika_search_tools`.
- 提供工具详情 `vika_describe_tool`.
- 提供统一代理执行 `vika_call_tool`.
- 对 catalog readiness、workbench scope、写入确认、artifact 输出做硬边界校验.

MCP 不负责:

- 从自然语言里抽取业务表名.
- 判断业务词是否属于系统对象.
- 清洗用户表名或业务对象名.
- 用业务名词词典覆盖用户领域.

## 4. `vika_search_tools` 新契约

`vika_search_tools` 是工具能力检索, 不是用户任务解析器.

### 4.1 输入语义

固定输入结构:

```json
{
  "domain": "query | export | schema | write | discovery | attachment | guide",
  "capability": "records.query | records.export | records.create | records.update | records.delete | schema.get | fields.get | views.get | write.commit",
  "query": "可省略的 capability keyword; 绝不是用户业务对象",
  "top_k": 5
}
```

`query` 保留, 但语义固定为 capability query:

- 合法: `records query`, `query records`, `导出记录`, `schema fields`, `write commit`.
- 非 capability query: `查询员工目录`, `导出线下门店`, `更新隐患记录`.
- 对纯业务词或自然语言用户任务: `员工目录`, `线下门店`, `客户`, `订单`, `查询员工目录`, 必须返回空候选和简短 `guidance`, 提示 LLM 自行抽取业务对象并先调用 `vika_resolve_datasheet(query=...)`; 不得猜业务工具.
- 至少应提供 `domain`、`capability`、`query` 三者之一. 三者都为空时返回空候选和 guide 提示, 不默认枚举全部 hidden tools.

Schema 要求:

- `domain`, `capability`, `query` 均可省略.
- `top_k` 可省略, 默认 5, 硬上限 10.
- `capability` 必须是稳定能力 id, 不得接受业务对象词.
- 当 `capability` 存在时, 以 `capability` 为主匹配; `query` 只作为补充 capability keyword.

### 4.2 检索范围

检索只基于:

- tool name
- domain
- capability id
- stable tags
- schema property names
- stable capability aliases

不得基于:

- 用户业务名词.
- 自然语言 task 拆分.
- subject hint.
- 正则识别的业务对象.

### 4.3 输出语义

输出应只包含工具候选和下一步:

```json
{
  "candidates": [
    {
      "name": "vika.records.query",
      "domain": "query",
      "brief": "...",
      "risk": "low",
      "hidden": true,
      "next_step": "Call vika_describe_tool with tool_name='vika.records.query'."
    }
  ]
}
```

当没有候选时, 输出应为:

```json
{
  "candidates": [],
  "guidance": "Search is capability-only. Extract the business table name yourself, call vika_resolve_datasheet(query=...), then search with a capability such as records.query."
}
```

不得输出:

- `subject_hint`
- `datasheet_query`
- 被 MCP 推断出的业务对象

## 5. `vika_route_task` 新契约

`vika_route_task` 已决策保留, 但必须把它从自然语言 route 改成结构化 workflow planner.

固定输入结构:

```json
{
  "task_kind": "record_query | record_export | record_create | record_update | record_delete | schema_read | attachment_upload | write_commit",
  "datasheet_query": "可省略; LLM 抽取的业务表名或业务对象; 原样透传",
  "datasheet_id": "可省略; 已解析的数据表 id",
  "has_user_confirmation": false
}
```

关键原则:

- `task_kind` 由 LLM 根据用户自然语言填写.
- `datasheet_query` 由 LLM 原样抽取, MCP 不修改.
- `route_task` 只根据结构化 `task_kind` 返回固定流程.
- 如果没有 `datasheet_id`, 返回流程必须先 `vika_resolve_datasheet(query=datasheet_query)`.
- 写入流程只能推荐 preview + user confirmation + commit, 不自动 commit.

Schema 要求:

- `task_kind` 必填.
- `datasheet_query` 和 `datasheet_id` 均可省略.
- 对 `record_query`, `record_export`, `record_create`, `record_update`, `record_delete`, `schema_read`, `attachment_upload`, 如果 `datasheet_id` 与 `datasheet_query` 都缺失, 返回结构化错误 `datasheet_target_required`, 并提示 LLM 先从用户请求中抽取业务表名或要求用户提供表 URL / dst.
- 对 `write_commit`, 不需要 `datasheet_query` 或 `datasheet_id`; route 只返回 commit 描述/调用流程, 且仍不自动 commit.
- 不接受 `task` 字段. 如果入参包含 `task`, 返回 `unsupported_natural_language_route_input`, 不兼容旧自由文本入口.

固定映射:

| `task_kind` | recommended hidden tool | domain | write flow |
| --- | --- | --- | --- |
| `record_query` | `vika.records.query` | `query` | no |
| `record_export` | `vika_export_records` | `export` | no |
| `record_create` | `vika.records.create` | `write` | preview + user confirmation + `vika.write.commit` |
| `record_update` | `vika.records.update` | `write` | preview + user confirmation + `vika.write.commit` |
| `record_delete` | `vika.records.delete` | `write` | preview + user confirmation + `vika.write.commit` |
| `schema_read` | `vika.schema.get` | `schema` | no |
| `attachment_upload` | `vika.attachments.upload` | `write` | preview + user confirmation + `vika.write.commit` |
| `write_commit` | `vika.write.commit` | `write` | commit only after user confirmation fields are supplied to `vika_call_tool` |

示例:

输入:

```json
{
  "task_kind": "record_query",
  "datasheet_query": "员工目录"
}
```

输出:

```json
{
  "recommended_sequence": [
    "vika_resolve_datasheet(query='员工目录')",
    "vika_search_tools(domain='query', capability='records.query')",
    "vika_describe_tool(tool_name='vika.records.query')",
    "vika_call_tool(tool_name='vika.records.query', arguments={...})"
  ],
  "recommended_tools": [
    {
      "tool_name": "vika.records.query",
      "domain": "query",
      "role": "read"
    }
  ],
  "auto_commits_write": false
}
```

不得再支持:

- MCP 自己解析 `task="查询员工目录"`.
- MCP 自己生成 `subject_hint`.
- MCP 自己清洗 `datasheet_query`.

## 6. 指南与 LLM 操作手册改造

`vika_guide`, `docs/tool-guide.md`, `standard_server.py` instructions 必须明确告诉 LLM:

1. 你负责理解用户任务.
2. 你负责抽取业务表名或业务对象.
3. MCP 不理解用户业务域, 不会替你解析自然语言表名.
4. 不知道 datasheet_id 时, 先调用:

```text
vika_resolve_datasheet(query="<你从用户请求中抽取的业务表名或业务对象>")
```

5. 需要找工具时, 用 capability 词检索:

```text
vika_search_tools(domain="query", capability="records.query")
vika_search_tools(domain="export", capability="records.export")
vika_search_tools(domain="write", capability="records.update")
```

6. 如果用户给的是 URL / dst / view, 优先直接传给 resolver 或对应工具, 不让 search 参与语义理解.

## 7. 代码改造边界

### 7.1 必须删除或重写

从 `runtime/meta_tools.py` 删除:

- `_TaskIntent`
- `_classify_task_intent`
- `_record_action_match`
- `_subject_hint_after_action`
- `_clean_subject_hint`
- `_system_object_kind`
- `_is_catalog_discovery_intent`

从 `search_tools` 删除:

- task intent classifier 调用.
- `subject_hint` / `datasheet_query` 输出.
- 基于自然语言动作 + 对象组合的准入逻辑.

从 `route_task` 删除:

- 对自由文本 `task` 的业务语义解析.
- 由 MCP 生成 `subject_hint`.
- 对 `搜索目录` / `获取目录项` 这类自然语言的特殊 fallback.

`TOOL_INTENTS` 必须改名为 capability metadata:

- 固定命名: `TOOL_CAPABILITIES`.
- 只保留稳定 capability aliases.
- 不包含业务名词.
- 不承担自然语言任务解析.

### 7.2 不应触碰

本专项不修改:

- catalog readiness 可信状态架构.
- workbench scope 校验协议.
- write preview/commit hash 协议.
- export artifact 协议.
- transport auth.
- Vika API client 行为.

如果执行中发现这些模块仍有 bug, 只能记录为独立 review 问题, 不混入本专项.

## 8. 测试改造

删除或重写这些旧方向测试:

- `查询客户` / `查询订单` 直接命中 `vika.records.query`.
- `route_task` 自动抽取 `subject_hint`.
- `route_task("搜索目录")` 之类自然语言特殊 fallback.
- `TOOL_INTENTS` 业务名词扫描作为核心验收.

新增测试:

### 8.1 search 是能力检索

- `vika_search_tools(domain="query", capability="records.query")` 返回 `vika.records.query`.
- `vika_search_tools(domain="export", capability="records.export")` 返回 `vika_export_records`.
- `vika_search_tools(domain="write", capability="records.update")` 返回 `vika.records.update`.
- `vika_search_tools(query="records query")` 返回 `vika.records.query`.
- `vika_search_tools(query="员工目录")` 不返回 `vika.records.query`.
- `vika_search_tools(query="查询员工目录")` 返回空候选和 capability-only guidance; LLM 应先解析业务对象并用 capability search.

### 8.2 route 是结构化 workflow

- `route_task(task_kind="record_query", datasheet_query="员工目录")` 原样返回 resolver query `员工目录`.
- `route_task(task_kind="record_export", datasheet_query="线下")` 原样返回 resolver query `线下`.
- `route_task(task_kind="record_update", datasheet_query="隐患记录")` 返回 preview + confirmation + commit 流程.
- 不存在任何对 `datasheet_query` 的中文清洗.

### 8.3 LLM 指南足够明确

- `vika_guide` 必须包含: LLM 自行抽取业务表名/业务对象.
- `vika_guide` 必须包含: search 只检索 capability, 不解析业务自然语言.
- `standard_server.instructions` 不得声称 route/search 会理解用户业务语义.

## 9. 用户体验变化

改造前:

- 用户说 `查询员工目录`, MCP 可能把 `目录` 当系统 catalog.
- 用户说 `查询线下`, MCP 可能改成 `线`.
- 继续补正则仍会引入新的误伤.

改造后:

- LLM 保留用户业务词原文.
- MCP 不再改写业务对象.
- 工具检索结果更稳定、可解释.
- 失败边界更清楚: 如果 LLM 没抽取好表名, 是 LLM 任务理解问题; 如果 resolver 找不到表, 是 catalog/表定位问题; 如果工具调用失败, 是工具契约或参数问题.

## 10. 已确认决策

### D1: 保留 `vika_route_task`, 改为结构化 workflow planner

结论: 保留 `vika_route_task`, 但删除自由文本自然语言解析能力, 改为只接受 LLM 已理解后的结构化输入.

理由:

- 保留它可以继续给 LLM 稳定步骤模板.
- 但必须删除自由文本自然语言解析.
- 输入 schema 改为 `task_kind` / `datasheet_query` / `datasheet_id`.
- 当前处于开发期, 不保留旧 `task` 兼容入口.

### D2: 保留 `vika_search_tools.query`, 固定为 capability query

结论: 保留 `query`, 但它只能表示 capability query, 不是 user task.

理由:

- JSHook 风格 search tool 仍需要关键词检索能力.
- LLM 可搜索 `records query`, `export records`, `write commit`.
- 只要文档和 schema 说清楚 `query` 不是业务自然语言, 就不会继续漂移.

### D3: 支持中文 capability alias, 但只支持稳定能力短语

结论: 支持稳定中文能力短语, 不支持业务短语.

允许:

- `查询记录`
- `导出记录`
- `新增记录`
- `提交写入`
- `字段`
- `视图`

禁止:

- `查询客户`
- `导出订单`
- `员工目录`
- `线下门店`

这些业务词必须由 LLM 传给 resolver.

## 11. 执行顺序

1. 先改测试, 删除自然语言业务解析预期.
2. 改 visible meta tool schema:
   - `vika_search_tools`: capability search.
   - `vika_route_task`: 结构化 workflow planner.
3. 删除 `runtime/meta_tools.py` 中自然语言 parser.
4. 收敛 `tools/vika_tools.py` 中 `TOOL_INTENTS` 为 capability metadata.
5. 更新 `vika_guide`, `standard_server.instructions`, `docs/tool-guide.md`, `docs/standard-mcp-refactor-plan.md`.
6. 运行:

```powershell
python -m pytest tests/test_standard_mcp_surface.py -q
python -m pytest tests/test_catalog_cache_discovery.py -q
python -m pytest -q
git diff --check
```

7. 扫描:

```powershell
rg -n "subject_hint|datasheet_query|_classify_task_intent|_clean_subject_hint|_is_catalog_discovery_intent" runtime tools docs tests -S
```

允许命中只应存在于:

- 新文档中说明旧机制被删除.
- 测试中断言旧字段不存在.

## 12. 完成标准

只有同时满足以下条件才算完成:

- MCP 内部不再解析用户业务自然语言.
- `search_tools` 只返回工具能力候选.
- `route_task` 不再接受或解析自由文本业务任务; 必须是结构化 workflow planner.
- LLM 操作手册明确要求 LLM 自行抽取业务表名并传给 resolver.
- 不再出现 `目录` / `线下` 这类业务词被 MCP 误判或改写的问题.
- 不引入 catalog/write/export/transport 的并行协议或兼容分叉.
