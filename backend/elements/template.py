"""Block-only conditional templates for ELEMENT.md (and, later, SKILL.md).

Only block tags are recognized::

    {{#if <expr>}} ... {{#elif <expr>}} ... {{else}} ... {{/if}}
    {{#unless <expr>}} ... {{else}} ... {{/unless}}

Every other ``{{...}}`` (prompt wildcards, segments) passes through untouched.

Expressions: identifiers, strings, numbers, ``true``/``false``, lists
``[a, b]``, ``== != < <= > >=``, ``in`` / ``not in``, ``and`` / ``or`` /
``not`` and parentheses. An unknown identifier is falsy and adds a warning.
A malformed template renders as its raw text with ``valid=False``.

A block tag alone on its line takes the whole line with it, so conditionals
leave no blank-line litter; runs of blank lines are collapsed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Union

# Context every consumer may supply. A condition on one of these is never an
# "unknown variable": a surface that lacks the fact simply leaves it unset.
STANDARD_VARIABLES = frozenset({
    "model_family", "task_type", "media_kind", "supports_images", "max_ref_images",
    "lora_available", "lora_active", "refs_active", "aspect_ratio", "orientation", "surface",
})

__all__ = ["STANDARD_VARIABLES", "RenderedTemplate", "TemplateError", "render", "strip_blocks", "referenced_vars", "check"]


class TemplateError(ValueError):
    pass


@dataclass
class RenderedTemplate:
    text: str
    referenced_vars: frozenset[str]
    warnings: list[str] = field(default_factory=list)
    valid: bool = True


# Expressions ----------------------------------------------------------------

_TOKEN = re.compile(
    r"""\s*(?:
        (?P<str>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
      | (?P<num>-?\d+(?:\.\d+)?)
      | (?P<op>==|!=|<=|>=|<|>|\(|\)|\[|\]|,)
      | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
    )""",
    re.VERBOSE,
)
_KEYWORDS = {"and", "or", "not", "in", "true", "false"}


def _tokenize(source: str) -> list[tuple[str, Any]]:
    tokens: list[tuple[str, Any]] = []
    pos = 0
    source = source.rstrip()
    while pos < len(source):
        m = _TOKEN.match(source, pos)
        if m is None or m.end() == pos:
            raise TemplateError(f"can't read {source[pos:].strip()!r} in condition {source.strip()!r}")
        pos = m.end()
        if m.group("str") is not None:
            raw = m.group("str")[1:-1]
            tokens.append(("lit", re.sub(r"\\(.)", r"\1", raw)))
        elif m.group("num") is not None:
            text = m.group("num")
            tokens.append(("lit", float(text) if "." in text else int(text)))
        elif m.group("op") is not None:
            tokens.append(("op", m.group("op")))
        else:
            word = m.group("ident")
            if word in ("true", "false"):
                tokens.append(("lit", word == "true"))
            elif word in _KEYWORDS:
                tokens.append(("kw", word))
            else:
                tokens.append(("var", word))
    return tokens


# AST nodes for expressions are tuples: ("lit", v) ("var", name) ("list", [..])
# ("not", e) ("and", a, b) ("or", a, b) ("cmp", op, a, b)

class _ExprParser:
    def __init__(self, source: str):
        self.source = source.strip()
        self.tokens = _tokenize(source)
        self.i = 0

    def parse(self):
        if not self.tokens:
            raise TemplateError("a condition is empty")
        node = self._or()
        if self.i != len(self.tokens):
            raise TemplateError(f"unexpected {self.tokens[self.i][1]!r} in condition {self.source!r}")
        return node

    def _peek(self, kind: str, value: Any = None) -> bool:
        if self.i >= len(self.tokens):
            return False
        k, v = self.tokens[self.i]
        return k == kind and (value is None or v == value)

    def _take(self, kind: str, value: Any = None):
        if not self._peek(kind, value):
            got = self.tokens[self.i][1] if self.i < len(self.tokens) else "the end"
            want = value if value is not None else kind
            raise TemplateError(f"expected {want!r} but found {got!r} in condition {self.source!r}")
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def _or(self):
        node = self._and()
        while self._peek("kw", "or"):
            self.i += 1
            node = ("or", node, self._and())
        return node

    def _and(self):
        node = self._not()
        while self._peek("kw", "and"):
            self.i += 1
            node = ("and", node, self._not())
        return node

    def _not(self):
        if self._peek("kw", "not"):
            self.i += 1
            return ("not", self._not())
        return self._cmp()

    def _cmp(self):
        left = self._atom()
        for op in ("==", "!=", "<=", ">=", "<", ">"):
            if self._peek("op", op):
                self.i += 1
                return ("cmp", op, left, self._atom())
        if self._peek("kw", "in"):
            self.i += 1
            return ("cmp", "in", left, self._atom())
        if self._peek("kw", "not") and self.i + 1 < len(self.tokens) and self.tokens[self.i + 1] == ("kw", "in"):
            self.i += 2
            return ("cmp", "not in", left, self._atom())
        return left

    def _atom(self):
        if self.i >= len(self.tokens):
            raise TemplateError(f"condition {self.source!r} ends too soon")
        kind, value = self.tokens[self.i]
        if kind == "lit":
            self.i += 1
            return ("lit", value)
        if kind == "var":
            self.i += 1
            return ("var", value)
        if kind == "op" and value == "(":
            self.i += 1
            node = self._or()
            self._take("op", ")")
            return node
        if kind == "op" and value == "[":
            self.i += 1
            items = []
            if not self._peek("op", "]"):
                items.append(self._atom())
                while self._peek("op", ","):
                    self.i += 1
                    items.append(self._atom())
            self._take("op", "]")
            return ("list", items)
        raise TemplateError(f"unexpected {value!r} in condition {self.source!r}")


def _expr_vars(node, out: set[str]) -> None:
    tag = node[0]
    if tag == "var":
        out.add(node[1])
    elif tag == "list":
        for item in node[1]:
            _expr_vars(item, out)
    elif tag == "not":
        _expr_vars(node[1], out)
    elif tag in ("and", "or"):
        _expr_vars(node[1], out)
        _expr_vars(node[2], out)
    elif tag == "cmp":
        _expr_vars(node[2], out)
        _expr_vars(node[3], out)


class _Eval:
    def __init__(self, context: Mapping[str, Any]):
        self.context = context
        self.warnings: list[str] = []
        self._warned: set[str] = set()

    def _warn(self, message: str) -> None:
        if message not in self._warned:
            self._warned.add(message)
            self.warnings.append(message)

    def value(self, node):
        tag = node[0]
        if tag == "lit":
            return node[1]
        if tag == "var":
            if node[1] not in self.context:
                self._warn(f"unknown variable '{node[1]}' (treated as false)")
                return None
            return self.context[node[1]]
        if tag == "list":
            return [self.value(item) for item in node[1]]
        if tag == "not":
            return not self.truthy(node[1])
        if tag == "and":
            return self.truthy(node[1]) and self.truthy(node[2])
        if tag == "or":
            return self.truthy(node[1]) or self.truthy(node[2])
        if tag == "cmp":
            return self._compare(node[1], self.value(node[2]), self.value(node[3]))
        raise TemplateError(f"unknown expression {tag}")  # pragma: no cover

    def truthy(self, node) -> bool:
        return bool(self.value(node))

    def _compare(self, op: str, left, right) -> bool:
        if op == "==":
            return left == right
        if op == "!=":
            return left != right
        if op in ("in", "not in"):
            if isinstance(right, (list, tuple, set, frozenset)):
                found = left in right
            elif isinstance(right, str) and isinstance(left, str):
                found = left in right
            else:
                found = False
            return found if op == "in" else not found
        numeric = (int, float)
        same = (
            isinstance(left, numeric) and isinstance(right, numeric)
            and not isinstance(left, bool) and not isinstance(right, bool)
        ) or (isinstance(left, str) and isinstance(right, str))
        if not same:
            if left is not None and right is not None:
                self._warn(f"can't compare {left!r} {op} {right!r} (treated as false)")
            return False
        return {"<": left < right, "<=": left <= right, ">": left > right, ">=": left >= right}[op]


# Documents ------------------------------------------------------------------

@dataclass
class _Branch:
    expr: Any  # None for else
    body: list


@dataclass
class _Block:
    kind: str  # "if" | "unless"
    branches: list[_Branch]


_Node = Union[str, _Block]
_TAG = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)


def _classify(inner: str) -> Optional[tuple[str, str]]:
    """(tag, argument) for a block tag, or None for literal ``{{...}}`` text."""
    s = inner.strip()
    for name in ("#if", "#elif", "#unless"):
        if s == name or (s.startswith(name) and s[len(name)].isspace()):
            return name[1:], s[len(name):].strip()
    if s == "else":
        return "else", ""
    if s in ("/if", "/unless"):
        return s, ""
    return None


def _scan(source: str) -> list[tuple[str, str] | tuple[str, str, str]]:
    """Split into ("text", s) and ("tag", name, arg) tokens; standalone tags eat their line."""
    out: list = []
    pos = 0
    for m in _TAG.finditer(source):
        tag = _classify(m.group(1))
        if tag is None:
            continue
        start, end = m.start(), m.end()
        line_start = source.rfind("\n", 0, start) + 1
        line_end = source.find("\n", end)
        line_end = len(source) if line_end == -1 else line_end
        before, after = source[line_start:start], source[end:line_end]
        if before.strip() == "" and after.strip() == "" and line_start >= pos:
            start = line_start
            end = line_end + 1 if line_end < len(source) else line_end
        if start > pos:
            out.append(("text", source[pos:start]))
        out.append(("tag", tag[0], tag[1]))
        pos = end
    if pos < len(source):
        out.append(("text", source[pos:]))
    return out


def _parse(source: str) -> list[_Node]:
    root: list[_Node] = []
    stack: list[tuple[_Block, list]] = []  # (block, body of the open branch)
    current = root
    for token in _scan(source):
        if token[0] == "text":
            current.append(token[1])
            continue
        _, name, arg = token
        if name in ("if", "unless"):
            if not arg:
                raise TemplateError(f"{{{{#{name}}}}} needs a condition")
            block = _Block(name, [_Branch(_ExprParser(arg).parse(), [])])
            current.append(block)
            stack.append((block, current))
            current = block.branches[0].body
        elif name == "elif":
            if not stack or stack[-1][0].kind != "if":
                raise TemplateError("{{#elif}} without an open {{#if}}")
            block = stack[-1][0]
            if block.branches[-1].expr is None:
                raise TemplateError("{{#elif}} after {{else}}")
            if not arg:
                raise TemplateError("{{#elif}} needs a condition")
            block.branches.append(_Branch(_ExprParser(arg).parse(), []))
            current = block.branches[-1].body
        elif name == "else":
            if not stack:
                raise TemplateError("{{else}} without an open {{#if}} or {{#unless}}")
            block = stack[-1][0]
            if block.branches[-1].expr is None:
                raise TemplateError("a block has two {{else}} tags")
            block.branches.append(_Branch(None, []))
            current = block.branches[-1].body
        else:  # /if or /unless
            want = name[1:]
            if not stack:
                raise TemplateError(f"{{{{{name}}}}} without an open {{{{#{want}}}}}")
            block, parent = stack.pop()
            if block.kind != want:
                raise TemplateError(f"{{{{{name}}}}} closes a {{{{#{block.kind}}}}} block")
            current = parent
    if stack:
        raise TemplateError(f"{{{{#{stack[-1][0].kind}}}}} is never closed")
    return root


def _collect_vars(nodes: list[_Node], out: set[str]) -> None:
    for node in nodes:
        if isinstance(node, _Block):
            for branch in node.branches:
                if branch.expr is not None:
                    _expr_vars(branch.expr, out)
                _collect_vars(branch.body, out)


def _emit(nodes: list[_Node], ev: Optional[_Eval], out: list[str]) -> None:
    for node in nodes:
        if isinstance(node, str):
            out.append(node)
            continue
        if ev is None:  # strip mode: keep every branch
            for branch in node.branches:
                _emit(branch.body, None, out)
            continue
        for branch in node.branches:
            if branch.expr is None:
                _emit(branch.body, ev, out)
                break
            hit = ev.truthy(branch.expr)
            if node.kind == "unless":
                hit = not hit
            if hit:
                _emit(branch.body, ev, out)
                break


_BLANK_RUN = re.compile(r"\n[ \t]*\n(?:[ \t]*\n)+")


def _tidy(text: str) -> str:
    return _BLANK_RUN.sub("\n\n", text).strip("\n")


def render(source: str, context: Optional[Mapping[str, Any]] = None) -> RenderedTemplate:
    """Evaluate the conditionals against ``context``."""
    source = source or ""
    try:
        nodes = _parse(source)
    except TemplateError as exc:
        return RenderedTemplate(source, frozenset(), [f"instructions template problem: {exc}"], False)
    names: set[str] = set()
    _collect_vars(nodes, names)
    ev = _Eval({**{name: None for name in STANDARD_VARIABLES}, **(context or {})})
    out: list[str] = []
    _emit(nodes, ev, out)
    return RenderedTemplate(_tidy("".join(out)), frozenset(names), ev.warnings, True)


def strip_blocks(source: str) -> RenderedTemplate:
    """Every branch's text with the block tags removed, for people reading it."""
    source = source or ""
    try:
        nodes = _parse(source)
    except TemplateError as exc:
        return RenderedTemplate(source, frozenset(), [f"instructions template problem: {exc}"], False)
    names: set[str] = set()
    _collect_vars(nodes, names)
    out: list[str] = []
    _emit(nodes, None, out)
    return RenderedTemplate(_tidy("".join(out)), frozenset(names), [], True)


def check(source: str) -> Optional[str]:
    """None when the template parses, else the problem in plain words."""
    try:
        _parse(source or "")
    except TemplateError as exc:
        return str(exc)
    return None


def referenced_vars(source: str) -> frozenset[str]:
    try:
        nodes = _parse(source or "")
    except TemplateError:
        return frozenset()
    names: set[str] = set()
    _collect_vars(nodes, names)
    return frozenset(names)
