from ci_shard import module_assignments


def test_partition_is_complete_stable_and_keeps_modules_together():
    nodes = [f'{module}::test_{i}' for module, size in [('a', 20), ('b', 11), ('c', 8), ('d', 4), ('e', 3)] for i in range(size)]
    mapping = module_assignments(nodes, 4)
    assert mapping == module_assignments(list(reversed(nodes)), 4)
    shards = [{node for node in nodes if mapping[node.split('::')[0]] == i} for i in range(4)]
    assert set.union(*shards) == set(nodes)
    assert sum(map(len, shards)) == len(nodes)
    assert all(shards)
    assert set(mapping) == {'a', 'b', 'c', 'd', 'e'}
