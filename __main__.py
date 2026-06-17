import os
import sys
import argparse


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


if __name__ == "__main__":
    main()
