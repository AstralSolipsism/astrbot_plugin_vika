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
python -m vika_mcp --host localhost --port 8080
```

The default HTTP API exposes:

- `GET /.well-known/healthz`
- `GET /mcp/v1/tools`
- `POST /mcp/v1/execute`
- `GET /mcp/v1/stream/{job_id}`

Write tools default to dry-run. Real writes require both:

```json
{
  "dry_run": false,
  "confirm": true
}
```

## Test

```powershell
python -m pytest -q
```
