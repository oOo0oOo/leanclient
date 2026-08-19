"""Scripted stdio LSP peer for byzantine-server tests.

Usage: python fake_server.py <scenario>

Speaks just enough LSP to let LspTransport / AsyncLeanLSPClient run, then
misbehaves according to the scenario. Each scenario documents the client
behavior it exists to verify.
"""

from __future__ import annotations

import json
import os
import sys
import time

STDIN = sys.stdin.buffer
STDOUT = sys.stdout.buffer

SCENARIO = sys.argv[1] if len(sys.argv) > 1 else "happy"


def send(msg: dict) -> None:
    body = json.dumps(msg).encode()
    STDOUT.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
    STDOUT.flush()


def send_raw(data: bytes) -> None:
    STDOUT.write(data)
    STDOUT.flush()


def respond(msg_id, result=None, error=None) -> None:
    payload = {"jsonrpc": "2.0", "id": msg_id}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result
    send(payload)


def read_message() -> dict | None:
    content_length = None
    while True:
        line = STDIN.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            break
        if line.lower().startswith(b"content-length:"):
            content_length = int(line.split(b":", 1)[1])
    if content_length is None:
        return None
    body = STDIN.read(content_length)
    return json.loads(body)


def publish_clean_diagnostics(uri: str, version: int) -> None:
    send(
        {
            "jsonrpc": "2.0",
            "method": "textDocument/publishDiagnostics",
            "params": {"uri": uri, "version": version, "diagnostics": []},
        }
    )
    send(
        {
            "jsonrpc": "2.0",
            "method": "$/lean/fileProgress",
            "params": {
                "textDocument": {"uri": uri, "version": version},
                "processing": [],
            },
        }
    )


def main() -> None:
    request_count = 0  # non-initialize requests seen
    pending_out_of_order: list[dict] = []
    doc_versions: dict[str, int] = {}

    while True:
        msg = read_message()
        if msg is None:
            return
        method = msg.get("method")
        msg_id = msg.get("id")

        # --- notifications ---------------------------------------------
        if msg_id is None:
            if method == "textDocument/didOpen":
                td = msg["params"]["textDocument"]
                doc_versions[td["uri"]] = td["version"]
                if SCENARIO != "slow_elab":
                    publish_clean_diagnostics(td["uri"], td["version"])
            elif method == "textDocument/didChange":
                td = msg["params"]["textDocument"]
                doc_versions[td["uri"]] = td["version"]
                publish_clean_diagnostics(td["uri"], td["version"])
            elif method == "$/cancelRequest" and SCENARIO == "cancel_ack":
                respond(
                    msg["params"]["id"],
                    error={"code": -32800, "message": "cancelled by fake server"},
                )
            continue

        # --- requests ---------------------------------------------------
        if method == "initialize":
            respond(msg_id, result={"capabilities": {}})
            continue

        # Answered in every scenario: the client fires this in the background
        # right after initialize; it must not perturb scenario request counts.
        if method == "$/lean/waitForILeans":
            respond(msg_id, result={})
            continue

        if method == "workspace/symbol":
            query = msg["params"]["query"]
            respond(
                msg_id,
                result=[
                    {
                        "name": f"{query}_exact",
                        "kind": 14,
                        "location": {
                            "uri": "file:///fake/Dep.lean",
                            "range": {
                                "start": {"line": 4, "character": 8},
                                "end": {"line": 4, "character": 20},
                            },
                        },
                    },
                    {
                        "name": f"Namespace.{query}_fuzzy",
                        "kind": 14,
                        "location": {
                            "uri": "file:///fake/Other.lean",
                            "range": {
                                "start": {"line": 9, "character": 0},
                                "end": {"line": 9, "character": 6},
                            },
                        },
                    },
                ],
            )
            continue

        request_count += 1

        if SCENARIO == "happy":
            if method == "textDocument/waitForDiagnostics":
                respond(msg_id, result={})
            else:
                respond(msg_id, result={"echo": method, "n": request_count})

        elif SCENARIO == "slow_elab":
            # Elaboration never finishes: emit a fileProgress processing range
            # and leave waitForDiagnostics pending forever. Clients must be
            # able to return an honest partial result instead of an error.
            if method == "textDocument/waitForDiagnostics":
                uri = msg["params"]["uri"]
                send(
                    {
                        "jsonrpc": "2.0",
                        "method": "$/lean/fileProgress",
                        "params": {
                            "textDocument": {"uri": uri, "version": 1},
                            "processing": [
                                {
                                    "range": {
                                        "start": {"line": 2, "character": 0},
                                        "end": {"line": 40, "character": 0},
                                    },
                                    "kind": 1,
                                }
                            ],
                        },
                    }
                )
                # never respond
            else:
                respond(msg_id, result={"echo": method})

        elif SCENARIO == "malformed_header":
            # Garbage instead of a header block: the reader must die typed
            # and fail every pending future (not hang).
            sys.stderr.write("about to write garbage\n")
            sys.stderr.flush()
            send_raw(b"XYZZY this is not an LSP header\r\n\r\n")
            time.sleep(30)  # stay alive: death must come from parsing, not EOF

        elif SCENARIO == "bad_json":
            send_raw(b"Content-Length: 12\r\n\r\n{not json!!}")
            time.sleep(30)

        elif SCENARIO == "out_of_order":
            # Answer requests 1 and 2 in reverse order.
            pending_out_of_order.append(msg)
            if len(pending_out_of_order) == 2:
                second = pending_out_of_order.pop()
                first = pending_out_of_order.pop()
                respond(second["id"], result={"which": "second"})
                respond(first["id"], result={"which": "first"})

        elif SCENARIO == "id_collision":
            # Server->client REQUEST with the same id as the client's pending
            # request. The client must answer it and must NOT resolve its own
            # future with this message.
            send(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "method": "workspace/semanticTokens/refresh",
                    "params": {"reason": "test"},
                }
            )
            respond(msg_id, result={"real": True})

        elif SCENARIO == "crash_mid_request":
            sys.stderr.write("FATAL: simulated server crash\n")
            sys.stderr.flush()
            os._exit(1)

        elif SCENARIO == "huge":
            respond(msg_id, result={"blob": "x" * (5 * 1024 * 1024)})

        elif SCENARIO == "cancel_ack":
            pass  # never answer; the $/cancelRequest handler above replies

        elif SCENARIO == "silent_eof":
            os._exit(0)

        else:
            respond(msg_id, error={"code": -32601, "message": "unknown scenario"})


if __name__ == "__main__":
    main()
