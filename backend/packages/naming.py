"""Filename templates.

A recipe declares the fields its free names can use and a default template.
The caller supplies a template string plus a case convention. Everything is
data, so the manifest records it, rebuild replays it, and a form can render
it. Platform-fixed names (``Contents.json``, ``mipmap-xxhdpi``) never pass
through here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

CASES = ("kebab", "snake", "camel", "pascal", "as-is")
_FIELD_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


class NamingError(ValueError):
    pass


@dataclass
class Naming:
    template: str
    case: str = "kebab"
    fields: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"template": self.template, "case": self.case}


def parse_naming(value: Any, *, fields: Iterable[str], default_template: str, default_case: str = "kebab") -> Naming:
    """Coerce a param value (str | dict | None) into a validated Naming."""
    allowed = tuple(fields)
    if value is None:
        template, case = default_template, default_case
    elif isinstance(value, str):
        template, case = value, default_case
    elif isinstance(value, dict):
        template = value.get("template") or default_template
        case = value.get("case") or default_case
    else:
        raise NamingError("naming must be a template string or {template, case}")
    if case not in CASES:
        raise NamingError(f"naming case must be one of {', '.join(CASES)}; got {case!r}")
    used = _FIELD_RE.findall(template)
    unknown = [f for f in used if f not in allowed and f != "ext"]
    if unknown:
        raise NamingError(
            f"naming template uses unknown field(s) {', '.join(unknown)}; "
            f"available: {', '.join(allowed)}"
        )
    stripped = _FIELD_RE.sub("", template)
    if "/" in stripped or "\\" in stripped:
        raise NamingError("naming template may not contain path separators")
    return Naming(template=template, case=case, fields=allowed)


def _words(text: str) -> list[str]:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return [w for w in re.split(r"[^A-Za-z0-9]+", text) if w]


def apply_case(stem: str, case: str) -> str:
    if case == "as-is":
        return stem
    words = _words(stem)
    if not words:
        return stem
    if case == "kebab":
        return "-".join(w.lower() for w in words)
    if case == "snake":
        return "_".join(w.lower() for w in words)
    if case == "camel":
        return words[0].lower() + "".join(w[:1].upper() + w[1:].lower() for w in words[1:])
    if case == "pascal":
        return "".join(w[:1].upper() + w[1:].lower() for w in words)
    raise NamingError(f"unknown case {case!r}")


def expand_name(naming: Naming, *, ext: str, **values: Any) -> str:
    """Expand the template with field values; returns ``stem.ext``.

    Fields the template names but the call omits expand to nothing, and the
    resulting doubled separators are collapsed, so ``{slug}-{variant}-{color}``
    with no color still reads ``acme-mark``.
    """
    ext = (ext or "").lstrip(".")
    data = {k: ("" if v is None else str(v)) for k, v in values.items()}
    has_ext_field = "{ext}" in naming.template
    template = naming.template.replace("{ext}", "") if has_ext_field else naming.template

    def sub(match: re.Match) -> str:
        return data.get(match.group(1), "")

    stem = _FIELD_RE.sub(sub, template)
    stem = re.sub(r"[-_ .]{2,}", lambda m: m.group(0)[0], stem).strip("-_ .")
    stem = apply_case(stem, naming.case) if naming.case != "as-is" else stem
    if not stem:
        raise NamingError("naming template expanded to an empty name")
    return f"{stem}.{ext}" if ext else stem
