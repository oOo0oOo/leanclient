import threading
import time
import pytest
from unittest.mock import MagicMock
from leanclient.file_manager import LSPFileManager, FileState


def test_wait_for_diagnostics_atomic_check_and_wait():
    """Test that _wait_for_diagnostics checks state and waits atomically."""

    class TestClient(LSPFileManager):
        def __init__(self):
            self.project_path = "."
            self._notification_handlers = {}
            super().__init__(max_opened_files=1)

    client = TestClient()
    client._send_request_async = MagicMock()
    client._uri_to_local = MagicMock(return_value="test.lean")

    path, uri = "test.lean", "file:///test.lean"
    client.opened_files[path] = FileState(
        uri=uri, content="", complete=False, processing=False, diagnostics_version=-1
    )

    real_cond = client._close_condition

    class CheckedCondition:
        def __enter__(self):
            real_cond.acquire()

        def __exit__(self, *a):
            real_cond.release()

        def notify_all(self):
            real_cond.notify_all()

        def wait(self, timeout=None):
            if client.opened_files[path].complete:
                raise RuntimeError("Race: Waiting while complete!")
            real_cond.wait(timeout)

    client._close_condition = CheckedCondition()

    errors = []

    def run():
        try:
            client._wait_for_diagnostics([uri], inactivity_timeout=0.5)
        except Exception as e:
            errors.append(e)

    t = threading.Thread(target=run)
    t.start()
    time.sleep(0.1)

    with real_cond:
        client.opened_files[path].complete = True
        client.opened_files[path].diagnostics_version = 0
        real_cond.notify_all()

    t.join(timeout=1.0)
    if errors:
        pytest.fail(f"Thread failed: {errors[0]}")
