import os
from pprint import pprint
import subprocess
import threading

import selectors
import orjson

from leanclient.config import (
    LEAN_FILE_PATH,
    MAX_SYNCED_FILES,
    LAKE_ENV_DIR,
)
from leanclient.env_setup import install_env


class LeanLanguageServer:
    """Thin wrapper around the Lean language server.

    Also sets up and builds a new lake env if not present.
    In the future, setup will be factored out, allowing users to run this in their custom projects.

    NOTE: This wrapper is blocking even though the language server is parallel.
    We could use architecture similar to multilspy in the future.

    Args:
            use_mathlib (bool): Whether to include mathlib in the environment.
            starting_file_path (str): If not None, copies the contents of this file to the base lean path.
            print_lake_errors (bool): Print lake errors to the stdout. This runs in a separate thread.
    """

    def __init__(
        self,
        use_mathlib: bool = False,
        starting_file_path: str = None,
        print_lake_errors: bool = False,
    ):
        self.lake_dir = os.path.abspath(LAKE_ENV_DIR) + "/"
        self.print_lake_errors = print_lake_errors
        self.request_id = 0
        self.synced_uris = []

        self.setup_env(use_mathlib, starting_file_path)

        # Run language server in a process
        self.process = subprocess.Popen(
            "lake serve",
            shell=True,
            cwd=self.lake_dir,
            stdout=subprocess.PIPE,
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE if print_lake_errors else subprocess.DEVNULL,
        )
        self.stdin = self.process.stdin
        self.stdout = self.process.stdout

        # Use selectors to read stdout and stderr non-blocking
        self.stdout_selector = selectors.DefaultSelector()
        self.stdout_selector.register(self.stdout, selectors.EVENT_READ)

        # Read stderr in a separate thread
        if print_lake_errors:
            self.stderr_selector = selectors.DefaultSelector()
            self.stderr_selector.register(self.process.stderr, selectors.EVENT_READ)

            def loop():
                while self.process.poll() is None:
                    line = self._read_stderr_non_blocking()
                    if line:
                        print(line)

            threading.Thread(target=loop).start()

        # Send initialization request, surprisingly no params required
        results = self._send_request("initialize", {"processId": os.getpid()})
        self.server_info = results[-1]["result"]
        self.token_legend = self.server_info["capabilities"]["semanticTokensProvider"][
            "legend"
        ]
        self.num_token_modifiers = len(self.token_legend["tokenModifiers"])

        self._send_notification("initialized", {})

    def setup_env(self, use_mathlib: bool = False, starting_file_path: str = None):
        # Create new environment
        if not os.path.exists(self.lake_dir):
            install_env(self.lake_dir, use_mathlib=use_mathlib)

        # Copy the starting file
        if starting_file_path:
            cmd = f"cp {starting_file_path} {self.lake_dir}{LEAN_FILE_PATH}"
            subprocess.run(cmd, shell=True)

        subprocess.run("lake build", shell=True, cwd=self.lake_dir)

    def close(self):
        """Close the language server and all associated resources."""
        self.process.terminate()
        self.stdout_selector.unregister(self.stdout)
        if self.print_lake_errors:
            self.stderr_selector.unregister(self.process.stderr)
            self.process.stderr.close()
        self.stdout.close()
        self.stdin.close()
        self.process.wait()

    def local_to_uri(self, file_name: str) -> str:
        return f"file://{self.lake_dir}{file_name}"

    # LANGUAGE SERVER INTERACTIONS
    def _read_stdout(self) -> dict:
        """Read the next message from the language server."""
        header = self.stdout.readline().decode("ascii")
        if header:
            content_length = int(header.split(":")[1])
            next(self.stdout)
            resp = orjson.loads(self.stdout.read(content_length))
        else:
            resp = {}

        if resp.get("error", ""):
            print("Error Message:", resp)
        return resp

    def _read_stdout_non_blocking(self, timeout: float = 0.001) -> dict | None:
        """Currently not required"""
        events = self.stdout_selector.select(timeout=timeout)
        return self._read_stdout() if events else None

    def _read_stderr_non_blocking(self, timeout: float = 0.025) -> dict | None:
        events = self.stderr_selector.select(timeout=timeout)
        return self.process.stderr.readline().decode("utf-8") if events else None

    def _send_request(self, method: str, params: dict) -> list[dict]:
        """Send a request to the language server.

        This includes and id, and waits for a response.

        Returns:
            list[dict] | None: List of responses, the last one being the final response, if not notification
        """
        self._send_raw_request(method, params, is_notification=False)
        rid = self.request_id - 1

        result = self._read_stdout()
        results = [result]
        while result.get("id") != rid:
            result = self._read_stdout()
            results.append(result)

        return results

    def _send_notification(self, method: str, params: dict):
        """Send a notification to the  language server."""
        self._send_raw_request(method, params, is_notification=True)

    def _send_raw_request(self, method: str, params: dict, is_notification: bool):
        """Send a JSON rpc request to the language server."""
        request = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            **({"id": self.request_id} if not is_notification else {}),
        }
        if not is_notification:
            self.request_id += 1

        body = orjson.dumps(request)
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        self.stdin.write(header + body)
        self.stdin.flush()

    def _open_files(self, uris: list[str]) -> list:
        """Open files in the language server.

        This function blocks until the file waitForDiagnostics returns.

        Args:
            uris (list[str]): List of URIs to open.
            return_diagnostics (bool): Whether to return diagnostics for each file.

        Returns:
            list: List of diagnostics for each file.
        """
        for uri in uris:
            params = {"textDocument": {"uri": uri}}
            with open(uri[7:], "r") as f:  # Remove "file://" prefix
                params["textDocument"]["text"] = f.read()
            params["textDocument"]["languageId"] = "lean"
            params["textDocument"]["version"] = 1
            self._send_notification("textDocument/didOpen", params)

        # waitForDiagnostics in series; Parallel requests are not reliable?
        responses = []
        for uri in uris:
            responses += self._send_request(
                "textDocument/waitForDiagnostics", {"uri": uri, "version": 1}
            )
            result = responses[-1]
            while True:
                # Could also require: result.get("id") == self.request_id - 1
                if result.get("result", True) == {}:
                    break
                result = self._read_stdout()
                responses.append(result)

        diagnostics = {
            resp["params"]["uri"]: resp["params"]["diagnostics"]
            for resp in responses
            if resp.get("method") == "textDocument/publishDiagnostics"
        }

        for uri, diags in diagnostics.items():
            if diags:
                warnings = [diag["message"] for diag in diags if diag["severity"] == 2]
                errors = [diag["message"] for diag in diags if diag["severity"] == 1]
                diagnostics[uri] = [warnings, errors]

        return [diagnostics.get(uri, []) for uri in uris]

    def _close_files(self, uris: list[str]):
        """Close files in the language server.

        This function blocks until publishDiagnostics is received for all files."""
        for uri in uris:
            params = {"textDocument": {"uri": uri}}
            self._send_notification("textDocument/didClose", params)

        # Wait for published diagnostics
        waiting_uris = set(uris)
        while waiting_uris:
            resp = self._read_stdout()
            if resp and resp.get("method") == "textDocument/publishDiagnostics":
                waiting_uris.discard(resp["params"]["uri"])

    def sync_files(self, uris: list[str]) -> list[list | None]:
        """Make files available to the language server if not already.

        Args:
            uris (list[str]): List of URIs to sync.

        Returns:
            list[list | None]: List of diagnostics for each file or None
        """
        uris_to_add = [u for u in uris if u not in self.synced_uris]
        if not uris_to_add:
            return [None] * len(uris)
        diags = {u: [] for u in uris}

        # Remove oldest synced files which are not in uris
        removable_uris = [u for u in self.synced_uris if u not in uris_to_add]
        to_remove = min(len(removable_uris), len(self.synced_uris) - MAX_SYNCED_FILES)
        if to_remove:
            remove_uris = removable_uris[:to_remove]
            self._close_files(remove_uris)
            self.synced_uris = [u for u in self.synced_uris if u not in remove_uris]

        diagnostics = self._open_files(uris_to_add)
        self.synced_uris += uris_to_add
        for uri, diag in zip(uris_to_add, diagnostics):
            diags[uri] = diag
        return [diags[u] for u in uris]

    def sync_file(self, uri: str) -> list:
        """Make a file available to the language server if not already."""
        return self.sync_files([uri])[0]

    def send_request_document(self, uri: str, method: str, params: dict) -> dict:
        """Send request regarding a document.
        Mainly used by other methods in this class."""
        self.sync_file(uri)
        params["textDocument"] = {"uri": uri}
        results = self._send_request(method, params)
        return results[-1]["result"]

    # LANGUAGE SERVER API
    # https://github.com/leanprover/lean4/blob/master/src/Lean/Server/FileWorker/RequestHandling.lean#L710

    def request_completion(self, uri: str, line: int, character: int) -> dict:
        return self.send_request_document(
            uri,
            "textDocument/completion",
            {"position": {"line": line, "character": character}},
        )

    def request_completion_item_resolve(self, uri: str, item: dict) -> dict:
        return self.send_request_document(
            uri,
            "completionItem/resolve",
            item,
        )

    def request_hover(self, uri: str, line: int, character: int) -> dict:
        return self.send_request_document(
            uri,
            "textDocument/hover",
            {"position": {"line": line, "character": character}},
        )

    def request_declaration(self, uri: str, line: int, character: int) -> dict:
        return self.send_request_document(
            uri,
            "textDocument/declaration",
            {"position": {"line": line, "character": character}},
        )

    def request_definition(self, uri: str, line: int, character: int) -> dict:
        return self.send_request_document(
            uri,
            "textDocument/definition",
            {"position": {"line": line, "character": character}},
        )

    def request_references(self, uri: str, line: int, character: int) -> dict:
        return self.send_request_document(
            uri,
            "textDocument/references",
            {
                "position": {"line": line, "character": character},
                "context": {"includeDeclaration": True},
            },
        )

    def request_type_definition(self, uri: str, line: int, character: int) -> dict:
        return self.send_request_document(
            uri,
            "textDocument/typeDefinition",
            {"position": {"line": line, "character": character}},
        )

    def request_document_highlight(self, uri: str, line: int, character: int) -> dict:
        return self.send_request_document(
            uri,
            "textDocument/documentHighlight",
            {"position": {"line": line, "character": character}},
        )

    def request_document_symbol(self, uri: str) -> dict:
        return self.send_request_document(uri, "textDocument/documentSymbol", {})

    def request_semantic_tokens_full(self, uri: str) -> list:
        res = self.send_request_document(uri, "textDocument/semanticTokens/full", {})
        return self._process_semantic_tokens(res["data"])

    def request_semantic_tokens_range(
        self,
        uri: str,
        start_line: int,
        start_character: int,
        end_line: int,
        end_character: int,
    ) -> list:
        res = self.send_request_document(
            uri,
            "textDocument/semanticTokens/range",
            {
                "range": {
                    "start": {"line": start_line, "character": start_character},
                    "end": {"line": end_line, "character": end_character},
                }
            },
        )
        return self._process_semantic_tokens(res["data"])

    def _process_semantic_tokens(self, raw_response: list[int]) -> list:
        """Semantic token response is "compressed". This function is a reverse translation of:
        https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#semanticTokens_fullRequest
        """
        tokens = []
        prev_line = 0
        prev_start_char = 0
        for i in range(0, len(raw_response), 5):
            delta_line = raw_response[i]
            delta_start_char = raw_response[i + 1]
            length = raw_response[i + 2]
            token_type = raw_response[i + 3]
            token_modifiers = raw_response[i + 4]

            line = prev_line + delta_line
            start_char = (
                prev_start_char + delta_start_char
                if delta_line == 0
                else delta_start_char
            )

            token_modifiers_list = [
                self.token_legend["tokenModifiers"][j]
                for j in range(self.num_token_modifiers)
                if token_modifiers & (1 << j)
            ]

            tokens.append(
                [
                    line,
                    start_char,
                    length,
                    self.token_legend["tokenTypes"][token_type],
                    token_modifiers_list,
                ]
            )

            prev_line = line
            prev_start_char = start_char

        return tokens

    def request_folding_range(self, uri: str) -> dict:
        return self.send_request_document(uri, "textDocument/foldingRange", {})

    def request_plain_goal(self, uri: str, line: int, character: int) -> dict:
        return self.send_request_document(
            uri,
            "$/lean/plainGoal",
            {"position": {"line": line, "character": character}},
        )

    def request_plain_term_goal(self, uri: str, line: int, character: int) -> dict:
        return self.send_request_document(
            uri,
            "$/lean/plainTermGoal",
            {"position": {"line": line, "character": character}},
        )

    # CUSTOM METHODS
    def get_sorries(self, uri: str) -> list[list]:
        """Currently only detects sorries in tactics (limitation by language server)."""
        semantic = self.request_semantic_tokens_full(uri)
        return [t[:3] for t in semantic if t[3] == "leanSorryLike"]
