"""Non-overlapping picker bands, independent of appearance's life-stage tags.

Saved life-stage choices retain their original vocabulary-defined years. New choices
use numeric band IDs; neither a band nor a legacy choice widens a prompt's allowed ages.
"""

from typing import Dict, List, Optional, Sequence

BANDS = ((0, 1), (2, 3), (4, 5), (6, 8), (9, 12), (13, 15), (16, 17),
         (18, 24), (25, 29), (30, 34), (35, 39), (40, 49), (50, 59),
         (60, 69), (70, 79), (80, 110))


def band_id(lo: int, hi: int) -> str:
    return "80+" if lo == 80 else f"{lo}-{hi}"


def bands(fits: Optional[Sequence[str]] = None, minor: Sequence[str] = ()) -> Dict[str, List[str]]:
    from prompt_programs.variants import age_years, allowed_ages
    allowed = allowed_ages(fits, minor)
    return {band_id(lo, hi): ages for lo, hi in BANDS
            if (ages := [a for a in allowed if lo <= age_years(a) <= hi])}


def bands_of(age: str) -> tuple[str, ...]:
    from prompt_programs.variants import age_years, year_ages
    if not isinstance(age, str) or age not in year_ages([age_years(age)]):
        return ()
    y = age_years(age)
    return tuple(band_id(lo, hi) for lo, hi in BANDS if lo <= y <= hi)
