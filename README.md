# vika_mcp

`vika_mcp` is the MCP-oriented Vika service that supersedes the old
AstrBot-specific plugin contents in this repository.

The Vika SDK is vendored into this repository so the project can be installed
from a single GitHub checkout without relying on PyPI for `astral-vika`:

- Runtime import package: `astral_vika`
- Vendored source snapshot: `vendor/astral_vika/src/astral_vika`
- Local development checkout: `astral_vika/` may exist beside this package, but
  it is ignored by this repository and is not used for packaging. Set
  `VIKAMCP_USE_LOCAL_ASTRAL_VIKA=1` only when deliberately testing that local
  checkout instead of the vendored snapshot.

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

## Configuration

If `--config` or `VIKAMCP_CONFIG` points to a missing, malformed, or non-object
YAML file, startup fails. If no explicit path is provided and the default
`vika_mcp.yaml` file is absent, the service starts from defaults plus
environment overrides.

Registry switches are honored at startup:

- `registry.enable_vika_tools=false` skips Vika tool registration.
- `registry.enable_builtin=true` registers builtin tools such as `time.now`.
- `registry.enabled_toolsets` can whitelist `vika` and/or `builtin`.

Attachment download host allowlist:

```powershell
$env:VIKAMCP_VIKA__ATTACHMENT_DOWNLOAD_ALLOWED_HOSTS="files.vika.cn,cdn.example.com"
```

`vika.attachments.download` always allows the configured `vika.host` and the
extra hosts above. It does not accept `save_path`; downloads are streamed into a
service-owned artifact and return `artifact_id`, manifest fields, byte count,
content type, filename, and `next_actions=["vika_artifact_status"]`.

`vika.attachments.upload` intentionally keeps arbitrary local `file_path`
support. Preview reports `file_path`, `file_name`, `file_size_bytes`, and
`file_sha256`; commit recalculates the file hash and rejects the upload with
`file_hash_mismatch` if the file changed after preview.

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
