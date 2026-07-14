"""Read-only integrity audit for the Asset/Revision/Media model."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

import yaml


CORE_ASSET_TABLES = {
    "asset_migration_map",
    "asset_migration_state",
    "asset_revisions",
    "asset_snapshots",
    "assets",
    "container_members",
    "media_items",
    "media_owners",
    "storage_objects",
    "working_documents",
}

REQUIRED_TABLES = CORE_ASSET_TABLES | {"chats", "flows", "generation_jobs"}

ASSET_MODEL_TABLES = CORE_ASSET_TABLES | {
    "asset_markers",
    "asset_tags",
    "board_asset_items",
    "managed_artifacts",
    "project_assets",
}

COUNT_CHECKS = (
    (
        "duplicate_migration_maps",
        """
        SELECT count(*) FROM (
            SELECT legacy_media_id, migration_version
            FROM asset_migration_map
            WHERE deleted_at IS NULL
            GROUP BY legacy_media_id, migration_version
            HAVING count(*) > 1
        )
        """,
        "duplicate live migration-map entries",
    ),
    (
        "applied_migration_maps_missing_media",
        """
        SELECT count(*)
        FROM asset_migration_map mm
        LEFT JOIN media_items m ON m.id = mm.legacy_media_id
        WHERE mm.deleted_at IS NULL AND mm.status = 'applied' AND m.id IS NULL
        """,
        "applied migration-map entries whose Media is missing",
    ),
    (
        "migration_maps_missing_asset",
        """
        SELECT count(*)
        FROM asset_migration_map mm
        LEFT JOIN assets a ON a.id = mm.asset_id
        WHERE mm.deleted_at IS NULL AND mm.asset_id IS NOT NULL AND a.id IS NULL
        """,
        "migration-map entries whose claimed Asset is missing",
    ),
    (
        "assets_without_valid_current_revision",
        """
        SELECT count(*)
        FROM assets a
        LEFT JOIN asset_revisions r ON r.id = a.current_revision_id
        WHERE r.id IS NULL OR r.asset_id != a.id OR r.deleted_at IS NOT NULL
        """,
        "Assets without a live current revision belonging to that Asset",
    ),
    (
        "asset_state_mismatches",
        """
        SELECT count(*) FROM assets
        WHERE (state = 'active' AND deleted_at IS NOT NULL)
           OR (state = 'trashed' AND deleted_at IS NULL)
        """,
        "Assets whose lifecycle state and deletion timestamp disagree",
    ),
    (
        "duplicate_revision_numbers",
        """
        SELECT count(*) FROM (
            SELECT asset_id, revision_number
            FROM asset_revisions
            WHERE deleted_at IS NULL
            GROUP BY asset_id, revision_number
            HAVING count(*) > 1
        )
        """,
        "duplicate live revision numbers within an Asset",
    ),
    (
        "live_revisions_missing_media",
        """
        SELECT count(*)
        FROM asset_revisions r
        LEFT JOIN media_items m ON m.id = r.primary_media_id
        WHERE r.deleted_at IS NULL AND m.id IS NULL
        """,
        "live revisions whose primary Media is missing",
    ),
    (
        "live_revisions_missing_primary_owner",
        """
        SELECT count(*)
        FROM asset_revisions r
        LEFT JOIN media_owners o
          ON o.media_id = r.primary_media_id
         AND o.root_kind = 'asset_revision'
         AND o.root_id = CAST(r.id AS TEXT)
         AND o.role = 'primary'
         AND o.deleted_at IS NULL
        WHERE r.deleted_at IS NULL AND o.id IS NULL
        """,
        "live revisions without their primary Media ownership edge",
    ),
    (
        "completed_asset_jobs_missing_asset_link",
        """
        SELECT count(*)
        FROM generation_jobs j
        WHERE j.status = 'completed'
          AND j.output_disposition = 'asset'
          AND j.result_media_id IS NOT NULL
          AND j.result_asset_id IS NULL
          AND EXISTS (
              SELECT 1 FROM asset_revisions r
              WHERE r.primary_media_id = j.result_media_id
                AND r.deleted_at IS NULL
          )
        """,
        "completed Asset-result jobs not linked to their backfilled Asset",
    ),
    (
        "duplicate_live_owner_edges",
        """
        SELECT count(*) FROM (
            SELECT media_id, root_kind, root_id, role
            FROM media_owners
            WHERE deleted_at IS NULL
            GROUP BY media_id, root_kind, root_id, role
            HAVING count(*) > 1
        )
        """,
        "duplicate live Media ownership edges",
    ),
    (
        "live_owners_missing_media",
        """
        SELECT count(*)
        FROM media_owners o
        LEFT JOIN media_items m ON m.id = o.media_id
        WHERE o.deleted_at IS NULL AND m.id IS NULL
        """,
        "live ownership edges whose Media is missing",
    ),
    (
        "asset_revision_owners_missing_root",
        """
        SELECT count(*)
        FROM media_owners o
        LEFT JOIN asset_revisions r ON CAST(r.id AS TEXT) = o.root_id
        WHERE o.deleted_at IS NULL AND o.root_kind = 'asset_revision' AND r.id IS NULL
        """,
        "Asset-revision ownership edges whose root is missing",
    ),
    (
        "container_revision_owners_missing_root",
        """
        SELECT count(*)
        FROM media_owners o
        LEFT JOIN asset_revisions r ON CAST(r.id AS TEXT) = o.root_id
        WHERE o.deleted_at IS NULL AND o.root_kind = 'container_revision' AND r.id IS NULL
        """,
        "container ownership edges whose revision root is missing",
    ),
    (
        "snapshot_owners_missing_root",
        """
        SELECT count(*)
        FROM media_owners o
        LEFT JOIN asset_snapshots s ON CAST(s.id AS TEXT) = o.root_id
        WHERE o.deleted_at IS NULL AND o.root_kind = 'asset_snapshot' AND s.id IS NULL
        """,
        "snapshot ownership edges whose snapshot root is missing",
    ),
    (
        "working_document_owners_missing_root",
        """
        SELECT count(*)
        FROM media_owners o
        LEFT JOIN working_documents w ON CAST(w.id AS TEXT) = o.root_id
        WHERE o.deleted_at IS NULL AND o.root_kind = 'working_document' AND w.id IS NULL
        """,
        "working-document ownership edges whose root is missing",
    ),
    (
        "chat_owners_missing_root",
        """
        SELECT count(*)
        FROM media_owners o
        LEFT JOIN chats c ON CAST(c.id AS TEXT) = o.root_id AND c.deleted_at IS NULL
        WHERE o.deleted_at IS NULL AND o.root_kind = 'chat' AND c.id IS NULL
        """,
        "chat ownership edges whose live Chat root is missing",
    ),
    (
        "batch_owners_missing_root",
        """
        SELECT count(*)
        FROM media_owners o
        WHERE o.deleted_at IS NULL AND o.root_kind = 'batch'
          AND NOT EXISTS (
              SELECT 1 FROM generation_jobs j WHERE j.batch_id = o.root_id
          )
        """,
        "batch ownership edges whose generation batch is missing",
    ),
    (
        "flow_owners_missing_root",
        """
        SELECT count(*)
        FROM media_owners o
        WHERE o.deleted_at IS NULL AND o.root_kind = 'flow_equation'
          AND NOT EXISTS (
              SELECT 1 FROM flows f
              WHERE f.deleted_at IS NULL
                AND o.root_id LIKE CAST(f.id AS TEXT) || ':%'
          )
        """,
        "Flow ownership edges whose live Flow root is missing",
    ),
    (
        "invalid_upload_owners",
        """
        SELECT count(*)
        FROM media_owners o
        WHERE o.deleted_at IS NULL AND o.root_kind = 'upload'
          AND o.root_id != CAST(o.media_id AS TEXT)
        """,
        "provisional upload ownership edges whose root does not match their Media",
    ),
    (
        "invalid_ephemeral_run_owners",
        """
        SELECT count(*)
        FROM media_owners o
        JOIN media_items m ON m.id = o.media_id
        WHERE o.deleted_at IS NULL AND o.root_kind = 'ephemeral_run'
          AND (m.ephemeral_run_id IS NULL OR m.ephemeral_run_id != o.root_id)
        """,
        "ephemeral-run ownership edges that disagree with their Media run",
    ),
    (
        "unknown_owner_kinds",
        """
        SELECT count(*)
        FROM media_owners
        WHERE deleted_at IS NULL
          AND root_kind NOT IN (
              'asset_revision', 'asset_snapshot', 'batch', 'chat',
              'container_revision', 'ephemeral_run', 'flow_equation',
              'upload', 'working_document'
          )
        """,
        "live Media ownership edges with an unknown root kind",
    ),
    (
        "unowned_live_media",
        """
        SELECT count(*)
        FROM media_items m
        LEFT JOIN media_owners o ON o.media_id = m.id AND o.deleted_at IS NULL
        WHERE m.deleted_at IS NULL
          AND m.deletion_pending_at IS NULL
          AND m.ephemeral_run_id IS NULL
          AND o.id IS NULL
        """,
        "live non-ephemeral Media with no owner",
    ),
    (
        "invalid_container_slots",
        """
        SELECT count(*)
        FROM container_members c
        WHERE c.deleted_at IS NULL
          AND ((c.linked_asset_id IS NOT NULL)
             + (c.embedded_media_id IS NOT NULL)
             + (COALESCE(c.missing_linked_asset, 0) = 1)) != 1
        """,
        "container slots without exactly one linked, embedded, or missing target",
    ),
    (
        "linked_container_assets_missing",
        """
        SELECT count(*)
        FROM container_members c
        LEFT JOIN assets a ON a.id = c.linked_asset_id
        WHERE c.deleted_at IS NULL AND c.linked_asset_id IS NOT NULL AND a.id IS NULL
        """,
        "linked container slots whose Asset is missing",
    ),
    (
        "embedded_container_media_missing",
        """
        SELECT count(*)
        FROM container_members c
        LEFT JOIN media_items m ON m.id = c.embedded_media_id
        WHERE c.deleted_at IS NULL AND c.embedded_media_id IS NOT NULL AND m.id IS NULL
        """,
        "embedded container slots whose Media is missing",
    ),
    (
        "embedded_slots_missing_owner",
        """
        SELECT count(*)
        FROM container_members c
        LEFT JOIN media_owners o
          ON o.media_id = c.embedded_media_id
         AND o.root_kind = 'container_revision'
         AND o.root_id = CAST(c.container_revision_id AS TEXT)
         AND o.deleted_at IS NULL
        WHERE c.deleted_at IS NULL AND c.embedded_media_id IS NOT NULL AND o.id IS NULL
        """,
        "embedded container slots without their Media ownership edge",
    ),
    (
        "snapshots_missing_owner",
        """
        SELECT count(*)
        FROM asset_snapshots s
        LEFT JOIN media_owners o
          ON o.media_id = s.media_id
         AND o.root_kind = 'asset_snapshot'
         AND o.root_id = CAST(s.id AS TEXT)
         AND o.deleted_at IS NULL
        WHERE s.deleted_at IS NULL AND o.id IS NULL
        """,
        "live snapshots without their Media ownership edge",
    ),
    (
        "media_with_dangling_storage_object",
        """
        SELECT count(*)
        FROM media_items m
        LEFT JOIN storage_objects s ON s.id = m.storage_object_id
        WHERE m.storage_object_id IS NOT NULL AND (s.id IS NULL OR s.deleted_at IS NOT NULL)
        """,
        "Media referencing a missing or deleted StorageObject",
    ),
    (
        "orphan_live_storage_objects",
        """
        SELECT count(*)
        FROM storage_objects s
        LEFT JOIN media_items m ON m.storage_object_id = s.id
        WHERE s.deleted_at IS NULL AND m.id IS NULL
        """,
        "live StorageObjects that no Media references",
    ),
)


class DoctorUsageError(ValueError):
    """The selected sandbox cannot be audited as requested."""


def _finding(code: str, count: int, message: str) -> dict[str, Any]:
    return {"code": code, "count": count, "message": message}


def _scalar(connection: sqlite3.Connection, sql: str) -> int:
    row = connection.execute(sql).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_payload(path: Path) -> str:
    if path.is_file():
        return _hash_file(path)
    if not path.is_dir():
        raise FileNotFoundError(path)
    digest = hashlib.sha256(b"stimma-directory-v1\0")
    candidates = list(path.rglob("*"))
    if any(candidate.is_symlink() for candidate in candidates):
        raise ValueError("managed directory contains a symlink")
    files = sorted(
        (candidate for candidate in candidates if candidate.is_file()),
        key=lambda candidate: candidate.relative_to(path).as_posix(),
    )
    for candidate in files:
        relative = candidate.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with candidate.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _is_asset_foreign_key_violation(table: str, parent: str) -> bool:
    if table in ASSET_MODEL_TABLES:
        return True
    # Many historical tables point at Media. They are legacy debris when the
    # missing parent is Media; new-model child tables are covered above.
    if parent in ASSET_MODEL_TABLES - {"media_items"}:
        return True
    return table == "media_items" and parent == "storage_objects"


def _audit_payloads(
    connection: sqlite3.Connection,
    *,
    profile_dir: Path,
    verify_hashes: bool,
) -> tuple[dict[str, int | bool], list[dict[str, Any]], list[dict[str, Any]]]:
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    object_root = profile_dir / "objects"
    storage_rows = list(connection.execute("""
        SELECT id, kind, object_key, external_path, expected_hash, state
        FROM storage_objects
        WHERE deleted_at IS NULL
    """))

    missing_managed = 0
    corrupt_managed = 0
    unsafe_managed_keys = 0
    managed_count = 0
    external_storage_count = 0
    resolved_root = object_root.resolve()
    for _, kind, object_key, external_path, expected_hash, _ in storage_rows:
        if kind == "managed":
            managed_count += 1
            locator = object_root / (object_key or "")
            try:
                locator.resolve().relative_to(resolved_root)
            except ValueError:
                unsafe_managed_keys += 1
                continue
            if not locator.is_file() and not locator.is_dir():
                missing_managed += 1
            elif verify_hashes:
                try:
                    if _hash_payload(locator) != expected_hash:
                        corrupt_managed += 1
                except (OSError, ValueError):
                    corrupt_managed += 1
        elif kind == "external":
            external_storage_count += 1

    if unsafe_managed_keys:
        failures.append(_finding(
            "unsafe_managed_object_keys",
            unsafe_managed_keys,
            "managed StorageObjects whose keys escape the profile object store",
        ))
    if missing_managed:
        failures.append(_finding(
            "missing_managed_payloads",
            missing_managed,
            "managed payloads missing from disk",
        ))
    if corrupt_managed:
        failures.append(_finding(
            "corrupt_managed_payloads",
            corrupt_managed,
            "managed payloads whose content hash does not match",
        ))

    missing_external = 0
    missing_external_flagged = 0
    live_payloads = 0
    media_rows = connection.execute("""
        SELECT m.file_path, COALESCE(m.file_unavailable, 0),
               s.kind, s.external_path
        FROM media_items m
        LEFT JOIN storage_objects s ON s.id = m.storage_object_id
        WHERE m.deleted_at IS NULL AND m.deletion_pending_at IS NULL
    """)
    for file_path, unavailable, storage_kind, external_path in media_rows:
        live_payloads += 1
        if storage_kind == "managed":
            continue
        locator_value = external_path if storage_kind == "external" else file_path
        locator = Path(locator_value) if locator_value else None
        if locator is None or (not locator.is_file() and not locator.is_dir()):
            missing_external += 1
            if unavailable:
                missing_external_flagged += 1

    if missing_external:
        warnings.append(_finding(
            "missing_external_payloads",
            missing_external,
            (
                "external or legacy payloads missing from disk "
                f"({missing_external_flagged} already marked unavailable)"
            ),
        ))

    return (
        {
            "live_payloads": live_payloads,
            "managed_objects": managed_count,
            "external_storage_objects": external_storage_count,
            "missing_external": missing_external,
            "missing_external_flagged": missing_external_flagged,
            "hashes_verified": verify_hashes,
        },
        failures,
        warnings,
    )


def audit_profile(
    data_dir: Path,
    *,
    profile_id: str,
    profile_name: str,
    verify_hashes: bool = False,
) -> dict[str, Any]:
    """Audit one profile without opening a writable database connection."""
    profile_dir = data_dir / profile_id
    database_path = profile_dir / "stimma_v1.db"
    report: dict[str, Any] = {
        "profile_id": profile_id,
        "profile_name": profile_name,
        "counts": {},
        "migration_phase": None,
        "checks": {},
        "foreign_keys": {"asset_model": 0, "legacy": 0, "legacy_groups": {}},
        "payloads": {},
        "failures": [],
        "warnings": [],
    }
    failures: list[dict[str, Any]] = report["failures"]
    warnings: list[dict[str, Any]] = report["warnings"]

    if not database_path.is_file():
        failures.append(_finding(
            "database_missing", 1, "profile database does not exist"
        ))
        report["ok"] = False
        return report

    connection = sqlite3.connect(
        f"file:{database_path}?mode=ro",
        uri=True,
        timeout=30,
    )
    try:
        connection.execute("PRAGMA query_only=ON")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        missing_tables = sorted(REQUIRED_TABLES - tables)
        if missing_tables:
            failures.append(_finding(
                "asset_schema_missing",
                len(missing_tables),
                "required Asset/Media tables are missing: " + ", ".join(missing_tables),
            ))
            report["ok"] = False
            return report

        integrity_rows = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        if integrity_rows != ["ok"]:
            failures.append(_finding(
                "sqlite_integrity",
                len(integrity_rows),
                "SQLite integrity_check reported errors",
            ))

        for table in (
            "media_items",
            "assets",
            "asset_revisions",
            "media_owners",
            "container_members",
            "asset_snapshots",
            "working_documents",
            "storage_objects",
            "asset_migration_map",
        ):
            report["counts"][table] = _scalar(
                connection, f'SELECT count(*) FROM "{table}"'
            )

        migration = connection.execute("""
            SELECT phase
            FROM asset_migration_state
            WHERE migration_key = 'asset_media_v1' AND deleted_at IS NULL
        """).fetchone()
        report["migration_phase"] = migration[0] if migration else None
        if report["migration_phase"] != "contracted":
            failures.append(_finding(
                "asset_migration_incomplete",
                1,
                "Asset/Media migration is not in the contracted phase",
            ))

        for code, sql, message in COUNT_CHECKS:
            value = _scalar(connection, sql)
            report["checks"][code] = value
            if value:
                failures.append(_finding(code, value, message))

        asset_fk_violations = 0
        legacy_fk_groups: Counter[tuple[str, str]] = Counter()
        for table, _, parent, _ in connection.execute("PRAGMA foreign_key_check"):
            if _is_asset_foreign_key_violation(table, parent):
                asset_fk_violations += 1
            else:
                legacy_fk_groups[(table, parent)] += 1
        legacy_fk_violations = sum(legacy_fk_groups.values())
        report["foreign_keys"] = {
            "asset_model": asset_fk_violations,
            "legacy": legacy_fk_violations,
            "legacy_groups": {
                f"{table}->{parent}": count
                for (table, parent), count in legacy_fk_groups.most_common()
            },
        }
        if asset_fk_violations:
            failures.append(_finding(
                "asset_foreign_key_violations",
                asset_fk_violations,
                "foreign-key violations involving the Asset/Media model",
            ))
        if legacy_fk_violations:
            warnings.append(_finding(
                "legacy_foreign_key_debris",
                legacy_fk_violations,
                "foreign-key violations confined to legacy tables",
            ))

        payloads, payload_failures, payload_warnings = _audit_payloads(
            connection,
            profile_dir=profile_dir,
            verify_hashes=verify_hashes,
        )
        report["payloads"] = payloads
        failures.extend(payload_failures)
        warnings.extend(payload_warnings)
    except sqlite3.Error as exc:
        failures.append(_finding(
            "database_read_error",
            1,
            f"database audit failed: {type(exc).__name__}",
        ))
    finally:
        connection.close()

    report["ok"] = not failures
    return report


def audit_assets(
    data_dir: Path,
    *,
    verify_hashes: bool = False,
    profile_id: str | None = None,
) -> dict[str, Any]:
    """Audit configured profiles and return a JSON-serializable report."""
    config_path = data_dir / "config.yaml"
    if not config_path.is_file():
        raise DoctorUsageError("config.yaml does not exist in the selected sandbox")
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise DoctorUsageError(
            f"config.yaml could not be read: {type(exc).__name__}"
        ) from exc
    configured_profiles = config.get("profiles") or []
    if not isinstance(configured_profiles, list) or not configured_profiles:
        raise DoctorUsageError("the selected sandbox has no configured profiles")

    selected = []
    for profile in configured_profiles:
        if not isinstance(profile, dict) or not profile.get("id"):
            continue
        if profile_id is None or profile["id"] == profile_id:
            selected.append(profile)
    if profile_id is not None and not selected:
        raise DoctorUsageError(f"profile not found: {profile_id}")
    if not selected:
        raise DoctorUsageError("the selected sandbox has no valid profiles")

    profiles = [
        audit_profile(
            data_dir,
            profile_id=profile["id"],
            profile_name=profile.get("name") or profile["id"],
            verify_hashes=verify_hashes,
        )
        for profile in selected
    ]
    failure_count = sum(len(profile["failures"]) for profile in profiles)
    warning_count = sum(len(profile["warnings"]) for profile in profiles)
    return {
        "ok": failure_count == 0,
        "verify_hashes": verify_hashes,
        "failure_count": failure_count,
        "warning_count": warning_count,
        "profiles": profiles,
    }


def render_report(report: dict[str, Any]) -> str:
    """Render a compact human-readable doctor report."""
    lines = ["Asset doctor (read-only)"]
    for profile in report["profiles"]:
        status = "PASS" if profile["ok"] else "FAIL"
        counts = profile["counts"]
        lines.append(
            f"\n{status}  {profile['profile_name']} [{profile['profile_id']}]"
        )
        if counts:
            lines.append(
                "  "
                f"{counts.get('media_items', 0):,} Media · "
                f"{counts.get('assets', 0):,} Assets · "
                f"{counts.get('asset_revisions', 0):,} revisions · "
                f"migration {profile['migration_phase'] or 'missing'}"
            )
            payloads = profile["payloads"]
            if payloads:
                hash_note = (
                    "hashes verified"
                    if payloads["hashes_verified"]
                    else "hashes not checked"
                )
                lines.append(
                    "  "
                    f"{payloads['managed_objects']:,} managed objects "
                    f"({hash_note}) · {payloads['missing_external']:,} missing external"
                )
        for finding in profile["failures"]:
            lines.append(
                f"  ERROR {finding['code']}: {finding['count']:,} — {finding['message']}"
            )
        for finding in profile["warnings"]:
            lines.append(
                f"  WARN  {finding['code']}: {finding['count']:,} — {finding['message']}"
            )
            if finding["code"] == "legacy_foreign_key_debris":
                groups = profile["foreign_keys"]["legacy_groups"]
                summary = ", ".join(
                    f"{name} {count:,}"
                    for name, count in list(groups.items())[:5]
                )
                if summary:
                    lines.append(f"        {summary}")

    result = "PASS" if report["ok"] else "FAIL"
    lines.append(
        f"\n{result}: {report['failure_count']} failure categories, "
        f"{report['warning_count']} warning categories"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--profile")
    parser.add_argument("--verify-hashes", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if not args.json:
        print(
            "Asset doctor: running read-only checks "
            "(large profiles may take a minute)...",
            flush=True,
        )
    try:
        report = audit_assets(
            args.data_dir,
            verify_hashes=args.verify_hashes,
            profile_id=args.profile,
        )
    except DoctorUsageError as exc:
        parser.error(str(exc))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_report(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
