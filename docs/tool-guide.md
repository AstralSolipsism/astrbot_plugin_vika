# Tool Guide

Default model flow:

1. Call `vika_guide` when unsure.
2. Call `vika_resolve_datasheet` before any table-scoped hidden tool.
3. Call `vika_search_tools` or `vika_route_task` to find the next hidden tool.
4. Call `vika_describe_tool` for schema, examples, risk, and result policy.
5. Call `vika_call_tool` with validated arguments.
6. Use bounded CSV export through `vika_export_records` for large reads, then artifact tools or execution-agent analysis such as pandas.
7. For writes, call the write tool for preview, use `confirmation_context` and `confirmation_brief` to ask the user one concise natural-language confirmation question, then call `vika.write.commit` with `operation_id`, `confirmed_payload_hash`, and `confirmed_by_user=true` only after the user confirms.

Rules:

- All hidden tools are still called through `vika_call_tool`.
- When workbench scope is configured, every hidden call is checked against that scope, including `datasheet_id`, `space_id`, `node_id`, and `folder_id`.
- `vika_export_records` requires `max_records`; use a filter/formula and bounded CSV export, then inspect with artifact tools or let an execution agent analyze the CSV with pandas.
- Write tools only preview; commit requires `operation_id`, `confirmed_payload_hash`, and `confirmed_by_user=true`.
- Do not guess a `datasheet_id`.
- Do not call `vika.records.read_all` directly; it is an internal export detail.
- Do not expect MCP `list_tools` to expose business tools.
- Do not rely on AstrBot result overflow handling for large Vika tables.
- Do not assume AstrBot implements artifact search/read; the MCP provides artifact tools, and execution agents may additionally analyze CSV artifacts with code.
- Do not show raw payload, sample records, complete field lists, or debug-shaped preview JSON as the user confirmation message.
