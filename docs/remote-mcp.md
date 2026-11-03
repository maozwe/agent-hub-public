# Remote MCP operator integration (experimental)

`remote_mcp.py` reuses the existing operator tools and SQLite database. Local
stdio connections are unchanged. The HTTP server requires OAuth on **every**
MCP request, including GET/streaming and DELETE. There is no anonymous mode.

## What is ready, and what still needs provisioning

The resource server validates RS256 access tokens against a configured HTTPS
JWKS endpoint, exact issuer, `/mcp` audience, expiry, exact operator subject and
`hub:operator` scope. Invalid tokens and JWKS failures fail closed. It publishes
RFC 9728 resource metadata at `/.well-known/oauth-protected-resource/mcp` and
advertises that URL in its 401 challenge. Only discovery is public.

This is a resource server, **not an OAuth authorization server**. To connect a
real ChatGPT account, provision a public HTTPS hostname and a trusted OAuth
provider first. Private Tailscale Serve access for the web UI does not by itself
make this MCP endpoint reachable from ChatGPT. Do not enable Funnel or replace
an existing web UI proxy to work around this.

The provider must support authorization code + PKCE S256, authorization-server
metadata, and either a predefined ChatGPT OAuth client, DCR or CIMD. Register the
exact redirect URI shown by ChatGPT for this connection. Configure the requested
resource `https://hub.example.com/mcp` as the access-token audience, issue RS256
JWT access tokens with `iss`, `sub`, `aud`, `exp`, `scope` and `client_id` (or
`azp`), and allow only the intended operator to consent to `hub:operator`.
An ID token or a static API key is not a substitute for an access token.

## Start the protected backend

Install `requirements.txt` in a virtual environment. Start with a disposable
database before pointing at real task data. Replace all example values:

```powershell
python remote_mcp.py --database .local/remote-test.sqlite3 --identity chatgpt-operator `
  --resource-url https://hub.example.com/mcp `
  --issuer-url https://auth.example.com/ `
  --jwks-url https://auth.example.com/.well-known/jwks.json `
  --subject EXACT_OAUTH_SUBJECT
```

Create the database's parent directory first. Copy the issuer and JWKS URL from
the provider's trusted configuration; do not take them from a token. Preserve
the issuer's trailing slash exactly. The subject is the provider's stable user
identifier, not the local Hub identity or an arbitrary email address. The Hub
identity is bound by startup configuration and cannot be selected by a caller.

The backend binds `127.0.0.1:8877` (optionally `::1`), refuses non-loopback binds,
and refuses missing OAuth settings or non-HTTPS URLs. Keep the database, local
settings, certificates and credentials outside public Git commits. The operator
connection exposes task/agent management and decision tools, so grant it only
to the intended owner. Additional participants still gain no execution rights.

## HTTPS reverse proxy

`deploy/Caddyfile.remote-mcp` is a deployment template for a dedicated host.
Caddy must run on the same machine/network namespace as the loopback backend.
Set `HUB_MCP_HOST` to the hostname matching `--resource-url`, configure DNS and
certificate issuance, then validate before starting:

```powershell
$env:HUB_MCP_HOST = 'hub.example.com'
caddy validate --config deploy/Caddyfile.remote-mcp --adapter caddyfile
caddy run --config deploy/Caddyfile.remote-mcp --adapter caddyfile
```

Only `/mcp` and resource discovery are proxied; the Hub web UI and its control
API are not exposed. Keep the original Host and Authorization headers. Do not
disable TLS certificate checks, token checks or Host/Origin validation to resolve
a connection error. Add internet-facing traffic limits at your chosen gateway
before a production deployment. This template has not been validated against a
provisioned public hostname or a live OAuth tenant.

Before using real data, verify the HTTPS discovery document and confirm that
anonymous GET, POST and DELETE requests to `/mcp` return 401. Also verify rejection
of expired tokens, wrong audience/issuer/subject, and missing scope. Do not
configure ChatGPT's connection as unauthenticated. In ChatGPT, add the HTTPS
`/mcp` URL as a custom MCP connection with OAuth, complete consent, and refresh
the tool list. Tool availability and write access depend on account/workspace
settings; verify `create_task` is actually available.

## Verification and task creation

```powershell
python -m unittest discover -s tests
node --test tests/*.js
```

`tests/test_remote_mcp.py` covers anonymous access, invalid tokens, discovery,
JWKS failure, Host/Origin checks, CLI rejection, and authenticated creation. It
also runs a real loopback HTTPS server with a temporary trusted certificate and
the MCP SDK client, creates one task and reconnects to read it. RSA signatures
are actually checked; JWKS retrieval uses a test fixture. This proves the
resource server and HTTPS transport, not a real provider login or ChatGPT UI.

For final account verification, use a disposable database and ask ChatGPT to
create one explicitly named test task in an example repository. Confirm via
`hub_status` that there is exactly one task and it is `queued` with `agent=null`.
Task creation never assigns or starts an agent. Do not retry an uncertain
creation result without checking status: creation is not idempotent. Application
approval records never replace native provider approval.

Stop the test proxy/server after verification. Disable only the dedicated route
you created; do not reset unrelated Tailscale or other proxy settings.

References: [OpenAI OAuth requirements](https://developers.openai.com/plugins/build/auth),
[MCP Python SDK authorization](https://github.com/modelcontextprotocol/python-sdk/blob/v1.30.0/docs/authorization.md).
