"""Partition CI tests without splitting stateful module-scoped fixtures.

Loaded explicitly with pytest -p ci_shard. Local test execution is unchanged.
Every shard collects the same suite and applies the same deterministic mapping.
"""

from collections import Counter
import os

import pytest


def module_assignments(nodeids, count):
    weights = Counter(nodeid.split('::', 1)[0] for nodeid in nodeids)
    loads = [0] * count
    assignments = {}
    for module in sorted(weights, key=lambda name: (-weights[name], name)):
        shard = min(range(count), key=lambda index: (loads[index], index))
        assignments[module] = shard
        loads[shard] += weights[module]
    return assignments


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    index, count = map(int, os.environ['STIMMA_TEST_SHARD'].split('/'))
    if not 1 <= index <= count:
        raise pytest.UsageError('STIMMA_TEST_SHARD must be INDEX/COUNT, starting at 1')
    assignments = module_assignments([item.nodeid for item in items], count)
    selected, deselected = [], []
    for item in items:
        destination = selected if assignments[item.nodeid.split('::', 1)[0]] == index - 1 else deselected
        destination.append(item)
    config.hook.pytest_deselected(items=deselected)
    items[:] = selected
