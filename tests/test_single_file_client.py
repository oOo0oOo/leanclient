from pprint import pprint
import unittest

from leanclient import SingleFileClient, LeanLSPClient
from leanclient.utils import DocumentContentChange

from run_tests import TEST_ENV_DIR, TEST_FILE_PATH


class TestSingleFileClient(unittest.TestCase):
    def setUp(self):
        self.client = LeanLSPClient(
            TEST_ENV_DIR, initial_build=False, print_warnings=False
        )

    def tearDown(self):
        self.client.close()

    def test_method_overlap(self):
        method_client = dir(LeanLSPClient)
        method_single = dir(SingleFileClient)

        # Missing methods in single file client
        missing = [
            m for m in method_client if m not in method_single and not m.startswith("_")
        ]
        ok_missing = [
            "close",
            "close_files",
            "create_file_client",
            "open_files",
            "get_env",
        ]
        missing = set(missing) - set(ok_missing)
        assert not missing, f"Missing methods in SingleFileClient: {missing}"

    def test_creation(self):
        # Instantiate a SingleFileClient
        sfc = SingleFileClient(self.client, TEST_FILE_PATH)
        self.assertEqual(sfc.file_path, TEST_FILE_PATH)
        res = sfc.get_goal(9, 15)
        assert "⊢" in res["goals"][0]

        sfc.close_file()  # Just to test the method

        # Create from a client
        sfc2 = self.client.create_file_client(TEST_FILE_PATH)
        self.assertEqual(sfc2.file_path, TEST_FILE_PATH)
        res2 = sfc.get_goal(9, 15)
        self.assertEqual(res, res2)

    def test_requests(self):
        sfc = self.client.create_file_client(TEST_FILE_PATH)
        res = []
        res.append(sfc.get_completions(9, 15))
        res.append(sfc.get_completion_item_resolve(res[0][0]))
        res.append(sfc.get_hover(4, 4))
        res.append(sfc.get_declarations(6, 4))
        res.append(sfc.get_definitions(1, 29))
        # res.append(sfc.get_references(9, 24))
        res.append(sfc.get_type_definitions(1, 36))
        res.append(sfc.get_document_symbols())
        res.append(sfc.get_document_highlights(9, 8))
        res.append(sfc.get_semantic_tokens())
        res.append(sfc.get_semantic_tokens_range(0, 0, 10, 10))
        res.append(sfc.get_folding_ranges())
        res.append(sfc.get_goal(9, 15))
        res.append(sfc.get_term_goal(9, 15))
        res.append(sfc.get_diagnostics())
        res.append(sfc.get_file_content())
        assert all(res)

        # item = sfc.get_call_hierarchy_items(1, 15)[0]
        # assert item["data"]["name"] == "add_zero_custom"
        # inc = sfc.get_call_hierarchy_incoming(item)
        # out = sfc.get_call_hierarchy_outgoing(item)
        # assert inc == []
        # assert len(out) >= 1, f"Expected at least 1 outgoing call, got {len(out)}"

        sfc.update_file([DocumentContentChange("change", (0, 0), (0, 1))])
        # res = sfc.get_code_actions(0, 0, 10, 10)
        # res = sfc.get_code_action_resolve({})
