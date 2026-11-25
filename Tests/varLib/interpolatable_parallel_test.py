"""Tests for optional parallel (multi-worker) interpolatable analysis.

These focus on the contract added on top of the serial implementation:

* configurable worker count (library ``workers=`` / CLI ``--workers``/``-j``);
* identical glyph ordering, diagnostics (dict and ordered stream), JSON and
  text reports and exit semantics versus serial mode;
* single-worker and empty-input handling;
* missing / corrupt input files and exceptions raised inside workers;
* prompt pool shutdown with no zombie children.
"""

from __future__ import annotations

import glob
import json
import multiprocessing as mp
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import pytest

from fontTools.ttLib import TTFont
from fontTools.varLib.interpolatable import (
    main as interpolatable_main,
    resolve_worker_count,
)
from fontTools.varLib.interpolatable import test as run_interpolatable
from fontTools.varLib.interpolatable import test_gen as iter_interpolatable

try:
    import scipy  # noqa: F401

    _HAS_MATCHER = True
except ImportError:
    try:
        import munkres  # noqa: F401

        _HAS_MATCHER = True
    except ImportError:
        _HAS_MATCHER = False

pytestmark = pytest.mark.skipif(
    not _HAS_MATCHER, reason="scipy or munkres is required for the matching tests"
)

DATA_DIR = Path(__file__).resolve().parent / "data"
TTX_DIR = DATA_DIR / "master_ttx_interpolatable_ttf"
FORKS_AVAILABLE = "fork" in mp.get_all_start_methods()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _compile(pattern, tmpdir):
    out = []
    for ttx in sorted(glob.glob(str(TTX_DIR / pattern))):
        font = TTFont()
        font.importXML(ttx)
        target = os.path.join(tmpdir, Path(ttx).stem + ".ttf")
        font.save(target, reorderTables=None)
        font.close()
        out.append(target)
    return out


def _glyphsets(paths, fill_missing=True):
    sets = []
    fonts = []
    for path in paths:
        font = TTFont(path)
        fonts.append(font)
        gs = font.getGlyphSet()
        sets.append({name: gs[name] for name in gs.keys()})
    if fill_missing:
        all_names = {name for gs in sets for name in gs}
        for gs in sets:
            for name in all_names - set(gs):
                gs[name] = None
    return sets


def _cli_json(argv):
    buf = StringIO()
    with redirect_stdout(buf):
        interpolatable_main(list(argv))
    return json.loads(buf.getvalue())


# ---------------------------------------------------------------------------
# worker count resolution
# ---------------------------------------------------------------------------


def test_resolve_worker_count_defaults_to_serial():
    assert resolve_worker_count() == 1
    assert resolve_worker_count(None) == 1
    assert resolve_worker_count(1) == 1
    assert resolve_worker_count("1") == 1


def test_resolve_worker_count_explicit_values():
    assert resolve_worker_count(3) == 3
    assert resolve_worker_count("4") == 4
    assert resolve_worker_count(workers=2) == 2
    assert resolve_worker_count(jobs=5) == 5
    assert resolve_worker_count(processes=6) == 6
    assert resolve_worker_count(n_jobs=7) == 7


def test_resolve_worker_count_aliases_precedence():
    # jobs wins over the generic workers spelling
    assert resolve_worker_count(workers=2, jobs=9) == 9


def test_resolve_worker_count_zero_means_all_cpus():
    n = resolve_worker_count(0)
    assert n >= 1
    assert n == (os.cpu_count() or 1)
    assert resolve_worker_count(-3) >= 1


def test_resolve_worker_count_invalid_falls_back_to_one():
    assert resolve_worker_count("not-an-int") == 1


# ---------------------------------------------------------------------------
# empty input
# ---------------------------------------------------------------------------


def test_empty_glyphsets_library():
    assert run_interpolatable([]) == {}
    assert run_interpolatable([], workers=1) == {}
    assert run_interpolatable([], workers=4) == {}
    assert list(iter_interpolatable([], workers=4)) == []


def test_empty_glyph_list_library():
    assert run_interpolatable([{}, {}], glyphs=[], workers=2) == {}
    assert list(iter_interpolatable([{}, {}], glyphs=[], workers=8)) == []


def test_cli_without_inputs_exits_2():
    with pytest.raises(SystemExit) as excinfo:
        interpolatable_main(["--workers", "2"])
    assert excinfo.value.code == 2


# ---------------------------------------------------------------------------
# serial / parallel equivalence on fixed multi-master samples
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def family2_ttfs():
    tmp = tempfile.mkdtemp(prefix="interp-par-")
    try:
        yield _compile("TestFamily2-Master*.ttx", tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope="module")
def sparse_ttfs():
    tmp = tempfile.mkdtemp(prefix="interp-par-sparse-")
    try:
        yield _compile("SparseMasters-*.ttx", tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope="module")
def family3_ttfs():
    tmp = tempfile.mkdtemp(prefix="interp-par-f3-")
    try:
        yield _compile("TestFamily3-*.ttx", tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.parametrize("workers", [1, 2, 4])
def test_library_dict_matches_serial(family2_ttfs, workers):
    gs = _glyphsets(family2_ttfs, fill_missing=False)
    serial = run_interpolatable(gs)
    parallel = run_interpolatable(gs, workers=workers)
    assert parallel == serial


@pytest.mark.parametrize("workers", [1, 2, 3])
def test_ordered_stream_matches_serial(sparse_ttfs, workers):
    gs = _glyphsets(sparse_ttfs)
    serial_stream = list(iter_interpolatable(gs))
    parallel_stream = list(
        iter_interpolatable(gs, workers=workers, start_method="fork")
    )
    assert parallel_stream == serial_stream
    # input glyph order is preserved
    glyph_order = []
    for glyphname, _ in serial_stream:
        if not glyph_order or glyph_order[-1] != glyphname:
            glyph_order.append(glyphname)
    par_order = []
    for glyphname, _ in parallel_stream:
        if not par_order or par_order[-1] != glyphname:
            par_order.append(glyphname)
    assert par_order == glyph_order


def test_sparse_missing_diagnostics_identical(sparse_ttfs):
    gs = _glyphsets(sparse_ttfs)
    names = [Path(p).stem for p in sparse_ttfs]
    serial = run_interpolatable(gs, names=names)
    parallel = run_interpolatable(gs, names=names, workers=2, start_method="fork")
    assert parallel == serial
    assert serial["a"] == [
        {"type": "missing", "master": "SparseMasters-Medium", "master_idx": 1}
    ]


def test_eight_master_family_equivalence(family3_ttfs):
    gs = _glyphsets(family3_ttfs, fill_missing=False)
    serial_items = list(iter_interpolatable(gs))
    parallel_items = list(iter_interpolatable(gs, workers=4, start_method="fork"))
    assert parallel_items == serial_items
    assert run_interpolatable(gs, workers=4, start_method="fork") == run_interpolatable(
        gs
    )


@pytest.mark.parametrize("flag", ["--workers", "--jobs", "--num-workers"])
def test_cli_json_matches_serial(sparse_ttfs, flag):
    base = _cli_json(["--json", *sparse_ttfs])
    parallel = _cli_json(["--json", flag, "2", *sparse_ttfs])
    assert parallel == base


def test_cli_short_j_flag(family2_ttfs):
    base = _cli_json(["--json", *family2_ttfs])
    parallel = _cli_json(["--json", "-j", "2", *family2_ttfs])
    assert parallel == base


def test_cli_text_report_byte_identical(sparse_ttfs):
    out = StringIO()
    with redirect_stdout(out):
        interpolatable_main([*sparse_ttfs])
    serial_text = out.getvalue()

    out = StringIO()
    with redirect_stdout(out):
        interpolatable_main(["-j", "2", *sparse_ttfs])
    parallel_text = out.getvalue()
    assert parallel_text == serial_text


def test_main_return_value_truthiness_matches(sparse_ttfs):
    serial_problems = interpolatable_main(["--quiet", *sparse_ttfs])
    parallel_problems = interpolatable_main(["--quiet", "-j", "2", *sparse_ttfs])
    assert bool(serial_problems) is bool(parallel_problems) is True
    assert parallel_problems == serial_problems


def test_clean_sample_returns_none(family2_ttfs):
    assert interpolatable_main(["--quiet", *family2_ttfs]) is None
    assert interpolatable_main(["--quiet", "-j", "2", *family2_ttfs]) is None


# ---------------------------------------------------------------------------
# failure paths: unopenable / corrupt inputs are loaded before the pool, so
# parallel mode raises exactly like serial mode
# ---------------------------------------------------------------------------


def test_missing_file_raises_identically(sparse_ttfs):
    missing = os.path.join(os.path.dirname(sparse_ttfs[0]), "does-not-exist.ttf")
    with pytest.raises(Exception) as serial_exc:
        interpolatable_main(["--quiet", sparse_ttfs[0], missing])
    with pytest.raises(Exception) as parallel_exc:
        interpolatable_main(["--quiet", "-j", "2", sparse_ttfs[0], missing])
    assert type(parallel_exc.value) is type(serial_exc.value)


def test_corrupt_font_raises_identically(sparse_ttfs, tmp_path):
    bad = tmp_path / "corrupt.ttf"
    bad.write_bytes(b"this is certainly not a TrueType/OpenType font")
    with pytest.raises(Exception) as serial_exc:
        interpolatable_main(["--quiet", sparse_ttfs[0], str(bad)])
    with pytest.raises(Exception) as parallel_exc:
        interpolatable_main(["--quiet", "--workers", "2", sparse_ttfs[0], str(bad)])
    assert type(parallel_exc.value) is type(serial_exc.value)


# ---------------------------------------------------------------------------
# failures raised inside a worker
# ---------------------------------------------------------------------------


class _BrokenGlyph:
    """Top-level (picklable under spawn) glyph that always fails."""

    def draw(self, pen, *args, **kwargs):
        raise ValueError("boom-from-broken-glyph")


def _broken_glyphsets():
    broken = _BrokenGlyph()
    return [{"bad": broken}, {"bad": broken}]


@pytest.mark.skipif(not FORKS_AVAILABLE, reason="fork start method unavailable")
def test_worker_exception_matches_serial():
    with pytest.raises(ValueError, match="boom-from-broken-glyph"):
        run_interpolatable(_broken_glyphsets(), glyphs=["bad"])
    with pytest.raises(ValueError, match="boom-from-broken-glyph"):
        run_interpolatable(
            _broken_glyphsets(),
            glyphs=["bad"],
            workers=2,
            start_method="fork",
        )


class _HardExitInWorkerGlyph:
    """Kills the worker process, but raises normally in the parent so the
    serial-suffix fallback can reproduce serial semantics."""

    def draw(self, pen, *args, **kwargs):
        if mp.current_process().name != "MainProcess":
            os._exit(7)
        raise RuntimeError("parent-serial-fallback-marker")


def _zombie_children():
    zombies = []
    mypid = os.getpid()
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            text = open(f"/proc/{pid}/stat").read()
            after = text[text.rfind(")") + 2 :].split()
            state, ppid = after[0], int(after[1])
        except (OSError, ValueError, IndexError):
            continue
        if ppid == mypid and state == "Z":
            zombies.append(int(pid))
    return zombies


def _child_pids():
    mypid = os.getpid()
    pids = set()
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            stat = open(f"/proc/{pid}/stat").read()
            after = stat[stat.rfind(")") + 2 :].split()
            ppid = int(after[1])
        except (OSError, ValueError, IndexError):
            continue
        if ppid == mypid:
            pids.add(int(pid))
    return pids


@pytest.mark.skipif(
    not FORKS_AVAILABLE or not os.path.isdir("/proc"),
    reason="needs fork and a Linux /proc filesystem",
)
def test_hard_worker_death_falls_back_without_zombies():
    before_children = _child_pids()
    glyph = _HardExitInWorkerGlyph()
    glyphsets = [{"bad": glyph}, {"bad": glyph}]

    with pytest.raises(RuntimeError, match="parent-serial-fallback-marker"):
        run_interpolatable(glyphsets, glyphs=["bad"], workers=2, start_method="fork")

    # Pool shutdown reaped every worker: no zombie children.
    assert _zombie_children() == []

    # Any newly introduced direct child may only be multiprocessing's
    # resource tracker, which exits with the parent.
    leftover = _child_pids() - before_children
    real_leftovers = set()
    for pid in leftover:
        try:
            cmdline = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ")
        except OSError:
            continue
        if b"resource_tracker" not in cmdline:
            real_leftovers.add(pid)
    assert real_leftovers == set()


@pytest.mark.skipif(
    not FORKS_AVAILABLE or not os.path.isdir("/proc"),
    reason="needs fork and a Linux /proc filesystem",
)
def test_early_generator_close_reaps_pool(sparse_ttfs):
    gs = _glyphsets(sparse_ttfs)
    before = _child_pids()
    gen = iter_interpolatable(gs, workers=4, start_method="fork")
    # Consume at most one item, then abandon the generator early.
    next(gen, None)
    gen.close()

    assert _zombie_children() == []
    leftover = _child_pids() - before
    real_leftovers = set()
    for pid in leftover:
        try:
            cmdline = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ")
        except OSError:
            continue
        if b"resource_tracker" not in cmdline:
            real_leftovers.add(pid)
    assert real_leftovers == set()


# ---------------------------------------------------------------------------
# real subprocess entry point (validates -m entry + spawn/forkserver safety)
# ---------------------------------------------------------------------------


def _subprocess_env():
    # Make the child import the same fontTools tree the tests imported.
    lib_dir = str(_fonttools_path())
    existing = os.environ.get("PYTHONPATH")
    env = dict(os.environ)
    env["PYTHONPATH"] = lib_dir + (os.pathsep + existing if existing else "")
    return env


def _fonttools_path():
    import fontTools

    return Path(fontTools.__file__).resolve().parent.parent


def test_subprocess_cli_parallel_json_matches(tmp_path):
    ttfs = _compile("TestFamily2-Master*.ttx", str(tmp_path))
    env = _subprocess_env()

    def run(extra):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "fontTools.varLib.interpolatable",
                "--json",
                *extra,
                *ttfs,
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout)

    serial = run([])
    parallel = run(["--workers", "2"])
    assert parallel == serial


def test_subprocess_cli_no_inputs_exit_2(tmp_path):
    env = _subprocess_env()
    proc = subprocess.run(
        [sys.executable, "-m", "fontTools.varLib.interpolatable", "-j", "2"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 2
