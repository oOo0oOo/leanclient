import unittest

from leanclient.base_client import BaseLeanLSPClient

from run_tests import TEST_ENV_DIR


class TestBaseClient(unittest.TestCase):
    def test_initial_build(self):
        lsp = BaseLeanLSPClient(TEST_ENV_DIR, initial_build=True, print_warnings=False)
        lsp.close()

    def test_get_env(self):
        lsp = BaseLeanLSPClient(TEST_ENV_DIR, initial_build=False, print_warnings=False)
        env = lsp.get_env()
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

        env = lsp.get_env(return_dict=False)
        self.assertEqual(type(env), str)

        lsp.close()
