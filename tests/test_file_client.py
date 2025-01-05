from pprint import pprint
import unittest

from leanclient import SingleFileClient, LeanLSPClient

from run_tests import TEST_ENV_DIR, TEST_FILE_PATH


class TestSingleFileClient(unittest.TestCase):
    def setUp(self):
        self.client = LeanLSPClient(TEST_ENV_DIR, initial_build=False)

    def tearDown(self):
        self.client.close()

    def test_creation(self):
        # Instantiate a SingleFileClient
        sfc = SingleFileClient(self.client, TEST_FILE_PATH)
        self.assertEqual(sfc.file_path, TEST_FILE_PATH)
        res = sfc.get_goal(9, 15)
        assert "⊢" in res["goals"][0]

        sfc.close_file(blocking=True)  # Just to test the method

        # Create from a client
        sfc2 = self.client.create_file_client(TEST_FILE_PATH)
        self.assertEqual(sfc2.file_path, TEST_FILE_PATH)
        res2 = sfc.get_goal(9, 15)
        self.assertEqual(res, res2)

    def test_requests(self):
        sfc = self.client.create_file_client(TEST_FILE_PATH)
        res = []
        res.append(sfc.get_completion(9, 15))
        res.append(sfc.get_completion_item_resolve(res[0][0]))
        res.append(sfc.get_hover(4, 4))
        res.append(sfc.get_declaration(6, 4))
        res.append(sfc.get_definition(1, 29))
        res.append(sfc.get_references(9, 24))
        res.append(sfc.get_type_definition(1, 36))
        res.append(sfc.get_document_symbol())
        res.append(sfc.get_document_highlight(9, 8))
        res.append(sfc.get_semantic_tokens())
        res.append(sfc.get_semantic_tokens_range(0, 0, 10, 10))
        res.append(sfc.get_folding_range())
        res.append(sfc.get_goal(9, 15))
        res.append(sfc.get_term_goal(9, 15))
        assert all(res)
