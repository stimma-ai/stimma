"""Real-SQLite coverage for explicit developer database maintenance."""

import sqlite3

import pytest

from services.database_maintenance import analyze_database, cleanup_database


def _seed_maintenance_database(path):
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        PRAGMA foreign_keys=OFF;
        CREATE TABLE parents (id INTEGER PRIMARY KEY);
        CREATE TABLE cascade_children (
            id INTEGER PRIMARY KEY,
            parent_id INTEGER REFERENCES parents(id) ON DELETE CASCADE
        );
        CREATE TABLE nullable_children (
            id INTEGER PRIMARY KEY,
            parent_id INTEGER REFERENCES parents(id) ON DELETE SET NULL
        );
        CREATE TABLE restricted_children (
            id INTEGER PRIMARY KEY,
            parent_id INTEGER REFERENCES parents(id) ON DELETE RESTRICT
        );
        CREATE TABLE composite_parents (
            left_id INTEGER,
            right_id INTEGER,
            PRIMARY KEY (left_id, right_id)
        );
        CREATE TABLE composite_children (
            id INTEGER PRIMARY KEY,
            left_id INTEGER,
            right_id INTEGER,
            FOREIGN KEY (left_id, right_id)
                REFERENCES composite_parents(left_id, right_id) ON DELETE CASCADE
        );
        CREATE TABLE assets (
            id INTEGER PRIMARY KEY,
            parent_id INTEGER REFERENCES parents(id) ON DELETE CASCADE
        );

        INSERT INTO parents VALUES (1);
        INSERT INTO cascade_children VALUES (1, 1), (2, 999), (3, 999);
        INSERT INTO nullable_children VALUES (1, 999);
        INSERT INTO restricted_children VALUES (1, 999);
        INSERT INTO composite_children VALUES (1, 999, 1000);
        INSERT INTO assets VALUES (1, 999);
        """
    )
    connection.commit()
    connection.close()


@pytest.mark.asyncio
async def test_analyze_groups_repairable_and_report_only_constraints(tmp_path):
    db_path = tmp_path / "maintenance.db"
    _seed_maintenance_database(db_path)

    analysis = await analyze_database(str(db_path))

    assert analysis["total_findings"] == 6
    assert analysis["repairable_count"] == 3
    assert analysis["report_only_count"] == 3
    groups = {group["child_table"]: group for group in analysis["groups"]}
    assert groups["cascade_children"] == {
        "child_table": "cascade_children",
        "child_columns": ["parent_id"],
        "parent_table": "parents",
        "parent_columns": ["id"],
        "on_delete": "CASCADE",
        "count": 2,
        "repairable": True,
        "repair_action": "delete_child",
        "reason": "Delete the orphaned child row (declared CASCADE)",
    }
    assert groups["nullable_children"]["repair_action"] == "set_null"
    assert groups["restricted_children"]["repairable"] is False
    assert groups["composite_children"]["reason"] == "Composite foreign keys are report only"
    assert groups["assets"]["reason"] == "Protected durable records are never deleted"


@pytest.mark.asyncio
async def test_cleanup_is_transactional_safe_and_idempotent(tmp_path):
    db_path = tmp_path / "maintenance.db"
    _seed_maintenance_database(db_path)

    result = await cleanup_database(str(db_path))

    assert result["before"]["total_findings"] == 6
    assert result["repaired_count"] == 3
    assert result["deleted_count"] == 2
    assert result["nullified_count"] == 1
    assert result["after"]["total_findings"] == 3
    assert result["after"]["repairable_count"] == 0

    connection = sqlite3.connect(db_path)
    assert connection.execute("SELECT id, parent_id FROM cascade_children ORDER BY id").fetchall() == [(1, 1)]
    assert connection.execute("SELECT parent_id FROM nullable_children").fetchone() == (None,)
    assert connection.execute("SELECT parent_id FROM restricted_children").fetchone() == (999,)
    assert connection.execute("SELECT parent_id FROM assets").fetchone() == (999,)
    connection.close()

    repeated = await cleanup_database(str(db_path))
    assert repeated["repaired_count"] == 0
    assert repeated["before"] == repeated["after"]
    assert repeated["after"]["total_findings"] == 3


@pytest.mark.asyncio
async def test_cleanup_rolls_back_all_repairs_on_failure(tmp_path):
    db_path = tmp_path / "rollback.db"
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        PRAGMA foreign_keys=OFF;
        CREATE TABLE parents (id INTEGER PRIMARY KEY);
        CREATE TABLE a_cascade (
            id INTEGER PRIMARY KEY,
            parent_id INTEGER REFERENCES parents(id) ON DELETE CASCADE
        );
        CREATE TABLE z_invalid_set_null (
            id INTEGER PRIMARY KEY,
            parent_id INTEGER NOT NULL REFERENCES parents(id) ON DELETE SET NULL
        );
        INSERT INTO a_cascade VALUES (1, 999);
        INSERT INTO z_invalid_set_null VALUES (1, 999);
        """
    )
    connection.commit()
    connection.close()

    with pytest.raises(sqlite3.IntegrityError):
        await cleanup_database(str(db_path))

    connection = sqlite3.connect(db_path)
    assert connection.execute("SELECT * FROM a_cascade").fetchall() == [(1, 999)]
    assert connection.execute("SELECT * FROM z_invalid_set_null").fetchall() == [(1, 999)]
    connection.close()
    assert (await analyze_database(str(db_path)))["total_findings"] == 2


@pytest.mark.asyncio
async def test_maintenance_endpoints_are_developer_only_and_profile_scoped(client, test_app):
    denied = await client.get("/api/settings/database/maintenance/analyze")
    assert denied.status_code == 403

    from database_registry import get_database_registry

    enabled = await client.patch("/api/settings/developer-mode", json={"enabled": True})
    assert enabled.status_code == 200
    db_path = get_database_registry().get_database("default").db_path
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        PRAGMA foreign_keys=OFF;
        CREATE TABLE maintenance_api_parents (id INTEGER PRIMARY KEY);
        CREATE TABLE maintenance_api_children (
            id INTEGER PRIMARY KEY,
            parent_id INTEGER REFERENCES maintenance_api_parents(id) ON DELETE CASCADE
        );
        INSERT INTO maintenance_api_children VALUES (1, 999);
        """
    )
    connection.commit()
    connection.close()

    analyzed = await client.get("/api/settings/database/maintenance/analyze")
    assert analyzed.status_code == 200
    assert analyzed.json()["profile_id"] == "default"
    api_group = next(group for group in analyzed.json()["groups"] if group["child_table"] == "maintenance_api_children")
    assert api_group["repairable"] is True

    unconfirmed = await client.post("/api/settings/database/maintenance/cleanup", json={"confirm": False})
    assert unconfirmed.status_code == 400
    cleaned = await client.post("/api/settings/database/maintenance/cleanup", json={"confirm": True})
    assert cleaned.status_code == 200
    assert cleaned.json()["profile_id"] == "default"
    assert cleaned.json()["repaired_count"] == 1
    assert cleaned.json()["before"]["total_findings"] == 1
    assert cleaned.json()["after"]["total_findings"] == 0
