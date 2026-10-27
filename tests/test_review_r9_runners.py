"""Round-9 fork probe, for the one-descriptor lock: a fork while another thread opens the lock's
descriptor waits for it to be recorded, so the child closes it. Every runner root is a temporary MOCK
layout."""

import json
import os
import threading

from i86 import runners
from test_lock_fork import collect, isolate, lock_path, on_lock, report


def test_fork_while_another_thread_opens_the_descriptor_leaves_the_child_none(tmp_path, monkeypatch):
    isolate(tmp_path, monkeypatch)
    opened, release = threading.Event(), threading.Event()
    real_open, errors = os.open, []

    def paused_open(path, *args, **kwargs):
        fd = real_open(path, *args, **kwargs)
        if threading.current_thread().name == "MOCK-lock-opener" and str(path).endswith(".lock"):
            # The descriptor exists, and _fd_guard is held, but _fd does not have it yet.
            opened.set()
            if not release.wait(10):
                errors.append("timed out")
        return fd

    monkeypatch.setattr(runners.os, "open", paused_open)

    def opener():
        try:
            with runners.bookkeeping_lock():
                pass
        except BaseException as exc:
            errors.append(repr(exc))

    thread = threading.Thread(target=opener, name="MOCK-lock-opener")
    thread.start()
    pid = None
    timer = threading.Timer(0.3, release.set)
    try:
        assert opened.wait(5), errors
        rd, wr = os.pipe()
        timer.start()  # fork waits for _fd_guard, so the opener is let go from another thread
        pid = os.fork()
        if pid == 0:
            try:
                os.close(rd)
                report(wr, {"descriptors": on_lock(lock_path()), "fd": runners._fd,
                            "forked_after_release": release.is_set()})
                os._exit(0)
            except BaseException:
                os._exit(2)
        os.close(wr)
        result, code = collect(rd, pid)
        pid = None
    finally:
        release.set()
        timer.cancel()
        thread.join(5)
        if pid not in (None, 0):
            os.waitpid(pid, 0)
    assert code == 0 and not errors, (result, errors)
    assert result == {"descriptors": [], "fd": None, "forked_after_release": True}, json.dumps(result)
