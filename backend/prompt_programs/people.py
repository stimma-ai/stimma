"""person(): the writer names a person and where they stand; the engine describes them.

    woman = person("woman", noun="woman", presentation="feminine")
    emit("A portrait of", woman, ", in her kitchen.")

A writer left to choose which of a person's details to draw draws some of them, some of the
time. So it doesn't choose: `person()` is rewritten, before anything else reads the program,
into one bound pick per detail (age, descent, skin, hair, eyes, face, build) and the
description that joins them, placed wherever the program used the person. Everything after
this sees ordinary picks (`woman.age`, `woman.face`): context, pins, the picker and the judge
work as they do for picks the writer wrote, and what the user said of the person ("an old
fisherman", "a red-haired girl") narrows those picks the way it narrows any bound pick: the
user's words are read for each detail after the program is written (narrow.py). The writer
passes no narrowing words of its own, so it has none to invent.

- `noun`: what the person is, in the user's word ("woman", "fisherman", "friend"), or the
  pick of their list (`noun=job`).
- `presentation`: "feminine" or "masculine" when the user's words say which; it lets the
  face and facial hair fit.
- `said`: details the user gave as one value, with their words for it ({"descent": "Irish",
  "eyes": "emerald"}): that detail's pick gets said= their words, so every image draws their
  value and the picker offers the rest of the list (said.py).
- `leave`: details the user gave in words no list holds, which the program keeps as fixed text.
- `detail`: "full" or "brief". A person made in a loop (one of several) is brief unless said
  otherwise: several full descriptions bury the scene.

Nothing is drawn twice. A pick the program writes itself on a list person() draws from (its
own `woman.hair_color`, or with one person any pick on the hair color list) keeps its place
in the program's text, person() leaves that detail to it, and a pick the writer added is given
the person's id (`hair` → `woman.hair_color`) so it is drawn as that person's, to fit their
descent and age. A
person the program never puts in an `emit()` is emitted where they were made, so a person is
never drawn and then left out of the prompt.
"""

from __future__ import annotations

import ast
from typing import Any, Dict, List, Optional, Set, Tuple

# detail name -> (list, label, what it is of the person, a seed, phase)
DETAILS: Dict[str, Tuple[str, str, str, str, int]] = {
    "build": ("person.build", "Build", "build", "slender", 2),
    "age": ("person.age_band", "Age", "age", "30–34-year-old", 1),
    "descent": ("person.ethnicity", "Ethnicity", "descent", "Korean", 1),
    "skin": ("person.skin_tone", "Skin", "skin tone", "warm beige", 2),
    "hair": ("person.hair_length_texture", "Hair", "hair length and texture", "shoulder-length wavy", 2),
    "hair_color": ("person.hair_color", "Hair color", "hair color", "dark brown", 2),
    "eyes": ("person.eye_color", "Eyes", "eye color", "hazel", 2),
    "facial_hair": ("person.facial_hair", "Facial hair", "facial hair", "light stubble", 2),
    "face": ("person.face", "Face", "face", "a long, narrow nose, a light scatter of freckles across the nose", 2),
}
ALIASES = {"ethnicity": "descent", "age_band": "age", "skin_tone": "skin", "hair_colour": "hair_color", "eye_color": "eyes",
           "eye_colour": "eyes", "hair_length": "hair", "hair_texture": "hair", "beard": "facial_hair", "body": "build"}
BRIEF = ("age", "descent", "hair", "hair_color", "face")
_BY_LIST = {cls: key for key, (cls, *_rest) in DETAILS.items()}


def _name(key: Any) -> Optional[str]:
    key = str(key).strip().lower().replace(" ", "_")
    key = ALIASES.get(key, key)
    return key if key in DETAILS else None


def _const(node: Optional[ast.expr]) -> Any:
    try:
        return ast.literal_eval(node) if node is not None else None
    except (ValueError, SyntaxError):
        return None


def _id_text(node: Optional[ast.expr]) -> str:
    """An id as written, constant or f-string, for comparing whose pick is whose."""
    if node is None:
        return ""
    if isinstance(node, ast.JoinedStr):
        return "".join(str(v.value) if isinstance(v, ast.Constant) else "{" + ast.unparse(v.value) + "}"
                       for v in node.values if isinstance(v, (ast.Constant, ast.FormattedValue)))
    got = _const(node)
    return got if isinstance(got, str) else ""


def _suffixed(id_node: ast.expr, suffix: str) -> ast.expr:
    """The person's id with a detail's name after it: "woman" → "woman.age", and an f-string
    id in a loop (f"friends[{i+1}]") keeps its expression."""
    if isinstance(id_node, ast.JoinedStr):
        return ast.JoinedStr(values=[*id_node.values, ast.Constant(value=suffix)])
    return ast.Constant(value=str(_const(id_node) or "person") + suffix)


def _formatted(node: ast.AST) -> List[ast.Name]:
    """The plain names an f-string formats: f"A portrait of {woman}" → [woman]."""
    if not isinstance(node, ast.JoinedStr):
        return []
    return [v.value for v in node.values if isinstance(v, ast.FormattedValue) and isinstance(v.value, ast.Name)]


def _is_person(node: ast.AST) -> bool:
    return (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and getattr(node.value.func, "id", None) == "person"
            and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name))


class _People(ast.NodeTransformer):
    def __init__(self, tree: ast.Module) -> None:
        self.people: Dict[str, Tuple[str, List[ast.expr]]] = {}   # variable -> (noun, the parts that describe them)
        self.loops = 0
        made = [n for n in ast.walk(tree) if _is_person(n)]
        self.count = len(made)
        names = {n.targets[0].id for n in made}
        # The people the program places itself, and the listed details it binds picks of its own to.
        # (as an argument of emit(), or inside an f-string that is one)
        self.placed: Set[str] = {x.id for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "emit"
                                 for a in n.args for x in ([a] if isinstance(a, ast.Name) else _formatted(a)) if x.id in names}
        # The program's own picks on the lists person() draws from, and whose they are: a pick
        # whose id starts with a person's, or with one person any pick with a plain id.
        ids = [(n.value.args[0] if n.value.args else None) for n in made]
        texts = [_id_text(i) or n.targets[0].id for i, n in zip(ids, made)]
        self.kept: List[Tuple[str, str]] = []                     # (pick id as written, detail)
        self.adopt: Dict[int, ast.expr] = {}                      # id(pick call) -> the id it takes
        taken: Set[Tuple[int, str]] = set()
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Call) and getattr(n.func, "id", None) == "pick" and n.args):
                continue
            kw = {k.arg: k.value for k in n.keywords if k.arg}
            cls, pid = _const(kw.get("cls")), _id_text(n.args[0])
            owner = next((i for i, t in enumerate(texts) if pid.startswith(t + ".")), 0 if self.count == 1 and "." not in pid else None)
            if cls not in _BY_LIST or owner is None:
                continue
            self.kept.append((pid, _BY_LIST[cls]))
            # The writer's own addition under a plain id: it becomes the person's pick of that detail.
            plain = "." not in pid and isinstance(n.args[0], ast.Constant) and isinstance(ids[owner], (ast.Constant, type(None)))
            if plain and _const(kw.get("added")) is True and (owner, _BY_LIST[cls]) not in taken:
                taken.add((owner, _BY_LIST[cls]))
                self.adopt[id(n)] = ast.Constant(texts[owner] + "." + _BY_LIST[cls])

    def _theirs(self, person_id: str) -> Set[str]:
        """The details the program's own picks draw for this person: left to those picks."""
        return {detail for pid, detail in self.kept if pid.startswith(person_id + ".") or (self.count == 1 and "." not in pid)}

    # ---- person(...) assignments become the picks
    def _expand(self, target: str, call: ast.Call) -> List[ast.stmt]:
        kw = {k.arg: k.value for k in call.keywords if k.arg}
        id_node = call.args[0] if call.args else kw.get("id") or ast.Constant(value=target)
        # The noun is the user's word, or their list's pick (`noun=job` for "a {chef|firefighter}").
        said = kw.get("noun")
        noun = str(_const(said) or (_const(id_node) if said is None else "") or "person")
        noun_part: ast.expr = said if said is not None and _const(said) is None else ast.Constant(noun)
        presentation = str(_const(kw.get("presentation")) or "").lower()
        left = _const(kw.get("leave"))
        leave = {n for k in (left if isinstance(left, (list, tuple, set)) else [left] if left else []) if (n := _name(k))}
        leave |= self._theirs(_id_text(id_node))
        stated = _const(kw.get("said"))
        said = {n: v.strip() for k, v in (stated.items() if isinstance(stated, dict) else ())
                if (n := _name(k)) and isinstance(v, str) and v.strip()}
        detail = str(_const(kw.get("detail")) or ("brief" if self.loops else "full")).lower()
        keys = [k for k in DETAILS if k not in leave and (detail != "brief" or k in BRIEF or k in said)
                and (k != "facial_hair" or presentation == "masculine" or k in said)]
        out: List[ast.stmt] = []
        var = {k: f"{target}_{k}" for k in keys}
        for k in keys:
            cls, label, what, seed, phase = DETAILS[k]
            kws = [ast.keyword("cls", ast.Constant(cls)), ast.keyword("about", ast.Constant(f"the {noun}'s {what}")),
                   ast.keyword("seed", ast.List(elts=[ast.Constant(seed)], ctx=ast.Load())),
                   ast.keyword("label", ast.Constant(label)), ast.keyword("phase", ast.Constant(phase)),
                   ast.keyword("said", ast.Constant(said[k])) if k in said else ast.keyword("added", ast.Constant(True))]
            if k in ("face", "build") and presentation in ("feminine", "masculine"):   # the lists with features of one sex
                kws.insert(1, ast.keyword("where", ast.parse(repr({"presentation": presentation}), mode="eval").body))
            pick = ast.Call(func=ast.Name("pick", ast.Load()), args=[_suffixed(id_node, "." + k)], keywords=kws)
            out.append(ast.Assign(targets=[ast.Name(var[k], ast.Store())], value=pick, lineno=call.lineno))

        def name(k: str) -> ast.expr:
            return ast.Name(var[k], ast.Load())
        # "a slender 30–34-year-old Korean woman with warm beige skin, shoulder-length wavy dark brown hair, hazel eyes, ..."
        parts: List[ast.expr] = [ast.Constant("a")] + [name(k) for k in ("build", "age", "descent") if k in var] + [noun_part]
        groups = [g for g in ([name("skin"), ast.Constant("skin")] if "skin" in var else [],
                              [*(name(k) for k in ("hair", "hair_color") if k in var), ast.Constant("hair")]
                              if "hair" in var or "hair_color" in var else [],
                              [name("eyes"), ast.Constant("eyes")] if "eyes" in var else [],
                              [name("facial_hair")] if "facial_hair" in var else [],
                              [name("face")] if "face" in var else []) if g]
        for i, g in enumerate(groups):
            parts += [ast.Constant("with" if i == 0 else ",")] + g
        self.people[target] = (noun, parts)
        if target not in self.placed:   # never put in an emit(): they stand where they were made
            out.append(ast.Expr(ast.Call(func=ast.Name("emit", ast.Load()), args=[*parts, ast.Constant(";")], keywords=[])))
        return out

    def visit_Assign(self, node: ast.Assign) -> Any:
        if _is_person(node):
            return self._expand(node.targets[0].id, node.value)
        return self.generic_visit(node)

    def visit_For(self, node: ast.For) -> Any:
        self.loops += 1
        try:
            node = self.generic_visit(node)
        finally:
            self.loops -= 1
        node.body = node.body or [ast.Pass()]
        return node

    def visit_If(self, node: ast.If) -> Any:
        node = self.generic_visit(node)
        node.body = node.body or [ast.Pass()]
        return node

    # ---- the person, where the program uses them
    def visit_Call(self, node: ast.Call) -> Any:
        if getattr(node.func, "id", None) == "emit":
            args: List[ast.expr] = []
            for a in node.args:
                if isinstance(a, ast.Name) and a.id in self.people:
                    args += self.people[a.id][1]
                elif any(x.id in self.people for x in _formatted(a)):
                    # emit(f"A portrait of {woman} in her kitchen."): the text around her, and her description between
                    # Split only at the person: the rest of the f-string stays one string, as written.
                    run: List[ast.expr] = []
                    for v in [*a.values, None]:
                        here = isinstance(v, ast.FormattedValue) and isinstance(v.value, ast.Name) and v.value.id in self.people
                        if (v is None or here) and run:
                            args.append(run[0] if len(run) == 1 and isinstance(run[0], ast.Constant) else ast.JoinedStr(values=run))
                            run = []
                        if here:
                            args += self.people[v.value.id][1]
                        elif v is not None:
                            run.append(self.visit(v))
                else:
                    args.append(self.visit(a))
            node.args = args
            return node
        if id(node) in self.adopt:
            node.args[0] = self.adopt[id(node)]
        return self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> Any:
        # Anywhere else (about=f"what {woman} wears") the person is their noun.
        if isinstance(node.ctx, ast.Load) and node.id in self.people:
            return ast.Constant(self.people[node.id][0])
        return node


def expand_people(source: str) -> str:
    """The program with each person() written out as its picks and description. A program
    without one, or one that doesn't parse, is returned as written."""
    if "person(" not in source:
        return source
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source
    people = _People(tree)
    if not people.count:
        return source
    tree = people.visit(tree)
    return ast.unparse(ast.fix_missing_locations(tree)) + "\n"


__all__ = ["DETAILS", "expand_people"]
