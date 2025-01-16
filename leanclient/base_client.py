import os
import pathlib
from pprint import pprint
import subprocess

import select
import orjson

from .utils import SemanticTokenProcessor


LEN_URI_PREFIX = 7
IGNORED_METHODS = {
    "workspace/didChangeWatchedFiles",
    "workspace/semanticTokens/refresh",
    "client/registerCapability",
}


class BaseLeanLSPClient:
    """BaseLeanLSPClient runs a language server in a subprocess.

    See :meth:`leanclient.client.LeanLSPClient` for more information.
    """

    def __init__(
        self,
        project_path: str,
        initial_build: bool = True,
        print_warnings: bool = True,
    ):
        self.print_warnings = print_warnings
        self.project_path = os.path.abspath(project_path) + "/"
        self.len_project_uri = len(self.project_path) + LEN_URI_PREFIX
        self.request_id = 0

        if initial_build:
            subprocess.run(["lake", "build"], cwd=self.project_path, check=True)

        # Run the lean4 language server in a subprocess
        self.process = subprocess.Popen(
            ["lake", "serve"],
            cwd=self.project_path,
            stdout=subprocess.PIPE,
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.stdin = self.process.stdin
        self.stdout = self.process.stdout

        # Check stderr for any errors
        error = self._read_stderr_non_blocking()
        if error:
            print("Process started with stderr message:\n", error)

        # Initialize language server. Options can be found here:
        # https://github.com/leanprover/lean4/blob/a955708b6c5f25e7f9c9ae7b951f8f3d5aefe377/src/Lean/Data/Lsp/InitShutdown.lean
        self._send_request_rpc(
            "initialize",
            {
                "processId": os.getpid(),
                "rootUri": self._local_to_uri(self.project_path),
                "initializationOptions": {
                    "editDelay": 1  # It seems like this has no effect.
                },
            },
            is_notification=False,
        )
        server_info = self._read_stdout()["result"]

        legend = server_info["capabilities"]["semanticTokensProvider"]["legend"]
        self.token_processor = SemanticTokenProcessor(legend["tokenTypes"])

        self._send_notification("initialized", {})

    def close(self):
        """Always close the client when done!

        Terminates the language server process and close all pipes.
        """
        self.process.terminate()
        self.process.stderr.close()
        self.stdout.close()
        self.stdin.close()
        self.process.wait()

    # URI HANDLING
    def _local_to_uri(self, local_path: str) -> str:
        """Convert a local file path to a URI.

        User API is based on local file paths (relative to project path) but internally we use URIs.
        Example:

        - local path:  MyProject/LeanFile.lean
        - URI:         file:///abs/to/project_path/MyProject/LeanFile.lean

        Args:
            local_path (str): Relative file path.

        Returns:
            str: URI representation of the file.
        """
        return pathlib.Path(self.project_path, local_path).as_uri()

    def _locals_to_uris(self, local_paths: list[str]) -> list[str]:
        """See :meth:`_local_to_uri`"""
        return [
            pathlib.Path(self.project_path, local_path).as_uri()
            for local_path in local_paths
        ]

    def _uri_to_abs(self, uri: str) -> str:
        """See :meth:`_local_to_uri`"""
        return uri[LEN_URI_PREFIX:]

    def _uri_to_local(self, uri: str) -> str:
        """See :meth:`_local_to_uri`"""
        return uri[self.len_project_uri :]

    # LANGUAGE SERVER RPC INTERACTION
    def _read_stdout(self) -> dict:
        """Read the next message from the language server.

        This is the main blocking function in this synchronous client.

        Returns:
            dict: JSON response from the language server.
        """
        header = self.stdout.readline().decode("ascii")

        # Handle EOF: Return contents of stderr (non-blocking using select)
        if not header:
            line = self._read_stderr_non_blocking()
            if line:
                line = "lake stderr message:\n" + line
            if not line:
                line = "No lake stderr message."
            self.close()
            raise EOFError(f"Language server has closed. {line}")

        # Parse message
        content_length = int(header.split(":")[1])
        next(self.stdout)
        return orjson.loads(self.stdout.read(content_length))

    def _read_stderr_non_blocking(self, timeout: float = 0.00001) -> str:
        """Read the next message from the language server's stderr.

        Args:
            timeout (float): Time to wait for stderr message.

        Returns:
            str: Message from the language server's stderr.
        """
        stderr = self.process.stderr
        if select.select([stderr], [], [], timeout)[0]:
            return stderr.readline().decode("utf-8")
        return ""

    def _send_request_rpc(
        self, method: str, params: dict, is_notification: bool
    ) -> int | None:
        """Send a JSON RPC request to the language server.

        Args:
            method (str): Method name.
            params (dict): Parameters for the method.
            is_notification (bool): Whether the request is a notification.

        Returns:
            int | None: Id of the request if it is not a notification.
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

        if not is_notification:
            return self.request_id - 1

    def _send_notification(self, method: str, params: dict):
        """Send a notification to the language server.

        Args:
            method (str): Method name.
            params (dict): Parameters for the method.
        """
        self._send_request_rpc(method, params, is_notification=True)

    def _wait_for_diagnostics(self, uris: list[str], timeout: float = 1) -> list:
        """Wait until `waitForDiagnostics` returns or an rpc error occurs.

        This should only be used right after opening or updating files not to miss any responses.
        Returns either diagnostics or an error dict for each file.

        Sometimes `waitForDiagnostics` doesn't return. We need to check for "rpc errors", "fatal errors" and use a timeout..
        See source for more details.

        **Example diagnostics**:

        .. code-block:: python

            [
            # For each file:
            [
                {
                    'message': "declaration uses 'sorry'",
                    'severity': 2,
                    'source': 'Lean 4',
                    'range': {'end': {'character': 19, 'line': 13},
                                'start': {'character': 8, 'line': 13}},
                    'fullRange': {'end': {'character': 19, 'line': 13},
                                'start': {'character': 8, 'line': 13}}
                },
                {
                    'message': "unexpected end of input; expected ':'",
                    'severity': 1,
                    'source': 'Lean 4',
                    'range': {'end': {'character': 0, 'line': 17},
                                'start': {'character': 0, 'line': 17}},
                    'fullRange': {'end': {'character': 0, 'line': 17},
                                'start': {'character': 0, 'line': 17}}
                },
                # ...
            ], #...
            ]

        Args:
            uris (list[str]): List of URIs to wait for diagnostics on.
            timeout (float): Time to wait for diagnostics. Rarely exceeded.

        Returns:
            list: List of diagnostic messages or errors.
        """
        TIMEOUT_SHORT = 0.01

        # Request waitForDiagnostics for each file
        rid_to_uri = {}
        for uri in uris:
            rid = self._send_request_rpc(
                "textDocument/waitForDiagnostics",
                {"uri": uri, "version": 1},
                is_notification=False,
            )
            rid_to_uri[rid] = uri

        num_missing = len(uris)
        errored = set()
        diagnostics = {}
        while num_missing > 0:
            # Non-blocking read, `waitForDiagnostics` doesn't always return e.g. "unfinished comment"
            # Timeout is shortened if all remaining files have errored
            tmt = TIMEOUT_SHORT if len(errored) == num_missing else timeout
            if select.select([self.stdout], [], [], tmt)[0]:
                res = self._read_stdout()
            else:
                break

            method = res.get("method")

            # Capture diagnostics
            if method == "textDocument/publishDiagnostics":
                uri = res["params"]["uri"]

                # Don't overwrite errors
                if uri in diagnostics and uri in errored:
                    continue

                diagnostics[uri] = res["params"]["diagnostics"]
                continue

            # `waitForDiagnostics` has returned
            elif res.get("result", True) == {}:
                num_missing -= 1
                continue

            # RPC error
            elif "error" in res:
                uri = rid_to_uri.get(res.get("id"))
                if uri:
                    diagnostics[uri] = res
                errored.add(uri)
                continue

            if method in IGNORED_METHODS:
                continue

            # assert res.get("method") == "$/lean/fileProgress", res

            # Check for fatalError from fileProgress. See here:
            # https://github.com/leanprover/lean4/blob/8791a9ce069d6dc87f7cccc4387545b1110c89bd/src/Lean/Data/Lsp/Extra.lean#L55
            proc = res["params"]["processing"]
            if proc and proc[-1]["kind"] == 2:
                uri = rid_to_uri.get(res.get("id"))
                if uri:
                    errored.add(uri)
                    if not diagnostics.get(uri):
                        msg = f"leanclient: Received LeanFileProgressKind.fatalError from language server."
                        res["error"] = {"message": msg}
                        diagnostics[uri] = res

        return [diagnostics.get(uri, []) for uri in uris]

    # HELPERS
    def get_env(self, return_dict: bool = True) -> dict | str:
        """Get the environment variables of the project.

        Args:
            return_dict (bool): Return as dict or string.

        Returns:
            dict | str: Environment variables.
        """
        response = subprocess.run(
            ["lake", "env"], cwd=self.project_path, capture_output=True, text=True
        )
        if not return_dict:
            return response.stdout

        env = {}
        for line in response.stdout.split("\n"):
            if not line:
                continue
            key, value = line.split("=", 1)
            env[key] = value
        return env
