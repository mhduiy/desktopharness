import unittest
from types import SimpleNamespace
from unittest.mock import patch

from mcp_autogui.transport_auth import StaticBearerTokenVerifier, fastmcp_auth_kwargs


class TransportAuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_static_bearer_token_is_checked_before_access_is_granted(self):
        verifier = StaticBearerTokenVerifier("expected-token")

        self.assertIsNone(await verifier.verify_token("wrong-token"))
        access = await verifier.verify_token("expected-token")

        self.assertIsNotNone(access)
        self.assertEqual(access.client_id, "autoui-mcp")
        self.assertEqual(access.scopes, [])

    def test_fastmcp_auth_wiring_uses_the_configured_secret_environment(self):
        config = SimpleNamespace(
            transport_auth_mode="bearer-token",
            transport_token_env="AUTOUI_TEST_TOKEN",
            transport_port=8651,
        )
        with patch.dict("os.environ", {"AUTOUI_TEST_TOKEN": "secret"}, clear=True):
            kwargs = fastmcp_auth_kwargs(config)

        self.assertIn("auth", kwargs)
        self.assertIsInstance(kwargs["token_verifier"], StaticBearerTokenVerifier)


if __name__ == "__main__":
    unittest.main()
