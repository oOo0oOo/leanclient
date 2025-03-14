import os
import pathlib
from pprint import pprint
import subprocess
import urllib.parse

import select
import orjson

from .utils import SemanticTokenProcessor


LEN_URI_PREFIX = 7


class BaseLeanLSPClient:
    """BaseLeanLSPClient runs a language server in a subprocess.

    See :meth:`leanclient.client.LeanLSPClient` for more information.
    """

    def __init__(
        self, project_path: str, initial_build: bool = True, print_warnings: bool = True
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

    def close(self, timeout: float | None = 2):
        """Always close the client when done!

        Terminates the language server process and close all pipes.

        Args:
            timeout (float | None): Time to wait for the process to terminate. Defaults to 2 seconds.
        """
        self.process.terminate()
        try:
            if timeout is not None:
                self.process.wait(timeout=timeout)
            else:
                self.process.wait()
        except subprocess.TimeoutExpired:
            print("Warning: Language server did not close in time. Killing process.")
            self.process.kill()
            self.process.wait()
        finally:
            self.process.stderr.close()
            self.stdout.close()
            self.stdin.close()

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
        uri = pathlib.Path(self.project_path, local_path).as_uri()
        return urllib.parse.unquote(uri)

    def _locals_to_uris(self, local_paths: list[str]) -> list[str]:
        """See :meth:`_local_to_uri`"""
        paths = [
            pathlib.Path(self.project_path, local_path).as_uri()
            for local_path in local_paths
        ]
        return [urllib.parse.unquote(path) for path in paths]

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
        if not is_notification:
            request_id = self.request_id
            self.request_id += 1

        request = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            **({"id": request_id} if not is_notification else {}),
        }

        body = orjson.dumps(request)
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        self.stdin.write(header + body)
        self.stdin.flush()

        if not is_notification:
            return request_id

    def _send_notification(self, method: str, params: dict):
        """Send a notification to the language server.

        Args:
            method (str): Method name.
            params (dict): Parameters for the method.
        """
        self._send_request_rpc(method, params, is_notification=True)

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
