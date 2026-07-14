"""Finalize generated Media according to invocation-specific disposition."""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from asset_association_service import mirror_media_associations_to_asset
from asset_service import AssetServiceError, acquire_media_owner, create_asset_from_media
from database import GenerationJob, MediaItem


VALID_OUTPUT_DISPOSITIONS = frozenset({'asset', 'context', 'container_member', 'ephemeral'})


def validate_output_disposition(
    disposition: str,
    context_kind: str | None,
    context_id: str | None,
) -> None:
    if disposition not in VALID_OUTPUT_DISPOSITIONS:
        raise AssetServiceError(f"Invalid output disposition: {disposition}")
    needs_context = disposition in {'context', 'container_member'}
    if needs_context and (not context_kind or not context_id):
        raise AssetServiceError(f"{disposition} output requires a context root")
    if not needs_context and (context_kind or context_id):
        raise AssetServiceError(f"{disposition} output cannot have a context root")


async def finalize_generation_output(
    session: AsyncSession,
    *,
    job: GenerationJob,
    media: MediaItem,
    expires_at: datetime | None = None,
) -> int | None:
    """Create exactly one durable root for a completed generated Media."""
    disposition = 'ephemeral' if media.ephemeral_run_id else (job.output_disposition or 'asset')
    context_kind = job.output_context_kind
    context_id = job.output_context_id
    if disposition == 'ephemeral':
        return None
    validate_output_disposition(disposition, context_kind, context_id)

    if disposition == 'asset':
        asset = await create_asset_from_media(
            session,
            media_id=media.id,
            origin_type='generation_job',
            origin_id=str(job.id),
            idempotency_key=f'generation-job:{job.id}:asset',
            expires_at=expires_at,
        )
        await mirror_media_associations_to_asset(
            session, media_id=media.id, asset_id=asset.id
        )
        job.result_asset_id = asset.id
        await session.flush()
        return asset.id

    await acquire_media_owner(
        session,
        media_id=media.id,
        root_kind=context_kind,
        root_id=context_id,
        role='result' if disposition == 'context' else 'embedded_candidate',
        idempotency_key=f'generation-job:{job.id}:{disposition}',
    )
    return None
