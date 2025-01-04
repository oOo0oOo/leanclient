import os
import collections
from pprint import pprint
import subprocess
from typing import NamedTuple

import selectors
import orjson

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
    """LeanLanguageServer is a thin wrapper around the Lean language server.

    It interacts with a subprocess (`lake serve`) using the Language Server Protocol (LSP).
    This wrapper is blocking and synchronous.

    Args:
        project_path (str): Path to the root of the Lean project.
        max_opened_files (int): Maximum number of files to keep open at once.
    """

    def __init__(self, project_path: str, max_opened_files: int = 8):
        self.project_path = os.path.abspath(project_path) + "/"
        self.max_opened_files = max_opened_files
        self.request_id = 0
        self.opened_files = collections.OrderedDict()

        subprocess.run("lake build", shell=True, cwd=self.project_path)

        # Run language server in a process
        self.process = subprocess.Popen(
            "lake serve",
            shell=True,
            cwd=self.project_path,
            stdout=subprocess.PIPE,
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.stdin = self.process.stdin
        self.stdout = self.process.stdout

        # Send initialization request, surprisingly no params required
        results = self._send_request("initialize", {"processId": os.getpid()})
        server_info = results[-1]["result"]
        legend = server_info["capabilities"]["semanticTokensProvider"]["legend"]
        self.token_processor = SemanticTokenProcessor(legend["tokenTypes"])

        self._send_notification("initialized", {})

    def close(self):
        """Terminate the language server process and close all pipes."""
        self.process.terminate()
        self.process.stderr.close()
        self.stdout.close()
        self.stdin.close()
        self.process.wait()

    def local_to_uri(self, file_path: str) -> str:
        return f"file://{self.project_path}{file_path}"

    # LANGUAGE SERVER RPC INTERACTION
    def _read_stdout(self) -> dict:
        """Read the next message from the language server. Blocking."""
        header = self.stdout.readline().decode("ascii")

        # Handle EOF: Return contents of stderr (non-blocking using selectors)
        if not header:
            stderr = self.process.stderr
            stderr_sel = selectors.DefaultSelector()
            stderr_sel.register(stderr, selectors.EVENT_READ)
            line = "No lake stderr message."
            if stderr_sel.select(timeout=0.05):
                line = "lake stderr message:\n" + stderr.readline().decode("utf-8")
            self.close()
            raise EOFError(f"Language server has closed. {line}")

        # Parse message
        content_length = int(header.split(":")[1])
        next(self.stdout)
        resp = orjson.loads(self.stdout.read(content_length))

        # Display RPC error messages (from language server)
        if "error" in resp:
            print("RPC Error Message:\n", resp)

        return resp

    def _send_request_rpc(self, method: str, params: dict, is_notification: bool):
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

    def _send_request(self, method: str, params: dict) -> list[dict]:
        """Send a request to the language server.

        Returns:
            list[dict]: List of responses, the last one being the final response
        """
        self._send_request_rpc(method, params, is_notification=False)
        rid = self.request_id - 1

        result = self._read_stdout()
        results = [result]
        while result.get("id") != rid and "error" not in result:
            result = self._read_stdout()
            results.append(result)

        return results

    def _send_request_document(self, uri: str, method: str, params: dict) -> dict:
        """Send request about a document."""
        self.open_file(uri)
        params["textDocument"] = {"uri": uri}
        results = self._send_request(method, params)
        return results[-1]["result"]

    def _send_notification(self, method: str, params: dict):
        """Send a notification to the language server."""
        self._send_request_rpc(method, params, is_notification=True)

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
                elif "error" in result:
                    return responses + [result]
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

    # OPEN/CLOSE FILES IN LANGUAGE SERVER
    def _open_files_rpc(self, uris: list[str]) -> list:
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

    def open_files(self, uris: list[str]) -> list[list]:
        """Open files in the language server.

        Args:
            uris (list[str]): List of URIs to open.

        Returns:
            list[list]: List of diagnostics for each file
        """
        if len(uris) > self.max_opened_files:
            print(
                f"Warning! Should not open more than {self.max_opened_files} files at once."
            )

        # Open new files
        new_uris = [uri for uri in uris if uri not in self.opened_files]
        if new_uris:
            diagnostics = self._open_files_rpc(new_uris)
            self.opened_files.update(zip(new_uris, diagnostics))

        # Remove files if over limit
        remove_count = max(0, len(self.opened_files) - self.max_opened_files)
        if remove_count > 0:
            removable_uris = [uri for uri in self.opened_files if uri not in uris]
            removable_uris = removable_uris[:remove_count]
            self.close_files(removable_uris)
            for uri in removable_uris:
                del self.opened_files[uri]

        return [self.opened_files[uri] for uri in uris]

    def open_file(self, uri: str) -> list:
        """Make a file available to the language server if not already."""
        return self.open_files([uri])[0]

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

    def close_files(self, uris: list[str], blocking: bool = False):
        """Close files in the language server.

        Args:
            uris (list[str]): List of URIs to close.
            blocking (bool): Not blocking is a bit risky
        """
        # Only close if file is open
        uris = [uri for uri in uris if uri in self.opened_files]
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

    # LANGUAGE SERVER API
    # https://github.com/leanprover/lean4/blob/master/src/Lean/Server/FileWorker/RequestHandling.lean#L710

    def request_completion(self, uri: str, line: int, character: int) -> dict:
        return self._send_request_document(
            uri,
            "textDocument/completion",
            {"position": {"line": line, "character": character}},
        )

    def request_completion_item_resolve(self, item: dict) -> dict:
        return self._send_request_document(
            item["data"]["params"]["textDocument"]["uri"],
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
