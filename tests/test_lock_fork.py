"""A forked child lets go of the bookkeeping lock even with no descriptor free. Every runner root is a
temporary MOCK layout."""

import errno
import json
import os
import resource
import signal
import threading
from contextlib import contextmanager

from i86 import runners


def isolate(tmp_path, monkeypatch):
    for name in ("RUNS", "WORK", "STAGE", "JOBS"):
        monkeypatch.setattr(runners, name, tmp_path / name.lower())


@contextmanager
def no_descriptor_free():
    """Lower the soft descriptor limit and fill every free slot below it; yield the fillers."""
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    in_use = len(os.listdir("/dev/fd"))
    resource.setrlimit(resource.RLIMIT_NOFILE, (in_use + 16, hard))
    fillers = []
    try:
        while True:
            try:
                fillers.append(os.open(os.devnull, os.O_RDONLY))
            except OSError as exc:
                assert exc.errno == errno.EMFILE
                break
            assert len(fillers) < 4096
        yield fillers
    finally:
        for fd in fillers:
            try:
                os.close(fd)
            except OSError:
                pass
        resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))


def child_report(work, rd, wr):
    """Run work() in a forked child, which writes its JSON result to wr; return the result."""
    pid = os.fork()
    if pid == 0:
        try:
            signal.alarm(10)  # a child that cannot take the lock dies instead of hanging the suite
            os.close(rd)
            os.write(wr, json.dumps(work()).encode())
            os._exit(0)
        except BaseException:
            os._exit(2)
    return pid


def test_child_lets_go_with_no_descriptor_free(tmp_path, monkeypatch):
    """The parent's waiting-or-held descriptor is pointed at /dev/null without needing a free slot,
    the child's locks are fresh, and the child takes the file lock once the parent lets go."""
    isolate(tmp_path, monkeypatch)
    holding, release = threading.Event(), threading.Event()
    seen = {}

    def worker():
        with runners.bookkeeping_lock():
            seen["fd"] = next(iter(runners._lock_fds))
            holding.set()
            release.wait(10)

    thread = threading.Thread(target=worker, name="MOCK-lock-holder")
    thread.start()
    assert holding.wait(5)
    rd, wr = os.pipe()
    null = os.stat(os.devnull)

    def work():
        inherited = os.fstat(seen["fd"])
        result = {"tracked": sorted(runners._lock_fds),
                  "guard_free": runners._fd_guard.acquire(blocking=False),
                  "mutex_free": runners._mutex.acquire(blocking=False),
                  "points_at_null": (inherited.st_rdev, inherited.st_ino) == (null.st_rdev, null.st_ino)}
        runners._fd_guard.release()
        runners._mutex.release()
        for fd in fillers:
            os.close(fd)
        with runners.bookkeeping_lock():
            result["took_lock"] = True
        return result

    try:
        with no_descriptor_free() as fillers:
            pid = child_report(work, rd, wr)
        os.close(wr)
        wr = None
        release.set()
        thread.join(5)
        result = json.loads(os.read(rd, 4096) or b"{}")
        _, status = os.waitpid(pid, 0)
    finally:
        release.set()
        thread.join(5)
        os.close(rd)
        if wr is not None:
            os.close(wr)
    assert os.waitstatus_to_exitcode(status) == 0, result
    assert result == {"tracked": [], "guard_free": True, "mutex_free": True, "points_at_null": True,
                      "took_lock": True}


def test_child_without_spare_closes_and_leaves_the_number_alone(tmp_path, monkeypatch):
    """With the spare no longer /dev/null and no slot free, the child closes the inherited lock
    descriptor; the frame that opened it, unwinding in the child, leaves the number to whatever
    file now has it."""
    isolate(tmp_path, monkeypatch)
    other = tmp_path / "MOCK-other.txt"
    other.write_text("MOCK other file\n")
    impostor = os.open(other, os.O_RDONLY)  # the spare's number, now another file's
    monkeypatch.setattr(runners, "_spare_null", impostor)
    monkeypatch.setattr(runners, "_closed_in_child", set())
    rd, wr = os.pipe()
    other_id = (os.stat(other).st_dev, os.stat(other).st_ino)
    lock_path = runners.STAGE.with_name(runners.STAGE.name + ".lock")
    pid = None
    try:
        with runners.bookkeeping_lock():
            fd = next(iter(runners._lock_fds))
            with no_descriptor_free() as fillers:
                pid = os.fork()
                if pid == 0:
                    try:
                        signal.alarm(10)
                        try:
                            os.fstat(fd)
                            result = {"closed": False}
                        except OSError:
                            result = {"closed": True}
                        result["recorded"] = fd in runners._closed_in_child
                        for f in fillers:
                            os.close(f)
                        reuse = os.open(other, os.O_RDONLY)  # likely the lowest free number, fd's
                        if reuse != fd:
                            os.dup2(reuse, fd)  # either way the number now belongs to another file
                            os.close(reuse)
                    except BaseException:
                        os._exit(2)
        if pid == 0:
            try:
                st = os.fstat(fd)
                result["left_alone"] = (st.st_dev, st.st_ino) == other_id
            except OSError:
                result["left_alone"] = False
            try:
                result["forgotten"] = fd not in runners._closed_in_child
                with runners.bookkeeping_lock():  # the parent let go before it waited for this child
                    result["took_lock"] = True
                os.write(wr, json.dumps(result).encode())
                os._exit(0)
            except BaseException:
                os._exit(2)
        os.close(wr)
        wr = None
        result = json.loads(os.read(rd, 4096) or b"{}")
        _, status = os.waitpid(pid, 0)
        pid = None
    finally:
        if pid not in (None, 0):
            os.waitpid(pid, 0)
        os.close(rd)
        if wr is not None:
            os.close(wr)
        os.close(impostor)
    assert os.waitstatus_to_exitcode(status) == 0, result
    assert result == {"closed": True, "recorded": True, "left_alone": True, "forgotten": True,
                      "took_lock": True}
    assert lock_path.exists()
