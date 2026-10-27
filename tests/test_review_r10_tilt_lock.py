"""Round-10 tilt endpoint probes, with invented MOCK forecasts only."""

import numpy as np
import pytest
from mock import MOCK_response

from i86.response import parse, share_key
from i86.simulate import exact_tilt, simulate


def _endpoint_forecasts(graph, middle, later):
    obj = MOCK_response(graph)
    probs = {'yes_50.5': 0., 'yes_60.0': middle, 'yes_72.0': later}
    for key, row in obj['nodes']['ban_status']['forecasts'].items():
        p = probs[key]
        row.update(repealed=1-p, congress=0., court=0., not_certified=0., certified=p)
    for x in graph.share_grid:
        obj['nodes']['yes_share']['forecasts']['all'][share_key(x)] = float(np.clip((x-.5)/.3, 0., 1.))
    return parse(graph, obj)


def test_upper_endpoint_unused_answer_preserves_tilt_scale(graph):
    restrict = {'ban_status': {'certified'}}
    band = (.5, .6)
    quiet = _endpoint_forecasts(graph, 5e-324, 5e-324)
    loud = _endpoint_forecasts(graph, 5e-324, 1.)
    a = exact_tilt(graph, quiet, restrict, band)[1]
    b = exact_tilt(graph, loud, restrict, band)[1]
    assert a.scale == b.scale


def test_upper_endpoint_unused_answer_does_not_drop_positive_draws(graph):
    restrict = {'ban_status': {'certified'}}
    draws = simulate(graph, _endpoint_forecasts(graph, 5e-324, 1.), 64, 34,
                     share_band=(.5, .6), restrict=restrict)
    assert np.all(draws['_weight'] == 1.)


def test_upper_endpoint_control_without_loud_unused_answer(graph):
    restrict = {'ban_status': {'certified'}}
    draws = simulate(graph, _endpoint_forecasts(graph, 5e-324, 5e-324), 64, 34,
                     share_band=(.5, .6), restrict=restrict)
    assert np.all(draws['_weight'] == 1.)


def test_fallback_marker_does_not_leak_reused_fd_after_another_fork(tmp_path, monkeypatch):
    """The spare-invalid/EMFILE fallback is supported; a vanished parent thread has no frame to unwind."""
    import json
    import os
    import signal
    import threading

    from i86 import runners
    from test_lock_fork import no_descriptor_free

    for name in ('RUNS', 'WORK', 'STAGE', 'JOBS'):
        monkeypatch.setattr(runners, name, tmp_path / name.lower())
    other = tmp_path / 'MOCK-other'
    other.write_text('MOCK\n')
    impostor = os.open(other, os.O_RDONLY)
    monkeypatch.setattr(runners, '_spare_null', impostor)
    monkeypatch.setattr(runners, '_closed_in_child', {})
    rd, wr = os.pipe()
    held, release = threading.Event(), threading.Event()
    seen = {}

    def worker():
        with runners.bookkeeping_lock():
            seen['fd'] = next(iter(runners._lock_fds))
            held.set()
            release.wait(20)

    thread = threading.Thread(target=worker, name='MOCK-vanishing-lock-owner')
    thread.start()
    child = None
    try:
        assert held.wait(10)
        with no_descriptor_free():
            child = os.fork()
            if child == 0:
                signal.alarm(30)
        if child == 0:
            try:
                marker = seen['fd'] in runners._closed_in_child.values()
                with runners.bookkeeping_lock():
                    fd = next(iter(runners._lock_fds))
                    reused = fd == seen['fd']
                    grandchild = os.fork()
                if grandchild == 0:
                    try:
                        st = os.fstat(fd)
                        null = os.stat(os.devnull)
                        leaked = (st.st_dev, st.st_ino) == (null.st_dev, null.st_ino)
                    except OSError:
                        leaked = False
                    result = {'marker': marker, 'reused': reused, 'leaked': leaked,
                              'tracked': sorted(runners._lock_fds), 'fd': fd}
                    os.write(wr, json.dumps(result).encode())
                    os._exit(0)
                _, status = os.waitpid(grandchild, 0)
                os._exit(os.waitstatus_to_exitcode(status))
            except BaseException:
                os._exit(2)
        release.set()
        thread.join(10)
        os.close(wr)
        wr = None
        result = json.loads(os.read(rd, 4096) or b'{}')
        _, status = os.waitpid(child, 0)
        child = None
        assert os.waitstatus_to_exitcode(status) == 0, result
        # The vanished thread's descriptor is closed and not recorded: no frame here refers to it.
        assert not result['marker'] and result['reused'] and result['tracked'] == [], result
        assert not result['leaked'], result
    finally:
        release.set()
        thread.join(10)
        if child not in (None, 0):
            os.waitpid(child, 0)
        os.close(rd)
        if wr is not None:
            os.close(wr)
        os.close(impostor)
