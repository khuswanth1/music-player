"""open music catalogs: provider provenance, languages, rights and provider bookkeeping

Revision ID: 1370e5b06e0c
Revises: 00184306c3ce
Create Date: 2026-10-13 09:20:21.501631

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.music.languages import FEATURED, LANGUAGES

AVAILABILITY = postgresql.ENUM('playable', 'restricted', 'unavailable', name='availability', create_type=False)

# revision identifiers, used by Alembic.
revision: str = '1370e5b06e0c'
down_revision: Union[str, Sequence[str], None] = '00184306c3ce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('languages',
    sa.Column('code', sa.String(length=12), nullable=False),
    sa.Column('iso639_3', sa.String(length=3), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('native_name', sa.String(length=120), nullable=False),
    sa.Column('region', sa.String(length=32), nullable=False),
    sa.Column('rtl', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('featured_rank', sa.SmallInteger(), nullable=True),
    sa.PrimaryKeyConstraint('code', name=op.f('pk_languages'))
    )
    op.create_index(op.f('ix_languages_region'), 'languages', ['region'], unique=False)
    # Reference data. Later additions to app/music/languages.py need their own data migration.
    languages = sa.table('languages', sa.column('code'), sa.column('iso639_3'), sa.column('name'),
                         sa.column('native_name'), sa.column('region'), sa.column('rtl'), sa.column('featured_rank'))
    op.bulk_insert(languages, [
        {"code": lang.code, "iso639_3": lang.iso639_3, "name": lang.name, "native_name": lang.native_name,
         "region": lang.region, "rtl": lang.rtl,
         "featured_rank": FEATURED.index(lang.code) if lang.code in FEATURED else None}
        for lang in LANGUAGES
    ])
    op.create_table('provider_cache',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('body', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('key', name=op.f('pk_provider_cache'))
    )
    op.create_index(op.f('ix_provider_cache_expires_at'), 'provider_cache', ['expires_at'], unique=False)
    op.create_table('provider_usage',
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('requests', sa.Integer(), server_default='0', nullable=False),
    sa.Column('errors', sa.Integer(), server_default='0', nullable=False),
    sa.Column('last_error', sa.String(length=500), nullable=True),
    sa.Column('last_error_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('requests >= 0 AND errors >= 0', name=op.f('ck_provider_usage_non_negative')),
    sa.PrimaryKeyConstraint('provider', 'day', name=op.f('pk_provider_usage'))
    )
    op.create_table('rights_blocks',
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('provider_track_id', sa.String(length=128), nullable=False),
    sa.Column('reason', sa.String(length=255), nullable=False),
    sa.Column('requested_by', sa.String(length=120), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('source', 'provider_track_id', name=op.f('pk_rights_blocks'))
    )
    op.create_table('catalog_sync_state',
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('language', sa.String(length=12), nullable=False),
    sa.Column('next_offset', sa.Integer(), server_default='0', nullable=False),
    sa.Column('exhausted', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('imported', sa.Integer(), server_default='0', nullable=False),
    sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.String(length=500), nullable=True),
    sa.ForeignKeyConstraint(['language'], ['languages.code'], name=op.f('fk_catalog_sync_state_language_languages'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('provider', 'language', name=op.f('pk_catalog_sync_state'))
    )
    op.create_index('ix_catalog_sync_state_last_synced_at', 'catalog_sync_state', ['last_synced_at'], unique=False)
    op.add_column('albums', sa.Column('provider_album_id', sa.String(length=128), nullable=True))
    op.add_column('albums', sa.Column('source_url', sa.String(length=1000), nullable=True))
    op.add_column('albums', sa.Column('source', sa.String(length=32), server_default='local', nullable=False))
    op.alter_column('albums', 'release_date',
               existing_type=sa.DATE(),
               nullable=True)
    op.alter_column('albums', 'cover_url',
               existing_type=sa.VARCHAR(length=500),
               type_=sa.String(length=1000),
               existing_nullable=True)
    op.create_unique_constraint('uq_albums_source_provider_id', 'albums', ['source', 'provider_album_id'])
    op.add_column('artists', sa.Column('provider_artist_id', sa.String(length=128), nullable=True))
    op.add_column('artists', sa.Column('source_url', sa.String(length=1000), nullable=True))
    op.add_column('artists', sa.Column('musicbrainz_id', sa.UUID(), nullable=True))
    op.add_column('artists', sa.Column('country', sa.String(length=2), nullable=True))
    op.add_column('artists', sa.Column('source', sa.String(length=32), server_default='local', nullable=False))
    op.alter_column('artists', 'image_url',
               existing_type=sa.VARCHAR(length=500),
               type_=sa.String(length=1000),
               existing_nullable=True)
    op.create_unique_constraint('uq_artists_source_provider_id', 'artists', ['source', 'provider_artist_id'])
    op.add_column('songs', sa.Column('provider_track_id', sa.String(length=128), nullable=True))
    op.add_column('songs', sa.Column('source_url', sa.String(length=1000), nullable=True))
    op.add_column('songs', sa.Column('artwork_url', sa.String(length=1000), nullable=True))
    op.add_column('songs', sa.Column('language', sa.String(length=12), nullable=True))
    op.add_column('songs', sa.Column('language_source', sa.String(length=16), nullable=True))
    op.add_column('songs', sa.Column('country', sa.String(length=2), nullable=True))
    op.add_column('songs', sa.Column('isrc', sa.String(length=12), nullable=True))
    op.add_column('songs', sa.Column('musicbrainz_recording_id', sa.UUID(), nullable=True))
    op.add_column('songs', sa.Column('enriched_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('songs', sa.Column('provider_popularity', sa.Float(), nullable=True))
    op.add_column('songs', sa.Column('remote_stream_url', sa.String(length=2000), nullable=True))
    op.add_column('songs', sa.Column('remote_download_url', sa.String(length=2000), nullable=True))
    op.add_column('songs', sa.Column('license_code', sa.String(length=16), nullable=True))
    op.add_column('songs', sa.Column('license_name', sa.String(length=80), nullable=True))
    op.add_column('songs', sa.Column('license_url', sa.String(length=500), nullable=True))
    op.add_column('songs', sa.Column('attribution', sa.Text(), nullable=True))
    AVAILABILITY.create(op.get_bind(), checkfirst=True)
    op.add_column('songs', sa.Column('availability', AVAILABILITY, server_default='playable', nullable=False))
    op.add_column('songs', sa.Column('stream_allowed', sa.Boolean(), server_default='true', nullable=False))
    op.add_column('songs', sa.Column('download_allowed', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('songs', sa.Column('restriction_reason', sa.String(length=255), nullable=True))
    op.add_column('songs', sa.Column('rights_checked_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('songs', sa.Column('takedown_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('songs', sa.Column('source', sa.String(length=32), server_default='local', nullable=False))
    op.create_index('ix_songs_availability_language', 'songs', ['availability', 'language'], unique=False)
    op.create_index('ix_songs_enrichment_pending', 'songs', ['created_at'], unique=False, postgresql_where="source <> 'local' AND enriched_at IS NULL")
    op.create_index(op.f('ix_songs_language'), 'songs', ['language'], unique=False)
    op.create_unique_constraint('uq_songs_source_provider_id', 'songs', ['source', 'provider_track_id'])
    op.create_foreign_key(op.f('fk_songs_language_languages'), 'songs', 'languages', ['language'], ['code'], ondelete='SET NULL')
    op.create_check_constraint(op.f('ck_songs_popularity_range'), 'songs',
                               'provider_popularity IS NULL OR provider_popularity BETWEEN 0 AND 1')
    op.create_check_constraint(op.f('ck_songs_provider_id_matches_source'), 'songs',
                               "(source = 'local') = (provider_track_id IS NULL)")
    op.add_column('users', sa.Column('preferred_languages', postgresql.ARRAY(sa.String(length=12)), server_default='{}', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    # Provider rows can't survive the old schema (e.g. albums without a release date): remove them first.
    op.execute("DELETE FROM songs WHERE source <> 'local'")
    op.execute("DELETE FROM albums WHERE source <> 'local' OR release_date IS NULL")
    op.execute("DELETE FROM artists WHERE source <> 'local' AND NOT EXISTS (SELECT 1 FROM albums WHERE albums.artist_id = artists.id) "
               "AND NOT EXISTS (SELECT 1 FROM songs WHERE songs.artist_id = artists.id)")
    op.drop_column('users', 'preferred_languages')
    op.drop_constraint(op.f('ck_songs_provider_id_matches_source'), 'songs', type_='check')
    op.drop_constraint(op.f('ck_songs_popularity_range'), 'songs', type_='check')
    op.drop_constraint(op.f('fk_songs_language_languages'), 'songs', type_='foreignkey')
    op.drop_constraint('uq_songs_source_provider_id', 'songs', type_='unique')
    op.drop_index(op.f('ix_songs_language'), table_name='songs')
    op.drop_index('ix_songs_enrichment_pending', table_name='songs', postgresql_where="source <> 'local' AND enriched_at IS NULL")
    op.drop_index('ix_songs_availability_language', table_name='songs')
    op.drop_column('songs', 'source')
    op.drop_column('songs', 'takedown_at')
    op.drop_column('songs', 'rights_checked_at')
    op.drop_column('songs', 'restriction_reason')
    op.drop_column('songs', 'download_allowed')
    op.drop_column('songs', 'stream_allowed')
    op.drop_column('songs', 'availability')
    AVAILABILITY.drop(op.get_bind(), checkfirst=True)
    op.drop_column('songs', 'attribution')
    op.drop_column('songs', 'license_url')
    op.drop_column('songs', 'license_name')
    op.drop_column('songs', 'license_code')
    op.drop_column('songs', 'remote_download_url')
    op.drop_column('songs', 'remote_stream_url')
    op.drop_column('songs', 'provider_popularity')
    op.drop_column('songs', 'enriched_at')
    op.drop_column('songs', 'musicbrainz_recording_id')
    op.drop_column('songs', 'isrc')
    op.drop_column('songs', 'country')
    op.drop_column('songs', 'language_source')
    op.drop_column('songs', 'language')
    op.drop_column('songs', 'artwork_url')
    op.drop_column('songs', 'source_url')
    op.drop_column('songs', 'provider_track_id')
    op.drop_constraint('uq_artists_source_provider_id', 'artists', type_='unique')
    op.alter_column('artists', 'image_url',
               existing_type=sa.String(length=1000),
               type_=sa.VARCHAR(length=500),
               existing_nullable=True)
    op.drop_column('artists', 'source')
    op.drop_column('artists', 'country')
    op.drop_column('artists', 'musicbrainz_id')
    op.drop_column('artists', 'source_url')
    op.drop_column('artists', 'provider_artist_id')
    op.drop_constraint('uq_albums_source_provider_id', 'albums', type_='unique')
    op.alter_column('albums', 'cover_url',
               existing_type=sa.String(length=1000),
               type_=sa.VARCHAR(length=500),
               existing_nullable=True)
    op.alter_column('albums', 'release_date',
               existing_type=sa.DATE(),
               nullable=False)
    op.drop_column('albums', 'source')
    op.drop_column('albums', 'source_url')
    op.drop_column('albums', 'provider_album_id')
    op.drop_index('ix_catalog_sync_state_last_synced_at', table_name='catalog_sync_state')
    op.drop_table('catalog_sync_state')
    op.drop_table('rights_blocks')
    op.drop_table('provider_usage')
    op.drop_index(op.f('ix_provider_cache_expires_at'), table_name='provider_cache')
    op.drop_table('provider_cache')
    op.drop_index(op.f('ix_languages_region'), table_name='languages')
    op.drop_table('languages')
