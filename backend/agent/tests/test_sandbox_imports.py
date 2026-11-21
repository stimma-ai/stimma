"""run_code import surface: stdlib modules that C code imports on the caller's behalf."""
import pytest

from agent.v2.code_runtime import build_safe_builtins


def _run(tmp_path, source: str) -> dict:
    scope = {"__builtins__": dict(build_safe_builtins(tmp_path, print))}
    exec(compile(source, "<run_code>", "exec"), scope)
    return scope


@pytest.mark.parametrize("source", [
    "from datetime import datetime\nout = datetime(2020, 1, 2).strftime('%Y-%m-%d')",
    "import datetime\nout = datetime.datetime(2020, 1, 2).strftime('%Y-%m-%d')",
    "import datetime as _dt\nout = _dt.datetime.strptime('2020-01-02', '%Y-%m-%d').strftime('%Y-%m-%d')",
    "from datetime import date\nout = date(2020, 1, 2).timetuple() and '2020-01-02'",
])
def test_datetime_works_however_it_is_imported(tmp_path, source):
    # datetime's C implementation imports time/_strptime through the calling
    # frame's __import__ (the sandbox's); that used to be denied as "Import 'time'".
    assert _run(tmp_path, source)["out"] == "2020-01-02"


def test_time_is_importable_but_sleep_points_at_asyncio(tmp_path):
    assert _run(tmp_path, "import time\nout = time.time()")["out"] > 0
    with pytest.raises(AttributeError, match="asyncio.sleep"):
        _run(tmp_path, "import time\ntime.sleep(0)")


def test_unrelated_modules_are_still_denied(tmp_path):
    with pytest.raises(ImportError, match="Import 'subprocess' is not allowed"):
        _run(tmp_path, "import subprocess")


def test_json_dumps_sdk_results_paths_and_numpy(tmp_path):
    from pathlib import Path

    from agent.v2.code_runtime import ToolResult

    scope = {"__builtins__": dict(build_safe_builtins(tmp_path, print)),
             "result": ToolResult(path=Path("clip.mp4"), media_id=7), "Path": Path}
    exec(compile(
        "import json, numpy as np\n"
        "with open('state.json', 'w') as f:\n"
        "    json.dump({'results': [result], 'where': Path('a/b.png'), 'n': np.int64(3), 'v': np.zeros(2)}, f)\n"
        "out = json.loads(open('state.json').read())\n"
        "from json import dumps\n"
        "custom = dumps({1, 2}, default=lambda v: sorted(v) if isinstance(v, set) else str(v))\n",
        "<run_code>", "exec"), scope)
    out = scope["out"]
    assert out["results"][0]["path"] == "clip.mp4" and out["results"][0]["media_id"] == 7
    assert out["where"] == "a/b.png" and out["n"] == 3 and out["v"] == [0.0, 0.0]
    assert scope["custom"] == "[1, 2]"
