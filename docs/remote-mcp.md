# Remote MCP operator integration (experimental)

This entrypoint reuses the existing operator tools in `hub_mcp.py` and the same SQLite database. It does **not** replace the local stdio MCP service.

## Start locally

Install `requirements.txt` in a virtual environment, then:

```powershell
python remote_mcp.py --database "C:\\path\\hub.sqlite3" --identity "chatgpt-operator"
```

The endpoint is `http://127.0.0.1:8877/mcp`. Do not expose this port publicly or forward it directly through a tunnel.

## Security requirements before remote access

- Put a TLS-terminating MCP-compatible gateway in front of the loopback endpoint.
- Require authenticated identity and authorize each MCP request. Restrict access to a single operator; no anonymous access.
- Ensure the gateway does not permit bypassing authentication, including on SSE/streaming requests.
- Restrict Cloudflare Tunnel ingress to the authenticated gateway, **not** the unauthenticated local MCP endpoint.
- Check the gateway's MCP client compatibility, Origin/Host handling, and session isolation before use.
- Protect the SQLite database and do not expose its path or contents.
- Keep task creation separate from agent assignment; approval actions require explicit user authorization.

This repository change provides a local HTTP transport only. It does **not** implement OAuth, Cloudflare Access, or the authentication gateway, and must not be treated as production-ready remote access.

## Verification checklist

1. Run existing tests: `python -m unittest discover -s tests`.
2. Start the server with a disposable test database and verify that `hub_identity` and `hub_status` work from a local MCP client.
3. Verify that binding to `0.0.0.0` is rejected.
4. Configure the authenticated gateway and verify anonymous requests are rejected.
5. Verify authorized task creation, then confirm the task remains unassigned.
6. Test reconnect, session behavior, and gateway streaming compatibility.
