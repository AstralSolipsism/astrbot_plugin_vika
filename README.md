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

## Test

```powershell
python -m pytest -q
```
