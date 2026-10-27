"""Round-11 finding 40: bookkeeping_lock under signal handlers. Each probe runs in its own Python
process, so its handlers and forks stay out of the test runner. All paths are temporary MOCK
directories."""

import subprocess
import sys
import textwrap

SETUP = """
import fcntl, os, signal, sys, time
from pathlib import Path
from i86 import runners
tmp = Path(sys.argv[1])
runners.STAGE = tmp / "stage"
lock = tmp / "stage.lock"
"""


def probe(tmp_path, code: str) -> str:
    proc = subprocess.run([sys.executable, "-c", SETUP + textwrap.dedent(code), str(tmp_path)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def test_a_raising_handler_leaves_no_lock_descriptor_open(tmp_path):
    out = probe(tmp_path, """
        class Alarm(Exception):
            pass
        armed = [False]
        def handler(sig, frame):
            if armed[0]:  # at most once per entry, so none lands in the cleanup it starts
                armed[0] = False
                raise Alarm
        signal.signal(signal.SIGALRM, handler)
        signal.setitimer(signal.ITIMER_REAL, 1e-5, 1e-5)
        alarms = 0
        for _ in range(3000):
            armed[0] = True
            try:
                with runners.bookkeeping_lock():
                    pass
            except Alarm:
                alarms += 1
            armed[0] = False
        signal.setitimer(signal.ITIMER_REAL, 0)
        target = os.stat(lock)
        def on_lock(fd):
            try:
                st = os.fstat(fd)
            except OSError:
                return False
            return (st.st_dev, st.st_ino) == (target.st_dev, target.st_ino)
        print(alarms, sum(on_lock(int(n)) for n in os.listdir("/dev/fd")))
    """)
    alarms, left = map(int, out.split())
    assert alarms > 1000 and left == 0, out


def test_a_child_forked_by_a_handler_while_waiting_still_waits(tmp_path):
    out = probe(tmp_path, """
        holder = os.open(lock, os.O_WRONLY | os.O_CREAT, 0o644)
        if os.fork() == 0:  # another process holds the lock for 2 s
            fcntl.flock(holder, fcntl.LOCK_EX)
            time.sleep(2)
            os._exit(0)
        os.close(holder)
        time.sleep(0.3)
        start, me = time.time(), os.getpid()
        def handler(sig, frame):
            os.fork()
        signal.signal(signal.SIGALRM, handler)
        signal.setitimer(signal.ITIMER_REAL, 0.3)
        with runners.bookkeeping_lock():
            print("parent" if os.getpid() == me else "child", round(time.time() - start, 2), flush=True)
        if os.getpid() != me:
            os._exit(0)
        os.wait()
        os.wait()
    """)
    entered = dict(line.split() for line in out.splitlines())
    assert set(entered) == {"parent", "child"}, out
    assert float(entered["child"]) > 1.2 and float(entered["parent"]) > 1.2, out



def test_an_exception_after_any_call_the_lock_makes_leaves_it_whole(tmp_path):
    """A signal handler's exception lands where the interpreter checks for pending calls: just after
    a call returns, at a loop's jump back, or as a generator resumes (which a raise in the body
    stands for). Each call the lock makes to os, fcntl and threading, to its descriptor tables' pop,
    to the guard's exit and to its sweep is made, in turn, to raise just after it returns. After each
    raise no descriptor on the lock file is open, the lock is free and its depth 0, and the next use
    holds the file lock. Single-threaded, so no wait for another thread's turn."""
    out = probe(tmp_path, """
        import threading
        class Alarm(Exception):
            pass
        count, target = [0], [0]
        def after(real):
            def call(*args, **kwargs):
                result = real(*args, **kwargs)
                count[0] += 1
                if count[0] == target[0]:
                    raise Alarm
                return result
            return call
        class Table(dict):
            def pop(self, *args):
                return after(super().pop)(*args)
        class Guard:
            def __init__(self, lock):
                self.lock = lock
            def __enter__(self):
                return self.lock.__enter__()
            def __exit__(self, *exc):
                return after(self.lock.__exit__)(*exc)
            def acquire(self, *args):
                return self.lock.acquire(*args)
            def release(self):
                return self.lock.release()
        def left():
            target_st = os.stat(lock)
            def on_lock(fd):
                try:
                    st = os.fstat(fd)
                except OSError:
                    return False
                return (st.st_dev, st.st_ino) == (target_st.st_dev, target_st.st_ino)
            return sum(on_lock(int(n)) for n in os.listdir("/dev/fd"))
        def free():
            fd = os.open(lock, os.O_WRONLY)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except OSError:
                return False
            finally:
                os.close(fd)
        with runners.bookkeeping_lock():
            pass
        names = [(os, "open"), (os, "close"), (os, "getpid"), (os, "stat"), (os, "listdir"), (os, "fstat"),
                 (fcntl, "flock"), (threading, "get_ident"), (runners, "_close_strays")]
        real = {(mod, name): getattr(mod, name) for mod, name in names}
        raised, bad = 0, []
        while True:
            target[0] += 1
            count[0] = 0
            runners._lock_fds, runners._closed_in_child = Table(runners._lock_fds), Table(runners._closed_in_child)
            runners._fd_guard = Guard(runners._fd_guard)
            for (mod, name), fn in real.items():
                setattr(mod, name, after(fn))
            hit = False
            try:
                with runners.bookkeeping_lock():
                    pass
            except Alarm:
                hit = True
            finally:
                for (mod, name), fn in real.items():
                    setattr(mod, name, fn)
                runners._fd_guard = runners._fd_guard.lock
                runners._lock_fds = dict(runners._lock_fds)
                runners._closed_in_child = dict(runners._closed_in_child)
            if not hit:
                break
            raised += 1
            depth = getattr(runners._held, "depth", 0)
            with runners.bookkeeping_lock():
                taken = not free()
            if left() or not free() or depth or not taken:
                bad.append((target[0], left(), free(), depth, taken))
        print(raised, bad)
    """)
    raised, bad = out.split(" ", 1)
    assert int(raised) > 10 and bad.strip() == "[]", out
