# Tool Guide

Default model flow:

1. Call `vika_guide` when unsure.
2. The LLM must understand the user request and extract the business table name or business object itself.
3. Call `vika_resolve_datasheet(query="<LLM extracted business table name>")` before any table-scoped hidden tool, unless the user already provided a URL or `dst...` id.
4. If resolver reports `catalog_not_ready`, `catalog_stale`, `refreshing`, `refresh_abandoned`, or `failed`, stop and ask an operator to refresh the catalog through the maintenance surface; do not trigger refresh from the model flow.
5. Use `vika_route_task` only as a structured workflow planner with `task_kind` plus `datasheet_query` or `datasheet_id`; do not pass free-text user tasks.
6. Use `vika_search_tools` as capability-only search, for example `domain="query", capability="records.query"` or `domain="export", capability="records.export"`.
7. Call `vika_describe_tool` for schema, examples, risk, and result policy.
8. Call `vika_call_tool` with validated arguments.
9. Use bounded CSV export through `vika_export_records` for large reads, then artifact tools or execution-agent analysis such as pandas.
10. For writes, call the write tool for preview, use `confirmation_context` and `confirmation_brief` to ask the user one concise natural-language confirmation question, then call `vika.write.commit` with `operation_id`, `confirmed_payload_hash`, and `confirmed_by_user=true` only after the user confirms.

Rules:

- All hidden tools are still called through `vika_call_tool`.
- MCP does not parse, clean, or guess user business natural language. The LLM owns that semantic step.
- `vika_search_tools` only searches stable tool capabilities. Valid examples are `records.query`, `records.export`, `records.update`, `schema.get`, `fields.get`, `views.get`, and `write.commit`.
- Do not pass full user tasks such as `查询<业务表名>`, `导出<业务表名>`, or `更新<业务表名>` to `vika_search_tools`. Extract the table/business object first, resolve it, then search by capability.
- `vika_route_task` rejects old free-text `task` input. Provide `task_kind` values such as `record_query`, `record_export`, `record_update`, `schema_read`, or `write_commit`.
- When workbench scope is configured, every hidden call is checked against that scope, including `datasheet_id`, `space_id`, `node_id`, and `folder_id`.
- Datasheet discovery is cache-only. The model must not call catalog refresh/clear or live node/space enumeration to find tables.
- Catalog content readers return nodes, matches, or items only after the unified selector readiness gate is ready. Namespace-wide catalog search/get is strict: any scoped refresh failure, active refresh, or abandoned refresh blocks content and should be narrowed with `space_id` or retried after maintenance refresh.
- Catalog refresh/clear are maintenance operations for an operator, CLI, or background runtime, not normal LLM task tools.
- Catalog refresh is bounded to one configured space. It must never infer scope by scanning token-visible spaces, and failed required refresh requests preserve the previous cache.
- Write previews require fresh catalog scope evidence; missing or stale catalog state blocks writes.
- `vika_export_records` requires `max_records`; use a filter/formula and bounded CSV export, then inspect with artifact tools or let an execution agent analyze the CSV with pandas.
- Write tools only preview; commit requires `operation_id`, `confirmed_payload_hash`, and `confirmed_by_user=true`.
- `vika.attachments.upload` accepts any local `file_path`, but preview must show the file path, name, size, and SHA-256 before commit.
- `vika.attachments.download` accepts only `url`; it never accepts `save_path` and returns a binary artifact reference instead of writing to an arbitrary path.
- Do not guess a `datasheet_id`.
- Do not call `vika.records.read_all` directly; it is an internal export detail.
- Do not expect MCP `list_tools` to expose business tools.
- Do not rely on AstrBot result overflow handling for large Vika tables.
- Do not assume AstrBot implements artifact search/read; the MCP provides artifact tools, and execution agents may additionally analyze CSV artifacts with code.
- Do not show raw payload, sample records, complete field lists, or debug-shaped preview JSON as the user confirmation message.
