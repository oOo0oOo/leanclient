import os
import collections
from pprint import pprint
import subprocess
from typing import NamedTuple

import selectors
import orjson

from leanclient.config import (
    LEAN_FILE_PATH,
    MAX_SYNCED_FILES,
    LAKE_ENV_DIR,
)
from leanclient.env_setup import install_env
from leanclient.utils import SemanticTokenProcessor


class DocumentContentChange(NamedTuple):
    text: str
    start: list[int]
    end: list[int]

    def get_dict(self) -> dict:
        return {
            "text": self.text,
            "range": {
                "start": {"line": self.start[0], "character": self.start[1]},
                "end": {"line": self.end[0], "character": self.end[1]},
            },
        }


class LeanLanguageServer:
    """Thin wrapper around the Lean language server.

    Also sets up and builds a new lake env if not present.
    In the future, setup will be factored out, allowing users to run this in their custom projects.

    NOTE: This wrapper is blocking even though the language server is parallel.
    We could use architecture similar to multilspy in the future.

    Args:
            use_mathlib (bool): Whether to include mathlib in the environment.
            starting_file_path (str): If not None, copies the contents of this file to the base lean path.
    """

    def __init__(self, use_mathlib: bool = False, starting_file_path: str = None):
        self.lake_dir = os.path.abspath(LAKE_ENV_DIR) + "/"
        self.request_id = 0
        self.synced_files = collections.OrderedDict()

        self._setup_env(use_mathlib, starting_file_path)

        # Run language server in a process
        self.process = subprocess.Popen(
            "lake serve",
            shell=True,
            cwd=self.lake_dir,
            stdout=subprocess.PIPE,
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.stdin = self.process.stdin
        self.stdout = self.process.stdout
        self.stderr = self.process.stderr

        # Use selectors to read stderr non-blocking
        self.stderr_selector = selectors.DefaultSelector()
        self.stderr_selector.register(self.stderr, selectors.EVENT_READ)

        # Send initialization request, surprisingly no params required
        results = self._send_request("initialize", {"processId": os.getpid()})
        server_info = results[-1]["result"]
        legend = server_info["capabilities"]["semanticTokensProvider"]["legend"]
        self.token_processor = SemanticTokenProcessor(legend["tokenTypes"])

        self._send_notification("initialized", {})

    def _setup_env(self, use_mathlib: bool = False, starting_file_path: str = None):
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
        self.stderr_selector.unregister(self.stderr)
        self.stderr.close()
        self.stdout.close()
        self.stdin.close()
        self.process.wait()

    def local_to_uri(self, file_name: str) -> str:
        return f"file://{self.lake_dir}{file_name}"

    # LANGUAGE SERVER INTERACTIONS
    def _read_stdout(self) -> dict:
        """Read the next message from the language server."""
        header = self.stdout.readline().decode("ascii")

        # Handle EOF: Return contents of stderr
        if not header:
            line = ""
            if self.stderr_selector.select(timeout=0.05):
                line = self.stderr.readline().decode("utf-8")
            raise EOFError(f"Language server has closed. Lake error message:\n{line}")

        # Parse message
        content_length = int(header.split(":")[1])
        next(self.stdout)
        resp = orjson.loads(self.stdout.read(content_length))

        # Display error messages from language server
        if "error" in resp:
            print("RPC Error Message:\n", resp["error"], flush=True)

        return resp

    def _send_request(self, method: str, params: dict) -> list[dict]:
        """Send a request to the language server.

        This includes an id in the rpc, and waits for a response with the same id.

        Returns:
            list[dict]: List of responses, the last one being the final response
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

    def _wait_for_diagnostics(self, uris: list[str]) -> dict:
        # waitForDiagnostics in series; Parallel requests are not reliable?
        responses = []
        for uri in uris:
            responses += self._send_request(
                "textDocument/waitForDiagnostics", {"uri": uri, "version": 1}
            )
            result = responses[-1]
            while True:
                # Could also require: result.get("id") == self.request_id - 1
                # Currently works bc the return value of waitForDiagnostics is `{}` (a bit unusual and therefore unique?)
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
            errors = [diag["message"] for diag in diags if diag["severity"] == 1]
            warnings = [diag["message"] for diag in diags if diag["severity"] == 2]
            diagnostics[uri] = [errors, warnings]
        return [diagnostics[uri] for uri in uris]

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

        return self._wait_for_diagnostics(uris)

    def update_file(self, uri: str, changes: list[DocumentContentChange]) -> list:
        """Update a file in the language server.

        This function blocks until the file waitForDiagnostics returns.
        """
        params = {"textDocument": {"uri": uri}}
        params["textDocument"]["languageId"] = "lean"
        params["textDocument"]["version"] = 1
        params["contentChanges"] = [c.get_dict() for c in changes]
        self._send_notification("textDocument/didChange", params)

        return self._wait_for_diagnostics([uri])[0]

    def _close_files(self, uris: list[str], blocking: bool = False):
        """Close files in the language server.

        This function blocks until publishDiagnostics is received for all files.

        Args:
            uris (list[str]): List of URIs to close.
            blocking (bool): Not blocking is a bit risky
        """
        # Only close if file is open
        uris = [uri for uri in uris if uri in self.synced_files]
        for uri in uris:
            params = {"textDocument": {"uri": uri}}
            self._send_notification("textDocument/didClose", params)

        # Wait for published diagnostics
        if blocking:
            waiting_uris = set(uris)
            while waiting_uris:
                resp = self._read_stdout()
                if resp and resp.get("method") == "textDocument/publishDiagnostics":
                    waiting_uris.discard(resp["params"]["uri"])

    def sync_files(self, uris: list[str]) -> list[list]:
        """Make files available to the language server if not already.

        Args:
            uris (list[str]): List of URIs to sync.

        Returns:
            list[list]: List of diagnostics for each file
        """
        if len(uris) > MAX_SYNCED_FILES:
            print(
                f"Warning! Should not sync more than {MAX_SYNCED_FILES} files at once."
            )

        # Open new files
        new_uris = [uri for uri in uris if uri not in self.synced_files]
        if new_uris:
            diagnostics = self._open_files(new_uris)
            self.synced_files.update(zip(new_uris, diagnostics))

        # Remove files if over limit
        remove_count = max(0, len(self.synced_files) - MAX_SYNCED_FILES)
        if remove_count > 0:
            removable_uris = [uri for uri in self.synced_files if uri not in uris]
            removable_uris = removable_uris[:remove_count]
            self._close_files(removable_uris)
            for uri in removable_uris:
                del self.synced_files[uri]

        return [self.synced_files[uri] for uri in uris]

    def sync_file(self, uri: str) -> list:
        """Make a file available to the language server if not already."""
        return self.sync_files([uri])[0]

    def _send_request_document(self, uri: str, method: str, params: dict) -> dict:
        """Send request regarding a document.
        Mainly used by other methods in this class."""
        self.sync_file(uri)
        params["textDocument"] = {"uri": uri}
        results = self._send_request(method, params)
        return results[-1]["result"]

    # LANGUAGE SERVER API
    # https://github.com/leanprover/lean4/blob/master/src/Lean/Server/FileWorker/RequestHandling.lean#L710

    def request_completion(self, uri: str, line: int, character: int) -> dict:
        return self._send_request_document(
            uri,
            "textDocument/completion",
            {"position": {"line": line, "character": character}},
        )

    def request_completion_item_resolve(self, uri: str, item: dict) -> dict:
        return self._send_request_document(
            uri,
            "completionItem/resolve",
            item,
        )

    def request_hover(self, uri: str, line: int, character: int) -> dict:
        return self._send_request_document(
            uri,
            "textDocument/hover",
            {"position": {"line": line, "character": character}},
        )

    def request_declaration(self, uri: str, line: int, character: int) -> dict:
        return self._send_request_document(
            uri,
            "textDocument/declaration",
            {"position": {"line": line, "character": character}},
        )

    def request_definition(self, uri: str, line: int, character: int) -> dict:
        return self._send_request_document(
            uri,
            "textDocument/definition",
            {"position": {"line": line, "character": character}},
        )

    def request_references(self, uri: str, line: int, character: int) -> dict:
        return self._send_request_document(
            uri,
            "textDocument/references",
            {
                "position": {"line": line, "character": character},
                "context": {"includeDeclaration": True},
            },
        )

    def request_type_definition(self, uri: str, line: int, character: int) -> dict:
        return self._send_request_document(
            uri,
            "textDocument/typeDefinition",
            {"position": {"line": line, "character": character}},
        )

    def request_document_highlight(self, uri: str, line: int, character: int) -> dict:
        return self._send_request_document(
            uri,
            "textDocument/documentHighlight",
            {"position": {"line": line, "character": character}},
        )

    def request_document_symbol(self, uri: str) -> dict:
        return self._send_request_document(uri, "textDocument/documentSymbol", {})

    def request_semantic_tokens_full(self, uri: str) -> list:
        res = self._send_request_document(uri, "textDocument/semanticTokens/full", {})
        return self.token_processor(res["data"])

    def request_semantic_tokens_range(
        self,
        uri: str,
        start_line: int,
        start_character: int,
        end_line: int,
        end_character: int,
    ) -> list:
        res = self._send_request_document(
            uri,
            "textDocument/semanticTokens/range",
            {
                "range": {
                    "start": {"line": start_line, "character": start_character},
                    "end": {"line": end_line, "character": end_character},
                }
            },
        )
        return self.token_processor(res["data"])

    def request_folding_range(self, uri: str) -> dict:
        return self._send_request_document(uri, "textDocument/foldingRange", {})

    def request_plain_goal(self, uri: str, line: int, character: int) -> dict:
        return self._send_request_document(
            uri,
            "$/lean/plainGoal",
            {"position": {"line": line, "character": character}},
        )

    def request_plain_term_goal(self, uri: str, line: int, character: int) -> dict:
        return self._send_request_document(
            uri,
            "$/lean/plainTermGoal",
            {"position": {"line": line, "character": character}},
        )

    # CUSTOM METHODS
    def get_sorries(self, uri: str) -> list[list]:
        """Currently only detects sorries in tactics (limitation by language server)."""
        semantic = self.request_semantic_tokens_full(uri)
        return [t[:3] for t in semantic if t[3] == "leanSorryLike"]
