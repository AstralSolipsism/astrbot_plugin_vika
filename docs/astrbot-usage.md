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
