# vika_mcp

`vika_mcp` is the MCP-oriented Vika service that supersedes the old
AstrBot-specific plugin contents in this repository.

The Vika SDK remains a separate package:

- Runtime dependency: `astral-vika>=1.1.3,<2.0.0`
- Local development checkout: `astral_vika/` may exist beside this package, but
  it is ignored by this repository and keeps its own release lifecycle.

## Run

```powershell
$env:VIKAMCP_VIKA__API_TOKEN="your-vika-token"
$env:VIKAMCP_VIKA__WORKBENCH_URL="https://vika.cn/workbench/fod6mElQf7PFD"
$env:VIKAMCP_VIKA__WORKBENCH_SPACE_ID="your-workbench-space-id"
python -m vika_mcp --transport stdio
```

When `VIKAMCP_VIKA__WORKBENCH_URL` points to a folder workbench (`fod...`),
`VIKAMCP_VIKA__WORKBENCH_SPACE_ID` is required so the resolver can stay inside
that space without scanning all token-visible spaces.

For Streamable HTTP:

```powershell
python -m vika_mcp --transport streamable-http --host 127.0.0.1 --port 8080
```

The Streamable HTTP MCP endpoint is `/mcp`. The server does not expose the old
custom HTTP execute API. If Streamable HTTP is bound to a non-localhost address,
set an independent `VIKAMCP_MCP_BEARER_TOKEN`; do not reuse the Vika API token.

```json
{
  "mcpServers": {
    "vika": {
      "command": "python",
      "args": ["-m", "vika_mcp", "--transport", "stdio"],
      "env": {
        "VIKAMCP_VIKA__API_TOKEN": "your-vika-token",
        "VIKAMCP_VIKA__WORKBENCH_URL": "https://vika.cn/workbench/fod6mElQf7PFD",
        "VIKAMCP_VIKA__WORKBENCH_SPACE_ID": "your-workbench-space-id"
      }
    }
  }
}
```

The model sees stable meta tools first: guide, resolve, search, route, describe,
call, domain controls, and artifact readers. Business Vika tools stay hidden and
are invoked through `vika_call_tool` after `vika_describe_tool`.

Datasheet discovery is cache-first and cache-only on the model path. Large
workspace catalog refresh is a maintenance operation; normal `stdio` or
Streamable HTTP model requests must not trigger a full space scan. If the
catalog is empty, stale, refreshing, refresh-abandoned, or failed,
`vika_resolve_datasheet` reports that state and an operator should refresh the
catalog outside the LLM task flow.

Catalog search/get follows the same trust contract. It returns cached nodes,
matches, or items only after the selector readiness gate is ready. Namespace-wide
catalog lookup is strict: a scoped refresh failure, active refresh, or abandoned
refresh blocks content instead of mixing stale results from one space with ready
results from another.

Catalog refresh is bounded. It uses exactly one target space resolved in this
order: explicit `--space-id`, `VIKAMCP_VIKA__WORKBENCH_SPACE_ID`,
`VIKAMCP_VIKA__DEFAULT_SPACE_ID`. If none is configured, refresh returns
`catalog_refresh_scope_required` and never scans all spaces visible to the token.
Required Folder/Datasheet refresh failures mark the refresh failed and preserve
the previous catalog cache instead of replacing it with partial or empty data.

Catalog maintenance examples:

```powershell
python -m vika_mcp --catalog-status
python -m vika_mcp --catalog-refresh --space-id your-workbench-space-id
```

## Test

```powershell
python -m pytest -q
```
