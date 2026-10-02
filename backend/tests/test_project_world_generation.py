"""Project lifecycle and tool runs: submits need a live project, and deleting
a project stops its queued work and its flows."""

import httpx
from sqlalchemy import select

from database import Flow, GenerationJob


def _submit_body(project_id=None, prompt="project world"):
    body = {
        "tool_id": "test:text-to-image:test-model",
        "task_type": "text-to-image",
        "folder_path": "/unused",
        "parameters": {"prompt": prompt, "width": 64, "height": 64, "seed": 1},
    }
    if project_id is not None:
        body["project_id"] = project_id
    return body


async def _project(client, name):
    response = await client.post("/api/projects", json={"name": name})
    assert response.status_code == 200
    return response.json()["id"]


class TestSubmitRequiresLiveProject:
    async def test_submit_into_missing_project_is_404(self, generation_client: httpx.AsyncClient):
        response = await generation_client.post("/api/generate/submit", json=_submit_body(999999))
        assert response.status_code == 404
        assert response.json() == {"detail": "Project not found"}

    async def test_submit_into_deleted_project_is_404(self, generation_client: httpx.AsyncClient):
        project_id = await _project(generation_client, "Short lived")
        assert (await generation_client.delete(f"/api/projects/{project_id}")).status_code == 200
        for path in ("/api/generate/submit", "/api/generate/submit-batch"):
            body = _submit_body(project_id)
            if path.endswith("batch"):
                body = dict(body)
            response = await generation_client.post(path, json=body)
            assert response.status_code == 404, (path, response.text)
            assert response.json() == {"detail": "Project not found"}
        response = await generation_client.post(
            "/api/generate/submit-media-batch",
            json={
                **_submit_body(project_id),
                "batch_input": {"field": "image", "media_ids": [1]},
            },
        )
        assert response.status_code == 404

    async def test_submit_into_live_project_queues(
        self, generation_client: httpx.AsyncClient, generation_db_session, generation_queue
    ):
        project_id = await _project(generation_client, "Alive")
        response = await generation_client.post("/api/generate/submit", json=_submit_body(project_id))
        assert response.status_code == 200, response.text
        job_id = response.json()["job_id"]
        async with generation_db_session() as session:
            job = await session.get(GenerationJob, job_id)
            assert job.project_id == project_id
        await generation_queue.cancel_job(job_id)


class TestDeleteProjectStopsWork:
    async def test_delete_cancels_queued_jobs_and_flows(
        self, generation_client: httpx.AsyncClient, generation_db_session
    ):
        project_id = await _project(generation_client, "Busy")
        other = await generation_client.post("/api/generate/submit", json=_submit_body())
        queued = []
        for i in range(2):
            response = await generation_client.post(
                "/api/generate/submit", json=_submit_body(project_id, prompt=f"p{i}")
            )
            assert response.status_code == 200, response.text
            queued.append(response.json()["job_id"])

        async with generation_db_session() as session:
            flow = Flow(name="in project", project_id=project_id, execution_state="running")
            session.add(flow)
            await session.commit()
            flow_id = flow.id

        assert (await generation_client.delete(f"/api/projects/{project_id}")).status_code == 200

        async with generation_db_session() as session:
            jobs = (await session.scalars(
                select(GenerationJob).where(GenerationJob.id.in_(queued))
            )).all()
            assert {job.status for job in jobs} == {"cancelled"}
            assert all("project was deleted" in (job.error or "") for job in jobs)

            untouched = await session.get(GenerationJob, other.json()["job_id"])
            assert untouched.status != "cancelled"

            flow = await session.get(Flow, flow_id)
            assert flow.deleted_at is not None
            assert flow.execution_state == "idle"

        from generation_queue import get_generation_queue
        await get_generation_queue().cancel_job(other.json()["job_id"])

    async def test_output_does_not_revive_deleted_project(
        self, generation_client: httpx.AsyncClient, generation_db_session
    ):
        """Late output from a cancelled run can't re-enter a deleted project."""
        from project_service import attach_media_to_project
        from tests.helpers.media import create_test_media

        project_id = await _project(generation_client, "Late output")
        await generation_client.delete(f"/api/projects/{project_id}")
        async with generation_db_session() as session:
            (media,) = await create_test_media(session, count=1)
            await attach_media_to_project(session, project_id, media.id)
            await session.commit()
            from database import ProjectAsset, ProjectMedia
            assert (await session.scalars(
                select(ProjectAsset).where(ProjectAsset.project_id == project_id)
            )).all() == []
            assert (await session.scalars(
                select(ProjectMedia).where(ProjectMedia.project_id == project_id)
            )).all() == []
