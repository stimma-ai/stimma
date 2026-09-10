import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('publication_gate', Path(__file__).resolve().parents[2] / 'scripts/wait-for-quality-gate.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def job(status='completed', conclusion='success', name='Quality gate / Quality gate passed'):
    return {'name': name, 'status': status, 'conclusion': conclusion}


def test_only_completed_aggregate_gate_allows_publication():
    assert not gate.gate_result([])
    assert not gate.gate_result([job(name='Quality gate / Backend tests')])
    assert not gate.gate_result([job(status='in_progress', conclusion=None)])
    assert gate.gate_result([job()])


@pytest.mark.parametrize('conclusion', ['failure', 'cancelled', 'skipped', 'timed_out', None])
def test_unsuccessful_gate_never_publishes(conclusion):
    with pytest.raises(RuntimeError):
        gate.gate_result([job(conclusion=conclusion)])


def test_ambiguous_gate_never_publishes():
    with pytest.raises(RuntimeError):
        gate.gate_result([job(), job()])
