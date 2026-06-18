# AstrBot Usage

`vika_mcp` is now a standard MCP server. AstrBot should connect through `stdio`
or `streamable_http`; do not use the removed custom HTTP execute API.

## stdio

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

When the workbench URL is a folder id (`fod...`), `VIKAMCP_VIKA__WORKBENCH_SPACE_ID`
is required. The MCP resolver uses that single space and does not scan all spaces
visible to the Vika token.

## streamable_http

Start locally:

```powershell
python -m vika_mcp --transport streamable-http --host 127.0.0.1 --port 8080
```

AstrBot URL:

```text
http://127.0.0.1:8080/mcp
```

If binding to a non-localhost address, set `VIKAMCP_MCP_BEARER_TOKEN` and send
that token as `Authorization: Bearer ...`. Do not reuse the Vika API token.

## Expected Tool Surface

AstrBot should see only stable meta tools by default:

- `vika_guide`
- `vika_resolve_datasheet`
- `vika_search_tools`
- `vika_route_task`
- `vika_describe_tool`
- `vika_call_tool`
- `vika_list_domains`
- `vika_activate_domain`
- `vika_artifact_head`
- `vika_artifact_search`
- `vika_artifact_read`
- `vika_artifact_status`

Business tools such as `vika.records.query` stay hidden and are called through
`vika_call_tool` after `vika_describe_tool`.

Datasheet discovery reads the persisted catalog only. AstrBot/LLM interactions
should not trigger a full Vika space-node refresh. If the catalog is empty,
stale, refreshing, refresh-abandoned, or failed, the MCP returns that state;
refresh the catalog through the maintenance/admin path before retrying table
discovery or writes.

Catalog search/get also uses the unified selector readiness gate. It returns
cached matches/items only when the relevant selector is ready. Namespace-wide
lookup is strict: scoped refresh failure, active refresh, or abandoned refresh
blocks content instead of mixing old results from one space with ready results
from another.

Maintenance refresh must stay bounded to one space. The CLI resolves the target
as explicit `--space-id`, then `VIKAMCP_VIKA__WORKBENCH_SPACE_ID`, then
`VIKAMCP_VIKA__DEFAULT_SPACE_ID`. Without one of those values it returns
`catalog_refresh_scope_required` and does not enumerate token-visible spaces.
If required Folder/Datasheet indexing fails, the MCP marks refresh health failed
and keeps the previous cache instead of writing partial results. Table discovery
must use `ready_for_discovery=true`, not maintenance health alone.

Example maintenance commands:

```powershell
python -m vika_mcp --catalog-status
python -m vika_mcp --catalog-refresh --space-id your-workbench-space-id
```
