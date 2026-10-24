"""Remote MCP transport entry point.

Bind to loopback only. Put an authenticated, TLS-terminating MCP-aware
gateway in front of this process; never expose the endpoint unauthenticated.
"""
import argparse
from hub_mcp import build_server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--identity", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8877)
    args = parser.parse_args()
    if args.host not in ("127.0.0.1", "::1", "localhost"):
        parser.error("Remote MCP must bind to loopback; use an authenticated gateway")
    if not 1 <= args.port <= 65535:
        parser.error("Invalid port")
    server = build_server(args.database, args.identity, "operator")
    server.settings.host = args.host
    server.settings.port = args.port
    server.run(transport="streamable-http")


if __name__ == "__main__":
    main()
