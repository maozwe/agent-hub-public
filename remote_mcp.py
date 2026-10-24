"""OAuth protected MCP resource server behind a TLS reverse proxy."""
import argparse
import asyncio
from urllib.parse import urlsplit

import jwt
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings

from hub_mcp import build_server


def https_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or any(c.isspace() for c in value)):
        raise ValueError("OAuth and resource URLs must be HTTPS without credentials, query or fragment")
    parsed.port  # Validate malformed ports at startup.
    return parsed


class OperatorTokenVerifier(TokenVerifier):
    def __init__(self, issuer, resource, jwks_url, subject):
        self.issuer, self.resource, self.subject = issuer, resource, subject
        self.jwks = jwt.PyJWKClient(jwks_url, timeout=5)

    async def verify_token(self, token):
        try:
            # JWKS retrieval is blocking; never perform it on the ASGI event loop.
            key = await asyncio.to_thread(self.jwks.get_signing_key_from_jwt, token)
            claims = jwt.decode(token, key.key, algorithms=["RS256"], audience=self.resource,
                                issuer=self.issuer, subject=self.subject,
                                options={"require": ["exp", "iss", "aud", "sub"]})
            scope = claims.get("scope", "")
            if not isinstance(scope, str) or type(claims["exp"]) is not int:
                return None
            client_id = claims.get("client_id") or claims.get("azp")
            if not isinstance(client_id, str) or not client_id.strip():
                return None
            return AccessToken(token=token, client_id=client_id, scopes=scope.split(),
                               expires_at=claims["exp"], resource=self.resource,
                               subject=claims["sub"], claims={"iss": self.issuer})
        except (jwt.PyJWTError, ValueError, TypeError):
            return None


def build_remote_server(database, identity, resource_url, issuer_url, jwks_url, subject,
                        host="127.0.0.1", port=8877):
    if host not in ("127.0.0.1", "::1"):
        raise ValueError("Remote MCP must bind to a loopback address")
    if not 1 <= port <= 65535:
        raise ValueError("Invalid port")
    resource = https_url(resource_url)
    https_url(issuer_url)
    https_url(jwks_url)
    if resource.path != "/mcp":
        raise ValueError("Resource URL must end in /mcp")
    if not isinstance(subject, str) or not subject.strip():
        raise ValueError("An exact OAuth operator subject is required")
    verifier = OperatorTokenVerifier(issuer_url, resource_url, jwks_url, subject)
    return build_server(database, identity, "operator", host=host, port=port,
                        token_verifier=verifier, stateless_http=True, json_response=True,
                        auth=AuthSettings(issuer_url=issuer_url, resource_server_url=resource_url,
                                          required_scopes=["hub:operator"], validate_token_resource=True),
                        transport_security=TransportSecuritySettings(
                            allowed_hosts=[resource.netloc, "127.0.0.1:*", "[::1]:*"],
                            allowed_origins=[f"https://{resource.netloc}"]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--identity", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8877)
    parser.add_argument("--resource-url", required=True, help="Canonical public HTTPS URL ending in /mcp")
    parser.add_argument("--issuer-url", required=True, help="Exact OAuth issuer, including trailing slash if present")
    parser.add_argument("--jwks-url", required=True, help="Trusted issuer's HTTPS JWKS endpoint")
    parser.add_argument("--subject", required=True, help="Exact OAuth subject allowed to act as operator")
    args = parser.parse_args()
    try:
        server = build_remote_server(args.database, args.identity, args.resource_url,
                                     args.issuer_url, args.jwks_url, args.subject, args.host, args.port)
    except ValueError as error:
        parser.error(str(error))
    server.run(transport="streamable-http")


if __name__ == "__main__":
    main()
