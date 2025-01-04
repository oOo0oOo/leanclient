import os
import collections
from pprint import pprint
import select
import subprocess

import orjson

from .utils import SemanticTokenProcessor, DocumentContentChange


class LeanLSPClient:
    """LeanLSPClient is a thin wrapper around the Lean language server.

    It interacts with a subprocess (`lake serve`) using the Language Server Protocol (LSP).
    This wrapper is blocking and synchronous.

    Args:
        project_path (str): Path to the root of the Lean project.
        max_opened_files (int): Maximum number of files to keep open at once.
    """

    def __init__(self, project_path: str, max_opened_files: int = 8):
        self.project_path = os.path.abspath(project_path) + "/"
        self.len_project_uri = len(self.project_path) + 7
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

    # URI HANDLING
    # Users will use local file paths (relative to project path) but internally we use absolute URIs.
    # E.g. ".lake/packages/LeanFile.lean" -> "file:///path/to/project/.lake/packages/LeanFile.lean" (URI)
    def _local_to_uri(self, local_path: str) -> str:
        return "file://" + self.project_path + local_path

    def _locals_to_uris(self, local_paths: list[str]) -> list[str]:
        return [
            "file://" + self.project_path + local_path for local_path in local_paths
        ]

    def _uri_to_abs(self, uri: str) -> str:
        return uri[7:]

    def _uri_to_local(self, uri: str) -> str:
        return uri[self.len_project_uri :]

    # LANGUAGE SERVER RPC INTERACTION
    def _read_stdout(self) -> dict:
        """Read the next message from the language server. Blocking.

        Returns:
            dict: JSON response from the language server.
        """
        header = self.stdout.readline().decode("ascii")

        # Handle EOF: Return contents of stderr (non-blocking using select)
        if not header:
            stderr = self.process.stderr
            line = "No lake stderr message."
            if select.select([stderr], [], [], 0.05)[0]:
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
        """Send a JSON rpc request to the language server.

        Args:
            method (str): Method name.
            params (dict): Parameters for the method.
            is_notification (bool): Whether the request is a notification.
        """
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

        Args:
            method (str): Method name.
            params (dict): Parameters for the method.

        Returns:
            list[dict]: List of responses in the order they were received.
        """
        self._send_request_rpc(method, params, is_notification=False)
        rid = self.request_id - 1

        result = self._read_stdout()
        results = [result]
        while result.get("id") != rid and "error" not in result:
            result = self._read_stdout()
            results.append(result)

        return results

    def _send_request_document(self, path: str, method: str, params: dict) -> dict:
        """Send request about a document.

        NOTE: This function drops all intermediate responses and only returns the final response.

        Args:
            path (str): Relative file path.
            method (str): Method name.
            params (dict): Parameters for the method.

        Returns:
            dict: Final response.
        """
        self.open_file(path)
        params["textDocument"] = {"uri": self._local_to_uri(path)}
        results = self._send_request(method, params)
        return results[-1]["result"]

    def _send_notification(self, method: str, params: dict):
        """Send a notification to the language server.

        Args:
            method (str): Method name.
            params (dict): Parameters for the method.
        """
        self._send_request_rpc(method, params, is_notification=True)

    def _wait_for_diagnostics(self, uris: list[str]) -> list[dict]:
        """Wait until `waitForDiagnostics` returns or an rpc error occurs.

        Args:
            uris (list[str]): List of URIs to wait for diagnostics on.

        Returns:
            list[dict]: List of responses in the order they were received.
        """
        # Waiting in series; Parallel requests are not reliable?
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
    def _open_files_rpc(self, paths: list[str]) -> list:
        """Open files in the language server.

        This function blocks until the file waitForDiagnostics returns.

        Args:
            paths (list[str]): List of relative file paths.
            return_diagnostics (bool): Whether to return diagnostics for each file.

        Returns:
            list: List of diagnostics for each file: [[errors, warnings]]
        """
        uris = self._locals_to_uris(paths)
        for uri in uris:
            params = {"textDocument": {"uri": uri}}
            with open(self._uri_to_abs(uri), "r") as f:
                params["textDocument"]["text"] = f.read()
            params["textDocument"]["languageId"] = "lean"
            params["textDocument"]["version"] = 1
            self._send_notification("textDocument/didOpen", params)

        return self._wait_for_diagnostics(uris)

    def open_files(self, paths: list[str]) -> list[list]:
        """Open files in the language server.

        Args:
            paths (list[str]): List of relative file paths to open.

        Returns:
            list[list]: List of diagnostics for each file: [[errors, warnings]]
        """
        if len(paths) > self.max_opened_files:
            print(
                f"Warning! Should not open more than {self.max_opened_files} files at once."
            )

        # Open new files
        new_files = [p for p in paths if p not in self.opened_files]
        if new_files:
            diagnostics = self._open_files_rpc(new_files)
            self.opened_files.update(zip(new_files, diagnostics))

        # Remove files if over limit
        remove_count = max(0, len(self.opened_files) - self.max_opened_files)
        if remove_count > 0:
            removable_paths = [p for p in self.opened_files if p not in paths]
            removable_paths = removable_paths[:remove_count]
            self.close_files(removable_paths)
            for path in removable_paths:
                del self.opened_files[path]

        return [self.opened_files[path] for path in paths]

    def open_file(self, path: str) -> list:
        """Open a file in the language server if not already opened.

        Args:
            path (str): Relative file path to open.

        Returns:
            list: Diagnostics for file: [errors, warnings]
        """
        return self.open_files([path])[0]

    def update_file(self, path: str, changes: list[DocumentContentChange]) -> list:
        """Update a file in the language server.

        This function blocks until the file waitForDiagnostics returns.

        Args:
            path (str): Relative file path to update.
            changes (list[DocumentContentChange]): List of changes to apply.

        Returns:
            list: List of diagnostics: [errors, warnings]
        """
        uri = self._local_to_uri(path)
        params = {"textDocument": {"uri": uri}}
        params["textDocument"]["languageId"] = "lean"
        params["textDocument"]["version"] = 1
        params["contentChanges"] = [c.get_dict() for c in changes]
        self._send_notification("textDocument/didChange", params)

        return self._wait_for_diagnostics([uri])[0]

    def close_files(self, paths: list[str], blocking: bool = False):
        """Close files in the language server.

        Args:
            paths (list[str]): List of relative file paths to close.
            blocking (bool): Not blocking can be risky if you close files frequently.
        """
        # Only close if file is open
        paths = [p for p in paths if p in self.opened_files]
        uris = self._locals_to_uris(paths)
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

    def get_completion(self, path: str, line: int, character: int) -> dict | None:
        return self._send_request_document(
            path,
            "textDocument/completion",
            {"position": {"line": line, "character": character}},
        )

    def get_completion_item_resolve(self, item: dict) -> dict | None:
        uri = item["data"]["params"]["textDocument"]["uri"]
        return self._send_request_document(
            self._uri_to_local(uri), "completionItem/resolve", item
        )

    def get_hover(self, path: str, line: int, character: int) -> dict | None:
        return self._send_request_document(
            path,
            "textDocument/hover",
            {"position": {"line": line, "character": character}},
        )

    def get_declaration(self, path: str, line: int, character: int) -> list:
        return self._send_request_document(
            path,
            "textDocument/declaration",
            {"position": {"line": line, "character": character}},
        )

    def get_definition(self, path: str, line: int, character: int) -> list:
        return self._send_request_document(
            path,
            "textDocument/definition",
            {"position": {"line": line, "character": character}},
        )

    def get_references(self, path: str, line: int, character: int) -> list:
        return self._send_request_document(
            path,
            "textDocument/references",
            {
                "position": {"line": line, "character": character},
                "context": {"includeDeclaration": True},
            },
        )

    def get_type_definition(self, path: str, line: int, character: int) -> list:
        return self._send_request_document(
            path,
            "textDocument/typeDefinition",
            {"position": {"line": line, "character": character}},
        )

    def get_document_highlight(self, path: str, line: int, character: int) -> list:
        return self._send_request_document(
            path,
            "textDocument/documentHighlight",
            {"position": {"line": line, "character": character}},
        )

    def get_document_symbol(self, path: str) -> list:
        return self._send_request_document(path, "textDocument/documentSymbol", {})

    def get_semantic_tokens_full(self, path: str) -> list:
        res = self._send_request_document(path, "textDocument/semanticTokens/full", {})
        return self.token_processor(res["data"])

    def get_semantic_tokens_range(
        self,
        path: str,
        start_line: int,
        start_character: int,
        end_line: int,
        end_character: int,
    ) -> list:
        res = self._send_request_document(
            path,
            "textDocument/semanticTokens/range",
            {
                "range": {
                    "start": {"line": start_line, "character": start_character},
                    "end": {"line": end_line, "character": end_character},
                }
            },
        )
        return self.token_processor(res["data"])

    def get_folding_range(self, path: str) -> list:
        return self._send_request_document(path, "textDocument/foldingRange", {})

    def get_plain_goal(self, path: str, line: int, character: int) -> dict | None:
        return self._send_request_document(
            path,
            "$/lean/plainGoal",
            {"position": {"line": line, "character": character}},
        )

    def get_plain_term_goal(self, path: str, line: int, character: int) -> dict | None:
        return self._send_request_document(
            path,
            "$/lean/plainTermGoal",
            {"position": {"line": line, "character": character}},
        )
