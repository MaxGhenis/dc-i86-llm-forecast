"""Round-11 lock probe (from the interrupted first review): a fork while another thread holds the
bookkeeping lock leaves the child no untracked descriptor. All runner roots are temporary MOCK
directories."""

import json
import os
import signal
import threading

from i86 import runners


def test_fork_from_another_thread_does_not_orphan_lock_descriptor(tmp_path, monkeypatch):
    for name in ("RUNS", "WORK", "STAGE", "JOBS"):
        monkeypatch.setattr(runners, name, tmp_path / name.lower())
    held, release = threading.Event(), threading.Event()
    shared = {}

    def holder():
        with runners.bookkeeping_lock():
            shared["fd"] = next(iter(runners._lock_fds))
            held.set()
            release.wait(10)

    rd, wr = os.pipe()
    worker = threading.Thread(target=holder, name="MOCK-vanishing-lock-owner")
    worker.start()
    child = None
    try:
        assert held.wait(5)
        child = os.fork()
        if child == 0:
            try:
                signal.alarm(10)
                os.close(rd)
                with runners.bookkeeping_lock():
                    new_fd = next(iter(runners._lock_fds))
                try:
                    st, null = os.fstat(shared["fd"]), os.stat(os.devnull)
                    leaked = (st.st_dev, st.st_ino) == (null.st_dev, null.st_ino)
                except OSError:
                    leaked = False
                result = {
                    "leaked": leaked,
                    "inherited_fd": shared["fd"],
                    "new_fd": new_fd,
                    "tracked": sorted(runners._lock_fds),
                    "threads": [t.name for t in threading.enumerate()],
                }
                os.write(wr, json.dumps(result).encode())
                os._exit(0)
            except BaseException:
                os._exit(2)
        os.close(wr)
        wr = None
        release.set()
        worker.join(5)
        assert not worker.is_alive()
        result = json.loads(os.read(rd, 4096) or b"{}")
        _, status = os.waitpid(child, 0)
        child = None
        assert os.waitstatus_to_exitcode(status) == 0, result
        assert result["tracked"] == [] and result["threads"] == ["MainThread"], result
        assert not result["leaked"], result
    finally:
        release.set()
        worker.join(5)
        if child not in (None, 0):
            os.waitpid(child, 0)
        os.close(rd)
        if wr is not None:
            os.close(wr)
