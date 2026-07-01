# Cache-First Catalog Discovery Execution Spec

This is the execution source of truth for the current cache-first catalog/discovery stage.
Coding agents must follow this document before using older planning notes. Older documents are
historical references when they conflict with this spec.

## Goal

Make Vika MCP discovery predictable in large production spaces by separating two responsibilities:

- Model-facing discovery reads the persisted catalog/cache only.
- Heavy space-node refresh belongs to maintenance/admin/CLI or background runtime work only.

The model must never trigger a full space-node scan while resolving a table, checking workbench
scope, querying records, exporting records, or preparing writes.

## Architectural Decision

Use one unified architecture:

1. Keep the heavy folder/datasheet index.
2. Persist it in the SQLite catalog.
3. Expose only cache-backed discovery and status to the LLM path.
4. Move refresh/clear into a maintenance surface that is not searchable or callable by the LLM.

Do not implement a parallel mode where the LLM sometimes explores Vika nodes through live API calls.
That creates unpredictable latency and weakens scope enforcement.

## Non-Negotiable Boundaries

- `vika_resolve_datasheet` is cache-only.
- Workbench scope membership checks are cache-only.
- Model-visible catalog readers are cache-only.
- Query/export/write target resolution must not refresh catalog.
- `vika.nodes.list`, `vika.nodes.search`, `vika.nodes.tree`, and token-wide catalog tools are not
  normal model exploration tools.
- `vika.catalog.refresh` and `vika.catalog.clear` are maintenance operations, not LLM task tools.
- Records are not stored in catalog. Large record data continues to use bounded query or export
  artifacts.
- This stage does not add XLSX export.
- Do not restore old MCP endpoints, old write-confirmation protocols, or compatibility double paths.

## Catalog Data Contract

The catalog is the durable discovery substrate. It stores:

- spaces
- nodes
- datasheets
- optional fields/views cached on demand for known datasheets
- refresh metadata

Default refresh scope for the space index is `Folder` plus `Datasheet`. `Form` and `Dashboard` are
not part of the default index. Schema fields/views are not refreshed for every datasheet during
space refresh; they are fetched on demand for a selected datasheet.

Each cache reader must return enough freshness data for a model or client to judge reliability,
but maintenance health and model readiness must not be collapsed into one status field:

- `health_status`: maintenance diagnostic for the selected namespace/scope.
- `ready_for_discovery`: whether cache-only table discovery may return content.
- `discovery_status`: readiness status for node/datasheet discovery rows.
- `discovery_error`: structured error when `ready_for_discovery=false`.
- `selector_status`: readiness status for `catalog_search/get` selectors.
- `generation_id`
- `fresh`
- `updated_at` or equivalent newest timestamp
- `ttl_seconds`
- `source: "cache"`

Health/readiness status values must distinguish:

- `empty`: no usable rows for the relevant readiness selector.
- `ready`: the relevant readiness selector has fresh usable rows.
- `stale`: at least one relevant row is older than TTL or has missing/invalid timestamp.
- `refreshing`: a maintenance refresh is in progress.
- `refresh_abandoned`: a previous refresh stayed in progress beyond the timeout and is treated as failed maintenance state.
- `failed`: last refresh failed; include error details.

`health_status=ready` only means cached rows are fresh for diagnostics. It does not imply the
model may discover tables. Model-facing discovery must use `ready_for_discovery=true` or a
ready `DiscoveryReadiness` result.

Refresh metadata must include:

- `last_refresh_started_at`
- `last_refresh_finished_at`
- `last_refresh_duration_seconds`
- `last_refresh_error`
- `last_refresh_counts`

Refresh lifecycle metadata is scoped to the same identity as the maintained space index:
`(namespace, space_id)`. A failed, refreshing, or abandoned refresh for one space must not change
`ready_for_discovery` for another space with fresh node/datasheet rows. Namespace-wide status is
diagnostic only when no `space_id` is requested; model-facing discovery and workbench scope checks
must use the selected space status.
- `generation_id`
- `db_path`
- `ttl_seconds`

## Catalog Trust Contract

This section is the authoritative contract for catalog state trust. Do not implement a second
readiness policy in a tool, scope checker, resolver, or client wrapper.

The only state that may return catalog content to the model path is `ready`. These states must
return structured catalog errors and no `nodes`, `matches`, `item`, or scope membership result:

- `empty`
- `stale`
- `refreshing`
- `refresh_abandoned`
- `failed`
- `disabled`

All catalog content readers must go through one readiness gate. The gate has three inputs:

- `CatalogSelector`: namespace plus optional `space_id`, `dst_id`, item types, and readiness type.
- candidate rows for that selector.
- scoped refresh lifecycle state for the selector.

The gate has only two outputs:

- ready: `{"ready": true, "catalog": ...}` plus the caller's bounded content.
- blocked: `{"ready": false, "error": ...}` with a `catalog_*` error code and no content.

Callers must not interpret raw `catalog_status`, `refresh_state`, or timestamps themselves. They may
only format or propagate the gate result.

### Selector Scope Rules

| Selector | Refresh state checked | Content returned when |
| --- | --- | --- |
| workbench discovery | configured `workbench_space_id` | selected space discovery rows are fresh and scoped refresh state is not failed/refreshing/abandoned |
| explicit space discovery | requested `space_id` | selected space discovery rows are fresh and scoped refresh state is not failed/refreshing/abandoned |
| namespace discovery/search | every scoped refresh state in the namespace plus every space represented by candidate rows | all relevant scoped states are non-blocking and candidate rows are fresh |
| namespace status discovery readiness | the same discovery selector gate as namespace discovery/search | `ready_for_discovery=true` only when the namespace discovery gate is ready; otherwise `discovery_error` must match the gate error |
| datasheet/node get | item space, or all scoped states if item is missing and no narrower selector exists | selector rows are fresh and scoped state is non-blocking |
| field/view get | rows sharing the same `dst_id`; refresh states for spaces represented by those rows | all field/view rows for the datasheet selector are fresh and scoped states are non-blocking |
| workbench scope catalog metadata | configured `workbench_space_id` | accepted only when canonical ready is true: `ready_for_discovery=true`, `catalog_status=ready`, and any `readiness_status`/`discovery_status` values are also `ready` |
| maintenance status | requested diagnostic scope | may report health for diagnosis; it does not authorize content return unless the same selector gate is ready |
| maintenance refresh/clear | explicit maintenance target only | may mutate cache state; never runs from the model hot path |

Namespace-wide content lookup is intentionally strict. If any scoped refresh state in the namespace
is `failed`, `refreshing`, or `refresh_abandoned`, namespace-wide search/get cannot prove a complete
trusted result and must return the corresponding catalog error. The caller should retry with an
explicit `space_id` or wait for maintenance refresh to make the target space ready. Namespace-level
diagnostic refresh state with no `space_id` is not a content selector and must not block scoped
content selectors by itself.

### Entrypoint Matrix

| Entrypoint | Path type | Allowed behavior |
| --- | --- | --- |
| `vika_resolve_datasheet` | model hot path | cache-only; returns selected/candidates only after workbench discovery gate is ready |
| `vika.nodes.list(cache_only=true)` | cache-only hidden discovery | returns `nodes` only after explicit space discovery gate is ready |
| `vika.catalog.search` | cache-only hidden selector | returns `matches` only after selector gate is ready; namespace search is all-scoped-state strict |
| `vika.catalog.get` | cache-only hidden selector | returns `item` only after selector gate is ready; field/view use `dst_id` selector |
| write scope validation | model hot path write guard | may preview writes only after workbench scope evidence comes from ready discovery gate |
| `vika.catalog.status` | maintenance/diagnostic | reports health and discovery readiness; namespace discovery readiness must be produced from the same scoped gate used by namespace search |
| `vika.catalog.refresh` | maintenance only | may call live Vika APIs for one bounded target space; not model searchable/callable |
| `vika.catalog.clear` | maintenance only | clears explicit scope or full namespace state; not model searchable/callable |

Any future catalog content reader must add a row to this matrix and call the same readiness gate
before returning content.

## Model-Facing Tool Contract

The model-facing path may use:

- `vika_guide`
- `vika_resolve_datasheet`
- cache-only catalog diagnostic/search/get/children readers if exposed through visible meta tools
- schema/query/export/write preview/commit after a target is resolved and scope-checked
- artifact head/search/read/status for exported records

The model-facing path must not use:

- `vika.catalog.refresh`
- `vika.catalog.clear`
- token-wide `vika.spaces.list`
- live `vika.nodes.list/search/tree/get` as discovery
- any hidden operation with `force_refresh=true`
- any hidden operation with `use_cache=false` for discovery/scope resolution

If discovery readiness is empty, stale, refreshing, refresh-abandoned, or failed, discovery returns
a machine-readable state and clear next actions. It does not silently refresh.

Recommended error/status shape:

```json
{
  "error": {
    "code": "catalog_not_ready",
    "message": "The workbench catalog is not ready for cache-only discovery.",
    "details": {
      "discovery_status": "empty",
      "ready_for_discovery": false,
      "workbench_scope": "https://vika.cn/workbench/fod...",
      "space_id": "spc..."
    }
  },
  "next_actions": [
    "Ask an operator to run the catalog refresh maintenance command.",
    "Retry discovery after ready_for_discovery=true."
  ]
}
```

## Workbench Scope Rules

Folder workbench scope requires `workbench_space_id`. Without it, return a configuration error.
Do not scan token-visible spaces to infer the space.

For a folder workbench, membership is determined by cached node parent relationships:

- root folder id equals the configured workbench id, or
- target node/datasheet is a descendant of the root folder.

For a datasheet workbench, only that datasheet is in scope.

Write operations require fresh membership evidence. If the catalog is missing or stale, write preview
must be rejected with a catalog freshness error and maintenance next action. Read paths also must not
return stale catalog content: they return `catalog_stale` with maintenance guidance and no `nodes`,
`matches`, or `item`.

## Maintenance Refresh Contract

Refresh is a maintenance operation. It can be implemented as:

- CLI command,
- admin-only hidden tool,
- external scheduler invoking the CLI,
- optional non-blocking server background task.

It must not be exposed through `vika_search_tools`, `vika_describe_tool`, or `vika_call_tool` for
ordinary model work.

Refresh is still bounded maintenance, not token-wide discovery. Every refresh must resolve exactly
one target space in this order:

1. explicit CLI/tool `space_id`
2. configured `vika.workbench_space_id`
3. configured `vika.default_space_id`

If none is available, return `catalog_refresh_scope_required`. Do not call token-wide
`spaces.list` to discover or infer a target. When a target space is explicit, refresh only that
space and do not pre-list all token-visible spaces.

The refresh implementation should optimize the current expensive path:

1. Prefer a minimal folder/datasheet index.
2. Avoid default Form/Dashboard searches.
3. Use `Folder` and `Datasheet` typed search or one complete tree call, whichever is verified to be
   sufficient.
4. If multiple remote calls are needed, use bounded concurrency and capture per-request telemetry.
5. Treat Folder and Datasheet typed request failures as required failures. `nodes.alist` may be
   telemetry or supplemental data, but it must not mask typed request failure.
6. Preserve the previous cache on required refresh failure; do not replace it with empty or partial
   results.
7. Persist partial failure metadata instead of hiding errors. If fields/views were explicitly
   requested and schema refresh fails, mark the maintenance refresh failed and include the schema
   error in `last_refresh_error`.
8. Do not block stdio/AstrBot startup.

Refresh state must be trustworthy and scope-bound. A stale `refreshing` state left by a crashed
process must become `refresh_abandoned` after the refresh timeout for that same `(namespace,
space_id)` scope. Clearing one `space_id` must clear only that space's catalog rows and refresh
state. Full namespace catalog clear must clear all refresh states as well as catalog rows so an empty
cache does not retain a misleading generation id or old counts.

The old startup-sync configuration must not be reintroduced as an ambiguous blocking startup
refresh. If a future startup refresh option is added, it must be explicitly non-blocking background
maintenance. The default behavior for stdio/AstrBot must be no startup refresh.

## Implementation Work Items

1. Add catalog refresh metadata storage.
2. Add separate `CatalogHealth`, `DiscoveryReadiness`, and `SelectorReadiness` calculations for
   `empty`, `ready`, `stale`, `refreshing`, `refresh_abandoned`, `failed`, and `disabled`.
3. Make catalog search/get/list helpers consume the correct readiness object instead of reusing
   maintenance health as model readiness.
4. Change `WorkbenchScope.load_nodes()` to read cached catalog data only.
5. Add a cache-only child/list reader if folder exploration needs bounded paging.
6. Change `vika_resolve_datasheet` to return catalog state errors on cache miss/stale instead of
   refreshing.
7. Move refresh/clear out of the model-searchable hidden tool surface.
8. Ensure write preview rejects stale/missing catalog membership evidence.
9. Optimize refresh to index only Folder and Datasheet by default.
10. Make maintenance refresh require a bounded space target and reject no-scope refresh before any
    API call.
11. Make explicit-space refresh avoid token-wide `spaces.list`.
12. Ensure required node request failure preserves existing cache and marks refresh failed.
13. Ensure requested schema refresh failure is visible and marks refresh failed.
14. Add stale-refresh timeout handling and full clear refresh-state reset.
15. Update model guide, tool descriptions, README, AstrBot docs, and standard MCP documentation.

## Required Tests

Add or update tests that prove:

- `vika_resolve_datasheet` never calls `vika.nodes.list` with `use_cache=false` or
  `force_refresh=true`.
- Resolver cache miss returns `catalog_not_ready` or equivalent, without API fallback.
- Resolver stale catalog returns a stale/catalog freshness error, without API fallback.
- Folder scope membership is computed from cached parent relationships.
- Write preview is rejected when scope membership depends on missing or stale catalog data.
- Read discovery can surface stale status only as `catalog_stale` without returning catalog content.
- `vika.catalog.refresh` and `vika.catalog.clear` are not returned by model-facing tool search,
  describe, or route flows.
- Maintenance refresh indexes Folder and Datasheet by default, not Form/Dashboard.
- CLI and hidden/admin refresh reject no-scope refresh with `catalog_refresh_scope_required`.
- Explicit-space refresh does not call token-wide `spaces.list`.
- Refresh lifecycle state is stored and read per `(namespace, space_id)`; a failed or refreshing
  refresh for `spcB` must not block cache-only discovery for ready `spcA`.
- Required Folder/Datasheet request failure preserves the previous node/datasheet cache and marks
  refresh health failed.
- Requested schema refresh failure is visible in the return body and `last_refresh_error`.
- Stale `refreshing` state becomes `refresh_abandoned`.
- Space-scoped catalog clear removes only that space's refresh state; full namespace catalog clear
  removes all refresh state.
- Catalog diagnostic response includes generation, freshness, TTL, db path, counts, refresh timestamps, duration,
  last error fields, `health_status`, `ready_for_discovery`, `discovery_status`, and
  `discovery_error`.
- Existing export artifact and write hash-confirmation tests continue to pass.

## Verification Commands

Run focused tests first, then full regression:

```powershell
python -m pytest tests/test_standard_mcp_surface.py -q
python -m pytest tests/test_catalog_cache_discovery.py -q
python -m pytest tests/test_runtime_registry.py tests/test_limits_and_artifacts.py tests/test_write_plans.py -q
python -m pytest -q
```

Run scans:

```powershell
rg -n "use_cache.: False|use_cache=False|force_refresh.: True|force_refresh=True" runtime tools tests docs README.md standard_server.py -S
rg -n "vika\\.catalog\\.refresh|vika\\.catalog\\.clear" runtime tools docs README.md standard_server.py -S
rg -n "Authorization: Bearer|VIKAMCP_VIKA__API_TOKEN=.*[A-Za-z0-9]{12,}" . -S
```

The first scan may still find maintenance refresh implementation and negative tests. It must not find
normal resolver/scope/model-facing paths using forced refresh. The second scan may find maintenance
docs and admin registration, but not ordinary model guide text that tells the LLM to call refresh.

## Acceptance Criteria

The stage is complete only when current code and tests prove:

- The model hot path is cache-only for discovery.
- Full space refresh cannot be triggered by normal model task flow.
- Heavy refresh remains available as maintenance work.
- Maintenance refresh is scope-bounded and cannot fall back to token-wide space enumeration.
- Maintenance refresh state is scope-bounded and cannot contaminate another space's readiness.
- Required refresh failure preserves old cache and makes failure state visible.
- Stale in-progress refresh state becomes `refresh_abandoned` instead of persisting forever.
- Cache state is explicit and machine-readable.
- Writes are not allowed with missing or stale scope membership.
- Documentation tells operators how to refresh and tells models how to handle cache states.
- No token or test secret is written to the repo.
