import json
import asyncio
from contextlib import closing
from datetime import datetime, timedelta, timezone
import ipaddress
from pathlib import Path
import subprocess
import socket
import ssl
import sys
import tempfile
import time
import threading
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import hashes, serialization
from cryptography import x509
from cryptography.x509.oid import NameOID
import httpx
import jwt
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from starlette.testclient import TestClient
import uvicorn

from hub import Hub
from remote_mcp import build_remote_server


RESOURCE = "https://hub.example.com/mcp"
ISSUER = "https://auth.example.com/"


class RemoteMCPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        cls.jwk.update(kid="test-key", use="sig", alg="RS256")

    def token(self, **changes):
        claims = dict(iss=ISSUER, aud=RESOURCE, sub="owner", client_id="chatgpt",
                      scope="hub:operator", exp=int(time.time()) + 120)
        claims.update(changes)
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "test-key"})

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = str(Path(self.directory.name) / "hub.sqlite3")
        self.jwks = patch("jwt.PyJWKClient.fetch_data", return_value={"keys": [self.jwk]})
        self.jwks.start()
        self.addCleanup(self.jwks.stop)
        self.server = build_remote_server(self.database, "chatgpt-operator", RESOURCE,
                                          ISSUER, ISSUER + "jwks", "owner")
        self.client = self.enterContext(TestClient(self.server.streamable_http_app()))

    def rpc(self, method, params=None, token=None, **headers):
        request_headers = {"Host": "hub.example.com", "Accept": "application/json, text/event-stream"}
        if token is not None:
            request_headers["Authorization"] = "Bearer " + token
        request_headers.update(headers)
        return self.client.post("/mcp", headers=request_headers,
                                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})

    def test_anonymous_all_mcp_methods_are_denied(self):
        for method in ("GET", "POST", "DELETE"):
            with self.subTest(method=method):
                response = self.client.request(method, "/mcp")
                self.assertEqual(response.status_code, 401)
                self.assertIn("resource_metadata=", response.headers["www-authenticate"])
        self.assertFalse(Path(self.database).exists())

    def test_discovery_is_public_and_contains_no_task_data(self):
        response = self.client.get("/.well-known/oauth-protected-resource/mcp")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["resource"], RESOURCE)
        self.assertEqual(response.json()["authorization_servers"], [ISSUER])
        self.assertEqual(response.json()["scopes_supported"], ["hub:operator"])
        self.assertNotIn(self.database, response.text)

    def test_invalid_tokens_cannot_read_or_create_tasks(self):
        invalid = ["garbage", self.token(exp=int(time.time()) - 10),
                   self.token(aud="https://other.example/mcp"), self.token(iss=ISSUER + "other"),
                   self.token(sub="another-user"), self.token(sub=""),
                   self.token(client_id="", azp=""), self.token(scope=["hub:operator"]),
                   self.token(exp=None), self.token(nbf=int(time.time()) + 300),
                   jwt.encode({"sub": "owner"}, "a" * 32, algorithm="HS256"),
                   jwt.encode(dict(iss=ISSUER, aud=RESOURCE, sub="owner", scope="hub:operator",
                                   client_id="chatgpt", exp=int(time.time()) + 120),
                              rsa.generate_private_key(public_exponent=65537, key_size=2048),
                              algorithm="RS256", headers={"kid": "test-key"})]
        for token in invalid:
            with self.subTest(token_type=invalid.index(token)):
                self.assertEqual(self.rpc("tools/list", token=token).status_code, 401)
        self.assertEqual(self.rpc("tools/list", token=self.token(scope="hub:read")).status_code, 403)
        self.assertFalse(Path(self.database).exists())

    def test_jwks_outage_fails_closed(self):
        with patch("jwt.PyJWKClient.fetch_data", side_effect=jwt.PyJWKClientConnectionError("unavailable")):
            self.assertEqual(self.rpc("tools/list", token=self.token()).status_code, 401)

    def test_host_and_origin_validation(self):
        self.assertEqual(self.rpc("tools/list", token=self.token(), Host="evil.example").status_code, 421)
        self.assertEqual(self.rpc("tools/list", token=self.token(), Origin="https://evil.example").status_code, 403)

    def test_authenticated_task_creation_and_reconnect_remain_unassigned(self):
        initialized = self.rpc("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                                "clientInfo": {"name": "test", "version": "1"}}, self.token())
        self.assertEqual(initialized.status_code, 200, initialized.text)
        self.assertNotIn("mcp-session-id", initialized.headers)
        response = self.rpc("tools/call", {"name": "create_task", "arguments": {
            "repository": "example/test", "request": "Disposable MCP smoke test"}}, self.token())
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["result"]
        self.assertFalse(result.get("isError"), result)
        task = json.loads(result["content"][0]["text"])
        self.assertEqual(task["status"], "queued")
        self.assertIsNone(task["agent"])
        with closing(Hub(self.database)) as hub:
            self.assertEqual(hub.task(task["id"])["request"], "Disposable MCP smoke test")
        # Each HTTP request is independently authenticated, including a refreshed token.
        response = self.rpc("tools/call", {"name": "hub_status"}, self.token(exp=int(time.time()) + 200))
        tasks = json.loads(response.json()["result"]["content"][0]["text"])["tasks"]
        self.assertEqual(len(tasks), 1)
        self.assertIsNone(tasks[0]["agent"])

    def test_cli_requires_auth_and_rejects_network_bind(self):
        script = str(Path(__file__).resolve().parents[1] / "remote_mcp.py")
        auth_args = ["--resource-url", RESOURCE, "--issuer-url", ISSUER,
                     "--jwks-url", ISSUER + "jwks", "--subject", "owner"]
        for extra in ([], [*auth_args, "--host", "0.0.0.0"], [*auth_args, "--port", "0"]):
            result = subprocess.run([sys.executable, script, "--database", self.database,
                                     "--identity", "operator", *extra], capture_output=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)

    def test_real_https_mcp_client_and_reconnect(self):
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        now = datetime.now(timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                .public_key(self.key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(hours=1))
                .add_extension(x509.SubjectAlternativeName([
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
                .sign(self.key, hashes.SHA256()))
        cert_path = Path(self.directory.name) / "test.pem"
        key_path = Path(self.directory.name) / "test.key"
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(self.key.private_bytes(serialization.Encoding.PEM,
                             serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        context = ssl.create_default_context(cafile=str(cert_path))
        # Bind the socket ourselves to avoid a port-allocation race.
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            app = build_remote_server(self.database, "chatgpt-operator", RESOURCE,
                                      ISSUER, ISSUER + "jwks", "owner").streamable_http_app()
            server = uvicorn.Server(uvicorn.Config(app, ssl_certfile=str(cert_path),
                                    ssl_keyfile=str(key_path), log_level="error", access_log=False))
            thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
            thread.start()
            try:
                deadline = time.monotonic() + 10
                while not server.started and thread.is_alive() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(server.started)

                async def scenario():
                    url = f"https://127.0.0.1:{port}/mcp"
                    async with httpx.AsyncClient(verify=context, trust_env=False) as client:
                        self.assertEqual((await client.post(url, json={})).status_code, 401)
                    for attempt in range(2):
                        async with httpx.AsyncClient(verify=context, trust_env=False, headers={
                            "Host": "hub.example.com", "Authorization": "Bearer " + self.token()
                        }) as client:
                            async with streamable_http_client(url, http_client=client) as (read, write, _):
                                async with ClientSession(read, write) as session:
                                    await session.initialize()
                                    identity = await session.call_tool("hub_identity", {})
                                    self.assertFalse(identity.isError)
                                    if attempt == 0:
                                        result = await session.call_tool("create_task", {
                                            "repository": "example/test", "request": "HTTPS smoke test"})
                                        self.assertFalse(result.isError)
                                    status = await session.call_tool("hub_status", {})
                                    tasks = json.loads(status.content[0].text)["tasks"]
                                    self.assertEqual(len(tasks), 1)
                                    self.assertIsNone(tasks[0]["agent"])
                asyncio.run(scenario())
            finally:
                server.should_exit = True
                thread.join(timeout=10)
                self.assertFalse(thread.is_alive(), "HTTPS test server did not stop")

    def test_insecure_or_ambiguous_configuration_is_rejected(self):
        for resource, issuer, jwks, subject in (
            ("http://hub.example.com/mcp", ISSUER, ISSUER + "jwks", "owner"),
            (RESOURCE, "http://auth.example.com/", ISSUER + "jwks", "owner"),
            (RESOURCE, ISSUER, "http://auth.example.com/jwks", "owner"),
            (RESOURCE + "?token=secret", ISSUER, ISSUER + "jwks", "owner"),
            ("https://user:password@hub.example.com/mcp", ISSUER, ISSUER + "jwks", "owner"),
            ("https://@hub.example.com/mcp", ISSUER, ISSUER + "jwks", "owner"),
            ("https://hub.example.com/other", ISSUER, ISSUER + "jwks", "owner"),
            (RESOURCE, ISSUER, ISSUER + "jwks", " "),
        ):
            with self.subTest(resource=resource, issuer=issuer, subject=subject):
                with self.assertRaises(ValueError):
                    build_remote_server(self.database, "operator", resource, issuer, jwks, subject)
