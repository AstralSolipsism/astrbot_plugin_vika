import os
import sys
import argparse


def parse_args():
    parser = argparse.ArgumentParser(
        prog="vika-mcp",
        description="Start Vika MCP server with CLI overrides",
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
        help="Uvicorn log level (override config.server.log_level)",
        default=None,
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Inject CLI overrides via environment before app creation
    if args.config_path:
        os.environ["VIKAMCP_CONFIG"] = args.config_path
    if args.baseurl:
        os.environ["VIKAMCP_VIKA__HOST"] = args.baseurl

    # Defer import to honor env overrides
    try:
        from .server import create_app
    except Exception as e:
        print(f"Failed to import server: {e}", file=sys.stderr)
        sys.exit(1)

    app = create_app()

    # Read effective server params from the app's config
    cfg = getattr(app.state, "config", None)
    host = args.listen_host or (getattr(getattr(cfg, "server", None), "host", None) if cfg else None) or "localhost"
    port = args.listen_port or (getattr(getattr(cfg, "server", None), "port", None) if cfg else None) or 8080
    log_level = args.log_level or (getattr(getattr(cfg, "server", None), "log_level", None) if cfg else None) or "info"

    try:
        import uvicorn
    except Exception:
        print("uvicorn is required to run the server. Install with: pip install uvicorn", file=sys.stderr)
        sys.exit(1)

    uvicorn.run(app, host=host, port=port, log_level=str(log_level).lower())


if __name__ == "__main__":
    main()
