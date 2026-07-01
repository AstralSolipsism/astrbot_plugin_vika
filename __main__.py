import os
import sys
import argparse
import asyncio
import json


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="vika-mcp",
        description="Start the standard Vika MCP server",
    )
    parser.add_argument(
        "--transport",
        dest="transport",
        choices=["stdio", "streamable-http", "streamable_http"],
        default="stdio",
        help="Standard MCP transport to run: stdio or streamable-http.",
    )
    parser.add_argument(
        "--baseurl", "--base-url", "--api-base",
        dest="baseurl",
        help="Vika API base URL, e.g. https://selfhosted.example.com",
        default=None,
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        help="Path to vika_mcp.yaml configuration file",
        default=None,
    )
    parser.add_argument(
        "--host",
        dest="listen_host",
        help="Server listen host (override config.server.host)",
        default=None,
    )
    parser.add_argument(
        "--port",
        dest="listen_port",
        type=int,
        help="Server listen port (override config.server.port)",
        default=None,
    )
    parser.add_argument(
        "--log-level",
        dest="log_level",
        help="MCP server log level (override config.server.log_level)",
        default=None,
    )
    parser.add_argument(
        "--catalog-status",
        action="store_true",
        help="Maintenance mode: print persisted catalog status and exit without starting MCP.",
    )
    parser.add_argument(
        "--catalog-refresh",
        action="store_true",
        help="Maintenance mode: refresh the persisted catalog and exit without starting MCP.",
    )
    parser.add_argument(
        "--space-id",
        dest="space_id",
        default=None,
        help="Maintenance catalog space_id override. Defaults to configured workbench_space_id, then default_space_id.",
    )
    parser.add_argument(
        "--include-fields",
        action="store_true",
        help="Maintenance refresh option: also refresh fields for discovered datasheets.",
    )
    parser.add_argument(
        "--include-views",
        action="store_true",
        help="Maintenance refresh option: also refresh views for discovered datasheets.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Maintenance refresh option: force API reads for the bounded target space.",
    )
    args = parser.parse_args(argv)
    if args.transport == "streamable_http":
        args.transport = "streamable-http"
    return args


def main(argv=None):
    args = parse_args(argv)

    # Inject CLI overrides via environment before app creation
    if args.config_path:
        os.environ["VIKAMCP_CONFIG"] = args.config_path
    if args.baseurl:
        os.environ["VIKAMCP_VIKA__HOST"] = args.baseurl

    if args.catalog_status or args.catalog_refresh:
        try:
            result = asyncio.run(_run_catalog_maintenance(args))
        except Exception as e:
            print(f"Catalog maintenance failed: {e}", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if isinstance(result, dict) and "error" in result:
            sys.exit(1)
        return

    # Defer import to honor env overrides.
    try:
        from .standard_server import create_standard_mcp
    except Exception as e:
        print(f"Failed to import server: {e}", file=sys.stderr)
        sys.exit(1)

    server = create_standard_mcp(
        host=args.listen_host,
        port=args.listen_port,
        log_level=args.log_level,
        transport=args.transport,
    )
    server.run(transport=args.transport)


async def _run_catalog_maintenance(args):
    from .cache import CatalogCache
    from .config import load_config
    from .tools.vika_tools import VikaClient

    cfg = load_config()
    ttl_hours = getattr(cfg.cache, "ttl_hours", None) or getattr(cfg.vika, "cache_duration_hours", 24)
    cache = CatalogCache(db_path=cfg.cache.db_path, ttl_hours=ttl_hours, enabled=cfg.cache.enabled)
    client = VikaClient(
        api_token=cfg.vika.api_token,
        host=cfg.vika.host,
        default_space_id=cfg.vika.default_space_id,
        workbench_space_id=getattr(cfg.vika, "workbench_space_id", None),
        cache=cache,
    )
    if args.catalog_status:
        return client.catalog_status(space_id=args.space_id)
    target_space_id = args.space_id or getattr(cfg.vika, "workbench_space_id", None) or cfg.vika.default_space_id
    if not target_space_id:
        return {
            "error": {
                "code": "catalog_refresh_scope_required",
                "message": (
                    "Catalog refresh requires --space-id, VIKAMCP_VIKA__WORKBENCH_SPACE_ID, "
                    "or VIKAMCP_VIKA__DEFAULT_SPACE_ID; token-wide space scanning is disabled."
                ),
                "details": {
                    "space_id": args.space_id or None,
                    "workbench_space_id": getattr(cfg.vika, "workbench_space_id", None),
                    "default_space_id": cfg.vika.default_space_id,
                },
            }
        }
    return await client.catalog_refresh(
        space_id=target_space_id,
        include_fields=args.include_fields,
        include_views=args.include_views,
        force=args.force,
    )


if __name__ == "__main__":
    main()
