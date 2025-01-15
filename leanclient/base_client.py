import os
import collections
import pathlib
from pprint import pprint
import subprocess
import time

import select
import orjson

from .utils import SemanticTokenProcessor
from .single_file_client import SingleFileClient

LEN_URI_PREFIX = 7


class BaseLeanLSPClient:
    """BaseLeanLSPClient is managing RPC communication and file syncing.

    It interacts with a subprocess running `lake serve` via the `Language Server Protocol (LSP) <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/>`_.
    This wrapper is blocking, it always waits until the language server responds.

    See :meth:`leanclient.client.LeanLSPClient` for details.
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

        # Options can be found here:
        # https://github.com/leanprover/lean4/blob/a955708b6c5f25e7f9c9ae7b951f8f3d5aefe377/src/Lean/Data/Lsp/InitShutdown.lean
        project_uri = self._local_to_uri(self.project_path)
        params = {
            "processId": os.getpid(),
            "rootUri": project_uri,
            "initializationOptions": {"editDelay": 1},
        }

        results = self._send_request("initialize", params)
        server_info = results[-1]["result"]
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

        This is the main blocking function in this synchronous client:


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
        resp = orjson.loads(self.stdout.read(content_length))

        # Display RPC error messages (from language server)
        if "error" in resp:
            print("RPC Error Message\n", resp)

        return resp

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

    def _send_request(self, method: str, params: dict) -> list[dict]:
        """Send a request to the language server and return all responses.

        Args:
            method (str): Method name.
            params (dict): Parameters for the method.

        Returns:
            list[dict]: List of responses in the order they were received.
        """
        rid = self._send_request_rpc(method, params, is_notification=False)

        result = self._read_stdout()
        results = [result]
        while result.get("id") != rid and "error" not in result:
            result = self._read_stdout()
            results.append(result)

        return results

    def _send_request_document(self, path: str, method: str, params: dict) -> dict:
        """Send request about a document and return the final response.

        This function drops all intermediate responses since we typically don't need them.

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

    def _send_request_document_retries(
        self,
        path: str,
        method: str,
        params: dict,
        max_retries: int = 1,
        retry_delay: float = 0.0,
    ) -> dict:
        """Send request until no new results are found after a number of retries.

        Args:
            path (str): Relative file path.
            method (str): Method name.
            params (dict): Parameters for the method.
            max_retries (int): Number of times to retry if no new results were found. Defaults to 1.
            retry_delay (float): Time to wait between retries. Defaults to 0.0.

        Returns:
            dict: Final response.
        """
        prev_results = "Nvr_gnn_gv_y_p"
        retry_count = 0
        while True:
            results = self._send_request_document(
                path,
                method,
                params,
            )
            if results == prev_results:
                retry_count += 1
                if retry_count > max_retries:
                    break
                time.sleep(retry_delay)
            else:
                retry_count = 0
                prev_results = results

        return results

    def _send_notification(self, method: str, params: dict):
        """Send a notification to the language server.

        Args:
            method (str): Method name.
            params (dict): Parameters for the method.
        """
        self._send_request_rpc(method, params, is_notification=True)

    def _wait_for_diagnostics(self, uris: list[str], timeout: float = 3) -> list[dict]:
        """Wait until `waitForDiagnostics` returns or an rpc error occurs.

        This should only be used right after opening or updating files not to miss any responses.
        Sometimes `waitForDiagnostics` doesn't return, so we also check for file processing completion.
        See source for more details.

        **Example diagnostics**:

        .. code-block:: python

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
            ]

        Args:
            uris (list[str]): List of URIs to wait for diagnostics on.
            timeout (float): Time to wait for final diagnostics after file has finished. This is a workaround because `waitForDiagnostics` doesnt always terminate. Higher timeout decreases chance of incomplete diagnostics returned.

        Returns:
            list[dict]: List of diagnostic messages or errors.
        """
        # Waiting in series; Parallel requests are not reliable?
        diagnostics = collections.defaultdict(list)

        for uri in uris:
            # Send request for `waitForDiagnostics`
            rid = self._send_request_rpc(
                "textDocument/waitForDiagnostics",
                {"uri": uri, "version": 1},
                is_notification=False,
            )

            while True:
                # Non-blocking read if we have finished processing the file
                # `waitForDiagnostics` doesn't always return in that case. E.g. "unfinished comment"
                if select.select([self.stdout], [], [], timeout)[0]:
                    res = self._read_stdout()
                else:
                    print(f"Timed out after {timeout}s!!!")
                    break

                # Capture diagnostics
                method = res.get("method", "")
                if method == "textDocument/publishDiagnostics":
                    diagnostics[res["params"]["uri"]] = res["params"]["diagnostics"]
                    continue

                # Fatal error: https://github.com/leanprover/lean4/blob/8791a9ce069d6dc87f7cccc4387545b1110c89bd/src/Lean/Data/Lsp/Extra.lean#L55
                # elif method == "$/lean/fileProgress":
                #     proc = res["params"]["processing"]
                #     if len(proc) > 0 and proc[-1]["kind"] == 2:
                #         break

                # RPC error
                if "error" in res:
                    diagnostics[uri] = res
                    break

                # `waitForDiagnostics` has returned
                if res.get("id") == rid and res.get("result", True) == {}:
                    break

        return [diagnostics[uri] for uri in uris]

    def create_file_client(self, file_path: str) -> SingleFileClient:
        """Create a SingleFileClient for a file.

        Args:
            file_path (str): Relative file path.

        Returns:
            SingleFileClient: A client for interacting with a single file.
        """
        return SingleFileClient(self, file_path)

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
