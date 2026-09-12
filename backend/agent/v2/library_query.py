"""Shared, SQL-backed metadata matching for the agent library surfaces.

Filters describe the current payload's recorded generation, never an inferred
model or an ancestor's settings. Lineage traversal composes those searches.
"""

from sqlalchemy import case, func, select, union_all, true, or_, and_, not_

from database import MediaItem


TEXT_FIELDS = {
    "query",
    "prompt_query",
    "caption_query",
    "negative_prompt_query",
    "keyword_query",
    "filenames",
    "models",
    "loras",
    "task_types",
    "direct_tools",
}
METADATA_FACETS = {"models", "loras", "task_types", "direct_tools"}


def metadata_json():
    return case(
        (func.json_valid(MediaItem.generation_metadata), MediaItem.generation_metadata),
        else_="{}",
    )


def field_columns(field):
    meta = metadata_json()
    prompt = [
        MediaItem.extracted_prompt,
        func.json_extract(meta, "$.prompt"),
        func.json_extract(meta, "$.prompt_metadata.original_prompt"),
    ]
    return {
        "query": [*prompt, MediaItem.vlm_caption, MediaItem.keywords],
        "prompt_query": prompt,
        "caption_query": [MediaItem.vlm_caption],
        "negative_prompt_query": [
            func.json_extract(meta, "$.negative_prompt"),
            func.json_extract(meta, "$.parameters.negative_prompt"),
        ],
        "keyword_query": [MediaItem.keywords],
        "filenames": [MediaItem.file_path],
        "models": [
            func.json_extract(meta, path)
            for path in (
                "$.model",
                "$.parameters.model",
                "$.parameters.checkpoint",
                "$.parameters.ckpt_name",
            )
        ],
        "task_types": [func.json_extract(meta, "$.task_type")],
        "direct_tools": [MediaItem.tool_id, func.json_extract(meta, "$.tool_id")],
    }.get(field, [])


def lora_values():
    for path in ("$.parameters.loras", "$.loras"):
        entries = func.json_each(metadata_json(), path).table_valued(
            "value", "type", joins_implicitly=True
        )
        obj = case((entries.c.type == "object", entries.c.value), else_="{}")
        value = case(
            (entries.c.type == "text", entries.c.value),
            else_=func.coalesce(
                func.json_extract(obj, "$.path"),
                func.json_extract(obj, "$.lora"),
                func.json_extract(obj, "$.name"),
            ),
        )
        yield entries, value


def normalize_match(value, field):
    if isinstance(value, str):
        value = {"include": [value]}
    elif isinstance(value, list):
        value = {"include": value}
    if not isinstance(value, dict):
        raise ValueError(
            f"{field}: use a string, list, or {{include, exclude, match, mode}} object"
        )
    unknown = set(value) - {"include", "exclude", "match", "mode"}
    if unknown:
        raise ValueError(f"{field}: unknown keys {sorted(unknown)}")
    result = {"match": value.get("match", "contains"), "mode": value.get("mode", "any")}
    if result["match"] not in {"exact", "contains", "glob"}:
        raise ValueError(f"{field}.match must be exact, contains, or glob")
    if result["mode"] not in {"any", "all"}:
        raise ValueError(f"{field}.mode must be any or all")
    for key in ("include", "exclude"):
        terms = value.get(key, [])
        if isinstance(terms, str):
            terms = [terms]
        if not isinstance(terms, list) or any(
            not isinstance(t, str) or not t.strip() for t in terms
        ):
            raise ValueError(f"{field}.{key} must contain nonempty strings")
        result[key] = list(dict.fromkeys(terms))
    if not result["include"] and not result["exclude"]:
        raise ValueError(f"{field}: supply include or exclude")
    return result


def text_match(column, term, match="contains", basename=False):
    # Escape SQL wildcards even in glob mode; only * and ? are glob operators.
    if basename:
        term = term.replace("\\", "/")
    pattern = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    if match == "glob":
        pattern = pattern.replace("*", "%").replace("?", "_")
    elif match == "contains":
        pattern = f"%{pattern}%"
    column = func.coalesce(column, "")
    if basename:
        column = func.replace(column, "\\", "/")
    clauses = [column.ilike(pattern, escape="\\")]
    if basename and "/" not in term and match != "contains":
        clauses.append(column.ilike("%/" + pattern, escape="\\"))
    return and_(column != "", or_(*clauses))


def field_match(field, spec):
    def one(term):
        if field == "loras":
            return or_(
                *[
                    select(1)
                    .select_from(entries)
                    .where(text_match(value, term, spec["match"], True))
                    .correlate(MediaItem)
                    .exists()
                    for entries, value in lora_values()
                ]
            )
        return or_(
            *[
                text_match(col, term, spec["match"], field in {"models", "filenames"})
                for col in field_columns(field)
            ]
        )

    clauses = []
    if spec["include"]:
        combine = and_ if spec["mode"] == "all" else or_
        clauses.append(combine(*[one(term) for term in spec["include"]]))
    clauses.extend(not_(one(term)) for term in spec["exclude"])
    return and_(*clauses)


def metadata_values(field, media_ids):
    """Distinct recorded values with media IDs, for accurate facet counts."""
    if field == "loras":
        statements = [
            select(MediaItem.id.label("media_id"), value.label("value"))
            .select_from(MediaItem)
            .join(entries, true())
            .where(MediaItem.id.in_(media_ids))
            for entries, value in lora_values()
        ]
    else:
        statements = [
            select(MediaItem.id.label("media_id"), col.label("value")).where(
                MediaItem.id.in_(media_ids)
            )
            for col in field_columns(field)
        ]
    return union_all(*statements).subquery()
