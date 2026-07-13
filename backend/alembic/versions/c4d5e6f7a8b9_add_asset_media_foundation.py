"""add asset/media foundation

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-07-13

Additive foundation for stable Assets, immutable Revisions, Media storage
indirection, strong ownership, editor snapshots, and normalized containment.
No legacy reads or writes are removed by this migration.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, Sequence[str], None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'storage_objects',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('object_key', sa.String(), nullable=True),
        sa.Column('external_path', sa.String(), nullable=True),
        sa.Column('expected_hash', sa.String(), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('mime_type', sa.String(), nullable=True),
        sa.Column('state', sa.String(), nullable=False, server_default='available'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('verified_at', sa.DateTime(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint("kind IN ('managed', 'external')", name='ck_storage_objects_kind'),
        sa.CheckConstraint("state IN ('available', 'missing', 'deleting')", name='ck_storage_objects_state'),
        sa.CheckConstraint(
            "(kind = 'managed' AND object_key IS NOT NULL AND external_path IS NULL) OR "
            "(kind = 'external' AND external_path IS NOT NULL AND object_key IS NULL)",
            name='ck_storage_objects_locator',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('object_key'),
        sqlite_autoincrement=True,
    )
    op.create_index('ix_storage_objects_id', 'storage_objects', ['id'])
    op.create_index('ix_storage_objects_kind', 'storage_objects', ['kind'])
    op.create_index('ix_storage_objects_expected_hash', 'storage_objects', ['expected_hash'])
    op.create_index('ix_storage_objects_state', 'storage_objects', ['state'])
    op.create_index('ix_storage_objects_deleted_at', 'storage_objects', ['deleted_at'])

    with op.batch_alter_table('media_items') as batch_op:
        batch_op.add_column(sa.Column('storage_object_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_media_items_storage_object_id',
            'storage_objects',
            ['storage_object_id'],
            ['id'],
            ondelete='RESTRICT',
        )
        batch_op.create_index('ix_media_items_storage_object_id', ['storage_object_id'])

    op.create_table(
        'assets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('asset_type', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=True),
        sa.Column('current_revision_id', sa.Integer(), nullable=True),
        sa.Column('state', sa.String(), nullable=False, server_default='active'),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('origin_type', sa.String(), nullable=True),
        sa.Column('origin_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint("state IN ('active', 'trashed', 'deleting')", name='ck_assets_state'),
        sa.PrimaryKeyConstraint('id'),
        sqlite_autoincrement=True,
    )
    for column in ('id', 'asset_type', 'current_revision_id', 'state', 'expires_at', 'origin_type', 'deleted_at'):
        op.create_index(f'ix_assets_{column}', 'assets', [column])

    op.create_table(
        'asset_revisions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('asset_id', sa.Integer(), nullable=False),
        sa.Column('parent_revision_id', sa.Integer(), nullable=True),
        sa.Column('primary_media_id', sa.Integer(), nullable=False),
        sa.Column('revision_number', sa.Integer(), nullable=False),
        sa.Column('note', sa.String(), nullable=True),
        sa.Column('missing_parent', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['parent_revision_id'], ['asset_revisions.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['primary_media_id'], ['media_items.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sqlite_autoincrement=True,
    )
    for column in ('id', 'asset_id', 'parent_revision_id', 'primary_media_id', 'deleted_at'):
        op.create_index(f'ix_asset_revisions_{column}', 'asset_revisions', [column])
    op.create_index(
        'idx_asset_revisions_asset_number',
        'asset_revisions',
        ['asset_id', 'revision_number'],
        unique=True,
    )
    op.create_index(
        'idx_asset_revisions_primary_media',
        'asset_revisions',
        ['primary_media_id'],
        unique=True,
    )

    op.create_table(
        'media_owners',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('media_id', sa.Integer(), nullable=False),
        sa.Column('root_kind', sa.String(), nullable=False),
        sa.Column('root_id', sa.String(), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('idempotency_key', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['media_id'], ['media_items.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sqlite_autoincrement=True,
    )
    for column in ('id', 'media_id', 'root_kind', 'root_id', 'idempotency_key', 'deleted_at'):
        op.create_index(f'ix_media_owners_{column}', 'media_owners', [column])
    op.create_index('idx_media_owners_root', 'media_owners', ['root_kind', 'root_id', 'deleted_at'])
    op.create_index('idx_media_owners_media_live', 'media_owners', ['media_id', 'deleted_at'])
    op.create_index(
        'idx_media_owners_live_edge',
        'media_owners',
        ['media_id', 'root_kind', 'root_id', 'role'],
        unique=True,
        sqlite_where=sa.text('deleted_at IS NULL'),
    )

    op.create_table(
        'working_documents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('asset_id', sa.Integer(), nullable=False),
        sa.Column('editor_type', sa.String(), nullable=False),
        sa.Column('branch_key', sa.String(), nullable=False, server_default='main'),
        sa.Column('base_revision_id', sa.Integer(), nullable=True),
        sa.Column('state_locator', sa.String(), nullable=True),
        sa.Column('generation', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['base_revision_id'], ['asset_revisions.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sqlite_autoincrement=True,
    )
    for column in ('id', 'asset_id', 'editor_type', 'base_revision_id', 'deleted_at'):
        op.create_index(f'ix_working_documents_{column}', 'working_documents', [column])
    op.create_index(
        'idx_working_documents_asset_branch',
        'working_documents',
        ['asset_id', 'editor_type', 'branch_key'],
    )

    op.create_table(
        'asset_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('owner_kind', sa.String(), nullable=False),
        sa.Column('owner_id', sa.String(), nullable=False),
        sa.Column('media_id', sa.Integer(), nullable=False),
        sa.Column('source_asset_id', sa.Integer(), nullable=True),
        sa.Column('source_revision_id', sa.Integer(), nullable=True),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint("owner_kind IN ('revision', 'working_document')", name='ck_asset_snapshots_owner_kind'),
        sa.ForeignKeyConstraint(['media_id'], ['media_items.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['source_asset_id'], ['assets.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['source_revision_id'], ['asset_revisions.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sqlite_autoincrement=True,
    )
    for column in ('id', 'owner_kind', 'owner_id', 'media_id', 'source_asset_id', 'source_revision_id', 'deleted_at'):
        op.create_index(f'ix_asset_snapshots_{column}', 'asset_snapshots', [column])
    op.create_index('idx_asset_snapshots_owner', 'asset_snapshots', ['owner_kind', 'owner_id', 'deleted_at'])

    op.create_table(
        'container_members',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('container_revision_id', sa.Integer(), nullable=False),
        sa.Column('linked_asset_id', sa.Integer(), nullable=True),
        sa.Column('embedded_media_id', sa.Integer(), nullable=True),
        sa.Column('missing_linked_asset', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('member_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('row_index', sa.Integer(), nullable=True),
        sa.Column('column_index', sa.Integer(), nullable=True),
        sa.Column('caption', sa.String(), nullable=True),
        sa.Column('title', sa.String(), nullable=True),
        sa.Column('member_metadata', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "(linked_asset_id IS NOT NULL AND embedded_media_id IS NULL AND missing_linked_asset = 0) OR "
            "(linked_asset_id IS NULL AND embedded_media_id IS NOT NULL AND missing_linked_asset = 0) OR "
            "(linked_asset_id IS NULL AND embedded_media_id IS NULL AND missing_linked_asset = 1)",
            name='ck_container_members_target',
        ),
        sa.ForeignKeyConstraint(['container_revision_id'], ['asset_revisions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['linked_asset_id'], ['assets.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['embedded_media_id'], ['media_items.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sqlite_autoincrement=True,
    )
    for column in ('id', 'container_revision_id', 'linked_asset_id', 'embedded_media_id', 'deleted_at'):
        op.create_index(f'ix_container_members_{column}', 'container_members', [column])
    op.create_index(
        'idx_container_members_revision_order',
        'container_members',
        ['container_revision_id', 'member_order'],
    )

    op.create_table(
        'asset_migration_map',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('legacy_media_id', sa.Integer(), nullable=False),
        sa.Column('asset_id', sa.Integer(), nullable=True),
        sa.Column('classification', sa.String(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('evidence', sa.Text(), nullable=True),
        sa.Column('migration_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('status', sa.String(), nullable=False, server_default='classified'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sqlite_autoincrement=True,
    )
    for column in ('id', 'legacy_media_id', 'asset_id', 'classification', 'status', 'deleted_at'):
        op.create_index(f'ix_asset_migration_map_{column}', 'asset_migration_map', [column])
    op.create_index(
        'idx_asset_migration_media_version',
        'asset_migration_map',
        ['legacy_media_id', 'migration_version'],
    )

    op.create_table(
        'managed_artifacts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('owner_kind', sa.String(), nullable=False),
        sa.Column('owner_id', sa.String(), nullable=False),
        sa.Column('media_id', sa.Integer(), nullable=True),
        sa.Column('artifact_kind', sa.String(), nullable=False),
        sa.Column('locator', sa.String(), nullable=False),
        sa.Column('state', sa.String(), nullable=False, server_default='available'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint("state IN ('available', 'deleting', 'missing')", name='ck_managed_artifacts_state'),
        sa.ForeignKeyConstraint(['media_id'], ['media_items.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sqlite_autoincrement=True,
    )
    for column in ('id', 'owner_kind', 'owner_id', 'media_id', 'artifact_kind', 'state', 'deleted_at'):
        op.create_index(f'ix_managed_artifacts_{column}', 'managed_artifacts', [column])
    op.create_index('idx_managed_artifacts_owner', 'managed_artifacts', ['owner_kind', 'owner_id', 'deleted_at'])

    op.create_table(
        'asset_markers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('asset_id', sa.Integer(), nullable=False),
        sa.Column('marker_id', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(), nullable=False, server_default='manual'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['marker_id'], ['markers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sqlite_autoincrement=True,
    )
    for column in ('id', 'asset_id', 'marker_id', 'deleted_at'):
        op.create_index(f'ix_asset_markers_{column}', 'asset_markers', [column])
    op.create_index(
        'idx_asset_markers_live', 'asset_markers', ['asset_id', 'marker_id'],
        unique=True, sqlite_where=sa.text('deleted_at IS NULL'),
    )

    op.create_table(
        'asset_tags',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('asset_id', sa.Integer(), nullable=False),
        sa.Column('tag_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tag_id'], ['tags.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sqlite_autoincrement=True,
    )
    for column in ('id', 'asset_id', 'tag_id', 'deleted_at'):
        op.create_index(f'ix_asset_tags_{column}', 'asset_tags', [column])
    op.create_index(
        'idx_asset_tags_live', 'asset_tags', ['asset_id', 'tag_id'],
        unique=True, sqlite_where=sa.text('deleted_at IS NULL'),
    )

    op.create_table(
        'project_assets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('asset_id', sa.Integer(), nullable=False),
        sa.Column('added_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sqlite_autoincrement=True,
    )
    for column in ('id', 'project_id', 'asset_id', 'deleted_at'):
        op.create_index(f'ix_project_assets_{column}', 'project_assets', [column])
    op.create_index(
        'idx_project_assets_live', 'project_assets', ['project_id', 'asset_id'],
        unique=True, sqlite_where=sa.text('deleted_at IS NULL'),
    )

    op.create_table(
        'board_asset_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('board_section_id', sa.Integer(), nullable=False),
        sa.Column('asset_id', sa.Integer(), nullable=False),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('added_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['board_section_id'], ['board_sections.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sqlite_autoincrement=True,
    )
    for column in ('id', 'board_section_id', 'asset_id', 'deleted_at'):
        op.create_index(f'ix_board_asset_items_{column}', 'board_asset_items', [column])
    op.create_index(
        'idx_board_asset_items_order', 'board_asset_items', ['board_section_id', 'display_order'],
    )
    op.create_index(
        'idx_board_asset_items_live', 'board_asset_items', ['board_section_id', 'asset_id'],
        unique=True, sqlite_where=sa.text('deleted_at IS NULL'),
    )


def downgrade() -> None:
    op.drop_table('board_asset_items')
    op.drop_table('project_assets')
    op.drop_table('asset_tags')
    op.drop_table('asset_markers')
    op.drop_table('managed_artifacts')
    op.drop_table('asset_migration_map')
    op.drop_table('container_members')
    op.drop_table('asset_snapshots')
    op.drop_table('working_documents')
    op.drop_table('media_owners')
    op.drop_table('asset_revisions')
    op.drop_table('assets')
    with op.batch_alter_table('media_items') as batch_op:
        batch_op.drop_constraint('fk_media_items_storage_object_id', type_='foreignkey')
        batch_op.drop_index('ix_media_items_storage_object_id')
        batch_op.drop_column('storage_object_id')
    op.drop_table('storage_objects')
