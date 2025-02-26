import unittest

from leanclient.base_client import BaseLeanLSPClient

from run_tests import TEST_ENV_DIR


class TestBaseClient(unittest.IsolatedAsyncioTestCase):
    async def test_initial_build(self):
        lsp = BaseLeanLSPClient(TEST_ENV_DIR, initial_build=True)
        await lsp.start()
        await lsp.close()

    async def test_get_env(self):
        lsp = BaseLeanLSPClient(TEST_ENV_DIR, initial_build=False)
        await lsp.start()
        env = await lsp.get_env()
        exp = [
            "ELAN",
            "ELAN_HOME",
            "ELAN_TOOLCHAIN",
            "LAKE",
            "LAKE_HOME",
            "LAKE_PKG_URL_MAP",
            "LEAN",
            "LEAN_GITHASH",
            "LEAN_SYSROOT",
            "LEAN_AR",
            "LEAN_CC",
            "LEAN_PATH",
            "LEAN_SRC_PATH",
            "PATH",
            "LD_LIBRARY_PATH",
        ]
        self.assertEqual(sorted(list(env.keys())), sorted(exp))

        env = await lsp.get_env(return_dict=False)
        self.assertEqual(type(env), str)

        await lsp.close()


class TestBaseClientAsync(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = BaseLeanLSPClient(TEST_ENV_DIR)
        await self.client.start()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_initialize(self):
        self.assertIsNotNone(self.client.token_processor)
