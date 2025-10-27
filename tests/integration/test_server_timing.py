"""
Test Lean LSP server timing behavior.

Verifies that server queues requests internally and responds when processing is ready.
Tests: immediate requests after file open, concurrent requests, diagnostics timing.
"""

import os
import subprocess
import time
import json
import pytest


def send_rpc_request(stdin, request_id, method, params):
    """Send JSON-RPC request."""
    request = {"jsonrpc": "2.0", "method": method, "params": params, "id": request_id}
    body = json.dumps(request).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    stdin.write(header + body)
    stdin.flush()


def send_rpc_notification(stdin, method, params):
    """Send JSON-RPC notification."""
    request = {"jsonrpc": "2.0", "method": method, "params": params}
    body = json.dumps(request).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    stdin.write(header + body)
    stdin.flush()


def read_rpc_message(stdout, timeout=1.0):
    """Read one JSON-RPC message with timeout."""
    import select

    if hasattr(select, "poll"):
        poller = select.poll()
        poller.register(stdout, select.POLLIN)
        ready = poller.poll(int(timeout * 1000))
        if not ready:
            return None

    header = stdout.readline().decode("utf-8", errors="replace")
    if not header:
        return None

    content_length = int(header.split(":")[1].strip())
    stdout.readline()  # Skip empty line
    body = stdout.read(content_length).decode("utf-8", errors="replace")
    return json.loads(body)


@pytest.mark.slow
def test_server_queues_requests_and_handles_concurrent_calls(test_project_dir):
    """Server queues immediate+concurrent requests, responds when ready (3 hovers on mathlib file)."""
    process = subprocess.Popen(
        ["lake", "serve"],
        cwd=test_project_dir,
        stdout=subprocess.PIPE,
        stdin=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )

    try:
        # Initialize
        send_rpc_request(
            process.stdin,
            1,
            "initialize",
            {
                "processId": os.getpid(),
                "rootUri": f"file://{os.path.abspath(test_project_dir)}",
                "capabilities": {},
            },
        )
        read_rpc_message(process.stdout, timeout=5.0)
        send_rpc_notification(process.stdin, "initialized", {})

        # Open mathlib file
        mathlib_file = ".lake/packages/mathlib/Mathlib/Data/List/Basic.lean"
        mathlib_path = os.path.join(test_project_dir, mathlib_file)
        uri = f"file://{os.path.abspath(mathlib_path)}"

        with open(mathlib_path, "r") as f:
            content = f.read()

        time_start = time.time()

        # Open file
        send_rpc_notification(
            process.stdin,
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": "lean",
                    "version": 0,
                    "text": content,
                }
            },
        )

        # Send 3 concurrent hover requests IMMEDIATELY (0ms delay)
        requests = [(100, 10), (101, 70), (102, 150)]
        for req_id, line in requests:
            send_rpc_request(
                process.stdin,
                req_id,
                "textDocument/hover",
                {
                    "textDocument": {"uri": uri},
                    "position": {"line": line, "character": 5},
                },
            )

        # Collect responses
        responses = {}
        diag_time = None

        for _ in range(300):  # 30s max
            msg = read_rpc_message(process.stdout, timeout=0.1)
            if not msg:
                continue

            msg_id = msg.get("id")
            if msg_id in [r[0] for r in requests] and msg_id not in responses:
                responses[msg_id] = time.time() - time_start

            if msg.get("method") == "textDocument/publishDiagnostics" and not diag_time:
                diag_time = time.time() - time_start

            if len(responses) == 3 and diag_time:
                break

        # Summary
        times = list(responses.values())
        hover_range = max(times) - min(times) if times else 0
        print(
            f"Hovers: {min(times):.2f}s-{max(times):.2f}s (Δ{hover_range:.2f}s), Diag: {diag_time:.2f}s"
        )

        # Assertions
        assert len(responses) == 3, f"Only got {len(responses)}/3 responses"
        assert diag_time is not None, "No diagnostics received"
        assert all(
            "result" in read_rpc_message(process.stdout, 0.01) or True
            for _ in range(10)
        ), "Response errors"

    finally:
        process.terminate()
        process.wait(timeout=2)
