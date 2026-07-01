# Artifacts

Large table reads are exported as service-created artifact files under:

```text
artifacts/exports/
```

The default export format is CSV so execution agents can analyze the artifact
with pandas or spreadsheet tooling. JSONL remains available for machine-oriented
workflows. XLSX is out of scope for this stage and is not advertised.

`vika_export_records` is bounded and requires `max_records`. The current hard
cap is 100000 records per export.

Export and artifact read/search/head/status use the same runtime-owned
`ArtifactStore`; hidden tools must not construct separate artifact stores.

Each export creates:

- `{artifact_id}.csv` by default, or `{artifact_id}.jsonl` when requested
- `{artifact_id}.manifest.json`

Attachment downloads create binary artifacts:

- `dl_*.bin` data file with a service-generated filename under `artifacts/exports/`
- `dl_*.manifest.json`
- manifest fields include `artifact_id`, `filename`, `format="binary"`,
  `content_type`, `byte_count`, `created_at`, and `source_url_hash`
- the original URL is not stored in the manifest
- the tool response does not inline file content and returns
  `next_actions=["vika_artifact_status"]`

Available artifact tools:

- `vika_artifact_head`: default 20 lines, hard max 100 lines.
- `vika_artifact_search`: default 20 hits, hard max 100 hits, snippet max 300 chars.
- `vika_artifact_read`: default 100 lines, hard max 500 lines, total max 40000 chars.
- `vika_artifact_status`: reads the manifest/status.

Artifact tools only read service-created files under `artifacts/exports/`. They
do not accept arbitrary file paths.

`head`, `search`, and `read` are line-oriented and only support CSV/JSONL
exports. Binary download artifacts are status-only through
`vika_artifact_status`.
