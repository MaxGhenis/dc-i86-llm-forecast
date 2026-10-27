"""The bookkeeping lock across threads and forks: one descriptor per process, and a forked child holds
none of its parent's lock. Every runner root is a temporary MOCK layout; each child reports through a
pipe and dies on an alarm instead of hanging the suite."""

import errno
import fcntl
import json
import os
import resource
import signal
import threading
import time
from contextlib import contextmanager

from i86 import runners


def isolate(tmp_path, monkeypatch):
    for name in ("RUNS", "WORK", "STAGE", "JOBS"):
        monkeypatch.setattr(runners, name, tmp_path / name.lower())


def lock_path():
    return runners.STAGE.with_name(runners.STAGE.name + ".lock")


def on_lock(path) -> list[int]:
    """This process's descriptors on the file at `path`."""
    target = os.stat(path)
    out = []
    for name in os.listdir("/dev/fd"):
        try:
            st = os.fstat(int(name))
        except OSError:
            continue
        if (st.st_dev, st.st_ino) == (target.st_dev, target.st_ino):
            out.append(int(name))
    return sorted(out)


def free(path) -> bool:
    """Whether no open file holds the lock: a new descriptor takes it at once (flock locks on two
    open files conflict even within one process)."""
    fd = os.open(path, os.O_WRONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


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


def report(wr, result) -> None:
    os.write(wr, json.dumps(result).encode())
    os.close(wr)


def collect(rd, pid) -> tuple[dict, int]:
    with os.fdopen(rd, "rb") as f:
        data = f.read()
    _, status = os.waitpid(pid, 0)
    return json.loads(data or b"{}"), os.waitstatus_to_exitcode(status)


def test_one_descriptor_serves_every_use_in_a_process(tmp_path, monkeypatch):
    """Uses, nested uses and other threads' uses share one descriptor, kept open between them, and the
    lock is free between uses."""
    isolate(tmp_path, monkeypatch)
    with runners.bookkeeping_lock():
        with runners.bookkeeping_lock():
            inner = on_lock(lock_path())
        outer = on_lock(lock_path())
    seen = []

    def use():
        with runners.bookkeeping_lock():
            seen.append(on_lock(lock_path()))

    threads = [threading.Thread(target=use, name=f"MOCK-user-{i}") for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert inner == outer == [runners._fd] and all(s == outer for s in seen), (inner, outer, seen)
    assert on_lock(lock_path()) == outer and free(lock_path()) and runners._depth == 0


def test_a_descriptor_the_caller_opened_on_the_lock_file_survives(tmp_path, monkeypatch):
    """Round-12 finding 2: the lock closes no descriptor it did not open, though it is on the lock file."""
    isolate(tmp_path, monkeypatch)
    with runners.bookkeeping_lock():
        pass
    own = os.open(lock_path(), os.O_RDONLY)
    try:
        for _ in range(3):
            with runners.bookkeeping_lock():
                pass
        st, target = os.fstat(own), os.stat(lock_path())
        assert (st.st_dev, st.st_ino) == (target.st_dev, target.st_ino)
    finally:
        os.close(own)


def test_a_moved_lock_file_gets_a_new_descriptor_and_the_old_one_closes(tmp_path, monkeypatch):
    isolate(tmp_path, monkeypatch)
    with runners.bookkeeping_lock():
        pass
    first = lock_path()
    monkeypatch.setattr(runners, "STAGE", tmp_path / "MOCK-other-stage")
    with runners.bookkeeping_lock():
        pass
    assert on_lock(first) == [] and on_lock(lock_path()) == [runners._fd]


def test_child_of_another_threads_use_holds_nothing_even_with_no_descriptor_free(tmp_path, monkeypatch):
    """A child forked while another thread holds the lock closes its copy of the descriptor, which
    needs no free slot, so the lock is free once the parent lets go though the child still runs; the
    child's locks are fresh, and it then takes the file lock itself."""
    isolate(tmp_path, monkeypatch)
    holding, release = threading.Event(), threading.Event()

    def worker():
        with runners.bookkeeping_lock():
            holding.set()
            release.wait(10)

    thread = threading.Thread(target=worker, name="MOCK-lock-holder")
    thread.start()
    assert holding.wait(5)
    path = lock_path()
    rd, wr = os.pipe()
    go_rd, go_wr = os.pipe()
    pid = None
    try:
        with no_descriptor_free() as fillers:
            pid = os.fork()
            if pid == 0:
                try:
                    signal.alarm(15)
                    os.close(rd)
                    os.close(go_wr)
                    result = {"descriptors": on_lock(path), "fd": runners._fd, "depth": runners._depth,
                              "guard_free": runners._fd_guard.acquire(blocking=False),
                              "mutex_free": runners._mutex.acquire(blocking=False)}
                    runners._fd_guard.release()
                    runners._mutex.release()
                    for fd in fillers:
                        os.close(fd)
                    os.read(go_rd, 1)  # the parent has let go
                    with runners.bookkeeping_lock():
                        result["took_lock"] = not free(path)
                    report(wr, result)
                    os._exit(0)
                except BaseException:
                    os._exit(2)
        os.close(go_rd)
        os.close(wr)
        release.set()
        thread.join(5)
        free_while_child_runs = free(path)
        os.write(go_wr, b"g")
        os.close(go_wr)
        result, code = collect(rd, pid)
        pid = None
    finally:
        release.set()
        thread.join(5)
        if pid not in (None, 0):
            os.waitpid(pid, 0)
    assert code == 0 and free_while_child_runs, result
    assert result == {"descriptors": [], "fd": None, "depth": 0, "guard_free": True, "mutex_free": True,
                      "took_lock": True}


def test_a_use_forked_inside_runs_on_in_the_child_without_the_lock(tmp_path, monkeypatch):
    """Round-12 finding 3, for a plain fork: the child's own use, nested in the one it inherited,
    waits for the parent to let go and then takes the lock; the inherited use, ending in the child,
    leaves the child's state alone."""
    isolate(tmp_path, monkeypatch)
    path = lock_path()
    marker = tmp_path / "MOCK-child-took-lock"
    rd, wr = os.pipe()
    pid, result = None, {}
    try:
        with runners.bookkeeping_lock():
            pid = os.fork()
            if pid == 0:
                try:
                    signal.alarm(15)
                    os.close(rd)
                    result = {"descriptors": on_lock(path), "depth": runners._depth}
                    with runners.bookkeeping_lock():
                        result["took_lock"] = not free(path)
                        marker.write_text(repr(time.time()))
                except BaseException:
                    os._exit(2)
            else:
                time.sleep(0.5)
                waited = not marker.exists()
                released = time.time()
        if pid == 0:
            try:
                result.update(depth_after=runners._depth, free_after=free(path))
                report(wr, result)
                os._exit(0)
            except BaseException:
                os._exit(2)
        os.close(wr)
        result, code = collect(rd, pid)
        pid = None
    finally:
        if pid not in (None, 0):
            os.waitpid(pid, 0)
    assert code == 0 and waited and float(marker.read_text()) >= released, result
    assert result == {"descriptors": [], "depth": 0, "took_lock": True, "depth_after": 0, "free_after": True}
