"""Split request-sized ``IN (...)`` lists to fit SQLite's bound-parameter cap."""

# Older SQLite builds cap bound parameters at 999 per statement (32766 since
# 3.32). Queue-sized ``IN (...)`` lists, such as every Asset in a large Trash,
# are split into slices that fit either limit.
SQL_IN_CHUNK_SIZE = 900


def sql_in_chunks(values, size: int | None = None) -> list[list]:
    """Split ``values`` into slices small enough for one SQLite ``IN`` list.

    Pass a smaller ``size`` when one statement binds two such lists.
    """
    values = list(values)
    size = size or SQL_IN_CHUNK_SIZE
    return [values[start:start + size] for start in range(0, len(values), size)]
