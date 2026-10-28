"""Round-11 lock probe, for the one-descriptor lock: a fork while another thread holds the bookkeeping
lock leaves the child no descriptor on the lock file, and the child's own use opens its own. All
runner roots are temporary MOCK directories."""

import os
import signal
import threading

from i86 import runners
from test_lock_fork import collect, isolate, lock_path, on_lock, report


def test_fork_from_another_thread_does_not_orphan_lock_descriptor(tmp_path, monkeypatch):
    isolate(tmp_path, monkeypatch)
    held, release = threading.Event(), threading.Event()

    def holder():
        with runners.bookkeeping_lock():
            held.set()
            release.wait(10)

    worker = threading.Thread(target=holder, name="MOCK-vanishing-lock-owner")
    worker.start()
    child = None
    try:
        assert held.wait(5)
        rd, wr = os.pipe()
        child = os.fork()
        if child == 0:
            try:
                signal.alarm(10)
                os.close(rd)
                before = on_lock(lock_path())
                with runners.bookkeeping_lock():
                    during = on_lock(lock_path())
                    own = runners._fd
                report(wr, {"before": before, "during": during, "own": own,
                            "threads": [t.name for t in threading.enumerate()]})
                os._exit(0)
            except BaseException:
                os._exit(2)
        os.close(wr)
        release.set()
        worker.join(5)
        result, code = collect(rd, child)
        child = None
    finally:
        release.set()
        worker.join(5)
        if child not in (None, 0):
            os.waitpid(child, 0)
    assert code == 0, result
    assert result["before"] == [] and result["during"] == [result["own"]], result
    assert result["threads"] == ["MainThread"], result
