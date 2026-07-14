"""
Tests for project-membership filtering in the browse/media views.

Covers the filter dimension added for "scope media by project":
- has_project=true  -> media that belongs to at least one (non-deleted) project
- has_project=false -> media in no project (the "library only" case)
- project_ids       -> media in at least one of the given projects (OR)
- excluded_project_ids -> media in none of the given projects
- combination of has_project + excluded_project_ids ("in a project, just not these")
- soft-deleted projects release their media back to "not in any project"
- filter-counts projects facet + in-any/not-in-any membership totals
"""

import uuid
from datetime import datetime
from pathlib import Path

import pytest
from httpx import AsyncClient

from asset_service import create_asset_from_media
from database import Project, ProjectAsset
from tests.helpers.media import create_media_item


@pytest.fixture
async def project_media(db_session):
    """Media split across two live projects, a soft-deleted project, and the library.

    All items live under a unique folder prefix so tests can scope queries to just
    these rows (the test DB is shared across modules).
    """
    prefix = str(uuid.uuid4())[:8]
    folder = f"/projtest/{prefix}"

    async with db_session() as session:
        proj_a = Project(name="Project A")
        proj_b = Project(name="Project B")
        proj_deleted = Project(name="Deleted Project", deleted_at=datetime.utcnow())
        session.add_all([proj_a, proj_b, proj_deleted])
        await session.commit()
        for p in (proj_a, proj_b, proj_deleted):
            await session.refresh(p)

        item_a = await create_media_item(session, file_path=Path(f"{folder}/a.png"))
        item_b = await create_media_item(session, file_path=Path(f"{folder}/b.png"))
        item_ab = await create_media_item(session, file_path=Path(f"{folder}/ab.png"))
        item_orphan = await create_media_item(session, file_path=Path(f"{folder}/orphan.png"))
        item_deleted = await create_media_item(session, file_path=Path(f"{folder}/deleted.png"))

        assets = {
            item.id: await create_asset_from_media(session, media_id=item.id)
            for item in (item_a, item_b, item_ab, item_orphan, item_deleted)
        }

        session.add_all([
            ProjectAsset(project_id=proj_a.id, asset_id=assets[item_a.id].id),
            ProjectAsset(project_id=proj_b.id, asset_id=assets[item_b.id].id),
            ProjectAsset(project_id=proj_a.id, asset_id=assets[item_ab.id].id),
            ProjectAsset(project_id=proj_b.id, asset_id=assets[item_ab.id].id),
            ProjectAsset(project_id=proj_deleted.id, asset_id=assets[item_deleted.id].id),
        ])
        await session.commit()

        yield {
            "folder": folder,
            "proj_a": proj_a.id,
            "proj_b": proj_b.id,
            "proj_deleted": proj_deleted.id,
            "item_a": item_a.id,
            "item_b": item_b.id,
            "item_ab": item_ab.id,
            "item_orphan": item_orphan.id,
            "item_deleted": item_deleted.id,
        }


async def _ids(client: AsyncClient, folder: str, **params) -> set:
    """Return the set of media IDs matching the given filter, scoped to our folder."""
    params["folders"] = folder
    params["page_size"] = 200
    response = await client.get("/api/media", params=params)
    assert response.status_code == 200, response.text
    return {item["id"] for item in response.json()["items"]}


class TestProjectMembershipExistence:
    async def test_in_any_project(self, client: AsyncClient, project_media):
        """has_project=true returns media in at least one live project."""
        ids = await _ids(client, project_media["folder"], has_project="true")
        assert ids == {project_media["item_a"], project_media["item_b"], project_media["item_ab"]}

    async def test_not_in_any_project(self, client: AsyncClient, project_media):
        """has_project=false returns the library-only media (incl. media of deleted projects)."""
        ids = await _ids(client, project_media["folder"], has_project="false")
        assert ids == {project_media["item_orphan"], project_media["item_deleted"]}

    async def test_no_constraint_returns_everything(self, client: AsyncClient, project_media):
        """Without the filter, all of our items are returned regardless of membership."""
        ids = await _ids(client, project_media["folder"])
        assert ids == {
            project_media["item_a"], project_media["item_b"], project_media["item_ab"],
            project_media["item_orphan"], project_media["item_deleted"],
        }


class TestSpecificProjects:
    async def test_include_single_project(self, client: AsyncClient, project_media):
        ids = await _ids(client, project_media["folder"], project_ids=str(project_media["proj_a"]))
        assert ids == {project_media["item_a"], project_media["item_ab"]}

    async def test_include_multiple_projects_is_or(self, client: AsyncClient, project_media):
        ids = await _ids(
            client, project_media["folder"],
            project_ids=f"{project_media['proj_a']},{project_media['proj_b']}",
        )
        assert ids == {project_media["item_a"], project_media["item_b"], project_media["item_ab"]}

    async def test_exclude_single_project(self, client: AsyncClient, project_media):
        ids = await _ids(client, project_media["folder"], excluded_project_ids=str(project_media["proj_a"]))
        # Everything not in project A: B, orphan, and the deleted-project item
        assert ids == {project_media["item_b"], project_media["item_orphan"], project_media["item_deleted"]}

    async def test_in_any_project_but_not_a(self, client: AsyncClient, project_media):
        """The useful combination: in some live project, just not project A."""
        ids = await _ids(
            client, project_media["folder"],
            has_project="true", excluded_project_ids=str(project_media["proj_a"]),
        )
        assert ids == {project_media["item_b"]}


class TestSoftDeletedProjectRelease:
    async def test_deleted_project_membership_does_not_count(self, client: AsyncClient, project_media):
        """Media whose only project is soft-deleted counts as 'not in any project'."""
        in_any = await _ids(client, project_media["folder"], has_project="true")
        not_in_any = await _ids(client, project_media["folder"], has_project="false")
        assert project_media["item_deleted"] not in in_any
        assert project_media["item_deleted"] in not_in_any

    async def test_deleted_project_not_a_filter_target(self, client: AsyncClient, project_media):
        """Filtering by a soft-deleted project id yields nothing."""
        ids = await _ids(client, project_media["folder"], project_ids=str(project_media["proj_deleted"]))
        assert ids == set()


class TestProjectFilterCounts:
    async def test_projects_facet_and_membership_counts(self, client: AsyncClient, project_media):
        response = await client.get("/api/filter-counts", params={"folders": project_media["folder"]})
        assert response.status_code == 200, response.text
        data = response.json()

        projects = data["projects"]
        assert projects[str(project_media["proj_a"])] == 2  # item_a, item_ab
        assert projects[str(project_media["proj_b"])] == 2  # item_b, item_ab
        # Soft-deleted project never appears as a facet option
        assert str(project_media["proj_deleted"]) not in projects

        membership = data["project_membership"]
        assert membership["any"] == 3   # item_a, item_b, item_ab
        assert membership["none"] == 2  # item_orphan, item_deleted
