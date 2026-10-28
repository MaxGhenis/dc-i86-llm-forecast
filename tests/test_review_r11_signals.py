"""Round-11 finding 40 and round-12 findings 3, 4 and 12: bookkeeping_lock under signal handlers, for
the one-descriptor lock. Each probe runs in its own Python process, so its handlers and forks stay
out of the test runner. All paths are temporary MOCK directories."""

import subprocess
import sys
import textwrap

SETUP = """
import fcntl, inspect, os, signal, sys, threading, time
from pathlib import Path
from i86 import runners
tmp = Path(sys.argv[1])
runners.STAGE = tmp / "stage"
lock = tmp / "stage.lock"
paths = [tmp / "stage_a", tmp / "stage_b"]
locks = [p.with_name(p.name + ".lock") for p in paths]
def on_lock(path):
    if not path.exists():
        return 0
    target = os.stat(path)
    def same(fd):
        try:
            st = os.fstat(fd)
        except OSError:
            return False
        return (st.st_dev, st.st_ino) == (target.st_dev, target.st_ino)
    return sum(same(int(n)) for n in os.listdir("/dev/fd"))
def free(path):
    if not path.exists():
        return True
    fd = os.open(path, os.O_WRONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False
    finally:
        os.close(fd)
def mutex_free():
    out = []
    def attempt():
        got = runners._mutex.acquire(blocking=False)
        if got:
            runners._mutex.release()
        out.append(got)
    t = threading.Thread(target=attempt)
    t.start()
    t.join()
    return out[0]
def lost():
    # Descriptors on the lock files other than the one the lock keeps.
    return sum(map(on_lock, locks)) - (runners._fd is not None)
source, first = inspect.getsourcelines(runners._open)
OPEN_LINE = first + next(i for i, line in enumerate(source) if "os.open(" in line)
"""


def probe(tmp_path, code: str) -> str:
    proc = subprocess.run([sys.executable, "-c", SETUP + textwrap.dedent(code), str(tmp_path)],
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def test_a_raising_handler_leaves_the_lock_free_and_loses_only_what_it_cut_off_opening(tmp_path):
    """A SIGALRM handler raises at most once per use, wherever the interpreter lets it land. The uses
    alternate between two lock files, so each opens a descriptor and closes the other. After the
    loop, neither file is locked, and every descriptor left on them but the kept one was lost to a
    raise as `_open` stored what os.open returned."""
    out = probe(tmp_path, """
        class Alarm(Exception):
            pass
        armed, at_open, alarms = [False], [0], [0]
        def handler(sig, frame):
            if armed[0]:
                armed[0] = False
                while frame.f_code is handler.__code__:  # a timer signal handled inside this handler
                    frame = frame.f_back
                at_open[0] += frame.f_code is runners._open.__code__ and frame.f_lineno == OPEN_LINE
                raise Alarm
        signal.signal(signal.SIGALRM, handler)
        signal.setitimer(signal.ITIMER_REAL, 1e-5, 1e-5)
        for i in range(3000):
            runners.STAGE = paths[i % 2]
            armed[0] = True
            try:
                with runners.bookkeeping_lock():
                    pass
            except Alarm:
                alarms[0] += 1
            armed[0] = False
        signal.setitimer(signal.ITIMER_REAL, 0)
        print(alarms[0], at_open[0], lost(), all(map(free, locks)), runners._depth, mutex_free())
    """)
    alarms, at_open, left, free_, depth, mutex = out.split()
    assert int(alarms) > 1000 and 0 <= int(left) <= int(at_open), out
    assert free_ == "True" and depth == "0" and mutex == "True", out


def test_a_child_forked_by_a_handler_while_waiting_never_enters_the_use(tmp_path):
    """A handler must not fork (the module notes say so); one that does as its thread waits makes a
    child whose wait fails, with the descriptor it waited on closed, so the child never runs the
    use's body. The parent enters once the other process lets go."""
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
        try:
            with runners.bookkeeping_lock():
                print("parent" if os.getpid() == me else "child", "entered", round(time.time() - start, 2),
                      flush=True)
        except (OSError, RuntimeError) as exc:
            print("parent" if os.getpid() == me else "child", "raised", type(exc).__name__, flush=True)
        if os.getpid() != me:
            os._exit(0)
        os.wait()
        os.wait()
    """)
    lines = {line.split()[0]: line.split()[1:] for line in out.splitlines()}
    assert set(lines) == {"parent", "child"}, out
    assert lines["child"][0] == "raised", out
    assert lines["parent"][0] == "entered" and float(lines["parent"][1]) > 1.2, out


def test_an_exception_after_any_call_the_lock_makes_leaves_it_whole(tmp_path):
    """A signal handler's exception lands where the interpreter checks for pending calls: just after
    a call returns, as a function starts, at a loop's jump back, or as a generator resumes (which a
    raise in the body stands for). Each call the lock makes to os, fcntl and contextlib, to `_open`
    (as it starts, and once it returns), and to the guard's and the mutex's exits is made, in turn,
    to raise there. The uses alternate between two lock files, so each opens and closes a descriptor.
    Straight after each raise is handled, before any other use: neither lock file is locked, the
    depth is 0, the mutex is free, and no descriptor was lost but one cut off as os.open returned.
    The next use then holds the file lock."""
    out = probe(tmp_path, """
        import contextlib
        class Alarm(Exception):
            pass
        count, target, where = [0], [0], [None]
        def tick(name):
            count[0] += 1
            if count[0] == target[0]:
                where[0] = name
                raise Alarm
        def after(real, name):
            def call(*args, **kwargs):
                result = real(*args, **kwargs)
                tick(name)
                return result
            return call
        def around(real, name):
            def call(*args, **kwargs):
                tick(name + " starts")
                result = real(*args, **kwargs)
                tick(name)
                return result
            return call
        class Exits:
            def __init__(self, lock, name):
                self.lock, self.name = lock, name
            def __enter__(self):
                return self.lock.__enter__()
            def __exit__(self, *exc):
                result = self.lock.__exit__(*exc)
                tick(self.name)
                return result
            def acquire(self, *args, **kwargs):
                return self.lock.acquire(*args, **kwargs)
            def release(self):
                return self.lock.release()
        real = {(os, "open"): os.open, (os, "close"): os.close, (fcntl, "flock"): fcntl.flock,
                (Path, "mkdir"): Path.mkdir}
        real_open, real_next = runners._open, next
        raised, bad, i, hits = 0, [], 0, set()
        while True:
            i += 1
            target[0], count[0], where[0] = i, 0, None
            runners.STAGE = paths[i % 2]
            guard, mutex = runners._fd_guard, runners._mutex
            for (mod, name), fn in real.items():
                setattr(mod, name, after(fn, name))
            runners._open = around(real_open, "_open")
            contextlib.next = after(real_next, "next")
            runners._fd_guard, runners._mutex = Exits(guard, "guard exit"), Exits(mutex, "mutex exit")
            hit = False
            try:
                with runners.bookkeeping_lock():
                    tick("body")
            except Alarm:
                hit = True
            finally:
                for (mod, name), fn in real.items():
                    setattr(mod, name, fn)
                runners._open = real_open
                del contextlib.next
                runners._fd_guard, runners._mutex = guard, mutex
            if not hit:
                break
            raised += 1
            hits.add(where[0])
            state = (where[0], lost(), all(map(free, locks)), runners._depth, mutex_free())
            with runners.bookkeeping_lock():
                taken = not free(runners.STAGE.with_name(runners.STAGE.name + ".lock"))
            expected_lost = 1 if where[0] == "open" else 0
            if state[1:] != (expected_lost, True, 0, True) or not taken:
                bad.append((*state, taken))
            if where[0] == "open":  # close the lost descriptor, so the next count starts afresh
                target_st = os.stat(locks[i % 2])
                for name in os.listdir("/dev/fd"):
                    fd = int(name)
                    try:
                        st = os.fstat(fd)
                    except OSError:
                        continue
                    if fd != runners._fd and (st.st_dev, st.st_ino) == (target_st.st_dev, target_st.st_ino):
                        os.close(fd)
        print(raised, "|".join(sorted(hits)), bad, sep="|")
    """)
    raised, *hits, bad = out.split("|")
    assert set(hits) == {"open", "close", "flock", "_open starts", "_open", "next", "guard exit",
                                    "mutex exit", "body", "mkdir"}, out
    assert bad.strip() == "[]", out
