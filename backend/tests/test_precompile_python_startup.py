from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys


def test_precompile_script_emits_portable_unchecked_hash_bytecode(tmp_path: Path):
    payload = tmp_path / "payload"
    backend = payload / "backend"
    backend.mkdir(parents=True)
    source = backend / "main.py"
    source.write_text("STARTUP_SENTINEL = 42\n", encoding="utf-8")

    script = Path(__file__).parents[2] / "scripts" / "precompile_python_startup.py"
    result = subprocess.run(
        [sys.executable, str(script), str(payload)],
        check=True,
        capture_output=True,
        text=True,
    )

    cache = Path(importlib.util.cache_from_source(str(source)))
    bytecode = cache.read_bytes()
    assert cache.is_file()
    assert "Precompiled 1 startup modules" in result.stdout
    assert b"<stimma>/backend/main.py" in bytecode
    assert str(tmp_path).encode() not in bytecode
    # PEP 552 flags: bit 0 means hash-based, bit 1 would require Python to
    # reopen and hash the source at startup. Packaged bytecode deliberately
    # uses the unchecked form so antivirus is not pulled back into that path.
    assert int.from_bytes(bytecode[4:8], "little") & 0b11 == 0b01
