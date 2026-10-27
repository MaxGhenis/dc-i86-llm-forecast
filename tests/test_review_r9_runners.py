"""Round-9 fork probes; every runner root is a temporary MOCK layout."""

import json
import os
import stat
import threading

import pytest

from i86 import runners


class ReviewDefect(AssertionError):
    """An executed fork retained a descriptor it should have discarded."""


def test_fork_during_lock_teardown_does_not_leak_lock_descriptor(tmp_path, monkeypatch):
    for name in ("RUNS", "WORK", "STAGE", "JOBS"):
        monkeypatch.setattr(runners, name, tmp_path / name.lower())
    removed, release = threading.Event(), threading.Event()
    owner_errors = []
    active = {}

    class PausedDiscard(set):
        def discard(self, fd):
            # Control only the schedule: the ordinary removal has already happened, and the
            # owner's next operation will close this descriptor after the main thread forks.
            super().discard(fd)
            removed.set()
            if not release.wait(10):
                owner_errors.append("timed out waiting to close the descriptor")

    monkeypatch.setattr(runners, "_lock_fds", PausedDiscard())

    def owner():
        try:
            with runners.bookkeeping_lock():
                active["fd"] = next(iter(runners._lock_fds))
        except BaseException as exc:
            owner_errors.append(repr(exc))

    thread = threading.Thread(target=owner, name="MOCK-lock-owner")
    thread.start()
    child = None
    rd = wr = None
    timer = threading.Timer(0, lambda: None)
    try:
        assert removed.wait(5), owner_errors
        rd, wr = os.pipe()
        # Fork waits for the owner to close the descriptor it has just untracked (the teardown holds
        # _fd_guard), so the owner is let go shortly after the fork starts, from another thread.
        timer = threading.Timer(0.3, release.set)
        timer.start()
        child = os.fork()
        if child == 0:
            try:
                try:
                    inherited = os.fstat(active["fd"])
                except OSError:
                    result = {"retained_lock": False}
                else:
                    lock = runners.STAGE.with_name(runners.STAGE.name + ".lock").stat()
                    result = {"retained_lock": stat.S_ISREG(inherited.st_mode)
                              and (inherited.st_dev, inherited.st_ino) == (lock.st_dev, lock.st_ino),
                              "tracked": sorted(runners._lock_fds)}
                result["forked_after_release"] = release.is_set()
                os.write(wr, json.dumps(result).encode())
                os._exit(0)
            except BaseException:
                os._exit(2)
        os.close(wr)
        wr = None
        release.set()
        thread.join(5)
        assert not thread.is_alive() and not owner_errors, owner_errors
        result = json.loads(os.read(rd, 4096))
        _, status = os.waitpid(child, 0)
        child = None
        assert os.waitstatus_to_exitcode(status) == 0
        if result["retained_lock"] or not result["forked_after_release"]:
            raise ReviewDefect(result)
    finally:
        release.set()
        timer.cancel()
        thread.join(5)
        if child is not None:
            os.waitpid(child, 0)
        for fd in (rd, wr):
            if fd is not None:
                os.close(fd)
