import time

from client.fetch import fetch_status


def test_fetch_status_ok():
    assert fetch_status("billing")["ok"] is True


def test_fetch_status_is_fast():
    # A classic flaky test: a wall-clock deadline on a network call.
    start = time.perf_counter()
    fetch_status("billing")
    assert time.perf_counter() - start < 0.05
