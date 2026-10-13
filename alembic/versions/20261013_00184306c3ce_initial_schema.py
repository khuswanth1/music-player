"""initial schema

Revision ID: 00184306c3ce
Revises: 
Create Date: 2026-10-13 02:03:59.172140

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '00184306c3ce'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Trigram indexes power partial-word search. pg_trgm is a trusted extension (PG13+),
    # so the database owner can create it without superuser rights.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table('artists',
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('slug', sa.String(length=140), nullable=False),
    sa.Column('bio', sa.Text(), nullable=False),
    sa.Column('image_url', sa.String(length=500), nullable=True),
    sa.Column('verified', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_artists')),
    sa.UniqueConstraint('slug', name=op.f('uq_artists_slug'))
    )
    op.create_index('ix_artists_name_trgm', 'artists', ['name'], unique=False, postgresql_using='gin', postgresql_ops={'name': 'gin_trgm_ops'})
    op.create_table('genres',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('name', sa.String(length=60), nullable=False),
    sa.Column('slug', sa.String(length=60), nullable=False),
    sa.Column('color', sa.String(length=7), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_genres')),
    sa.UniqueConstraint('name', name=op.f('uq_genres_name')),
    sa.UniqueConstraint('slug', name=op.f('uq_genres_slug'))
    )
    op.create_table('roles',
    sa.Column('id', sa.SmallInteger(), nullable=False),
    sa.Column('name', sa.String(length=32), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_roles')),
    sa.UniqueConstraint('name', name=op.f('uq_roles_name'))
    )
    op.create_table('webhook_events',
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('event_id', sa.String(length=255), nullable=False),
    sa.Column('event_type', sa.String(length=100), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.Enum('received', 'processing', 'processed', 'failed', 'ignored', name='webhook_status'), nullable=False),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_webhook_events')),
    sa.UniqueConstraint('provider', 'event_id', name='uq_webhook_events_provider_event')
    )
    op.create_index('ix_webhook_events_received_at', 'webhook_events', ['received_at'], unique=False)
    op.create_index('ix_webhook_events_status_retry', 'webhook_events', ['status', 'next_retry_at'], unique=False)
    op.create_table('albums',
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('artist_id', sa.UUID(), nullable=False),
    sa.Column('album_type', sa.Enum('album', 'single', 'ep', 'compilation', name='album_type'), nullable=False),
    sa.Column('release_date', sa.Date(), nullable=False),
    sa.Column('cover_url', sa.String(length=500), nullable=True),
    sa.Column('is_featured', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['artist_id'], ['artists.id'], name=op.f('fk_albums_artist_id_artists'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_albums'))
    )
    op.create_index(op.f('ix_albums_artist_id'), 'albums', ['artist_id'], unique=False)
    op.create_index(op.f('ix_albums_release_date'), 'albums', ['release_date'], unique=False)
    op.create_index('ix_albums_title_trgm', 'albums', ['title'], unique=False, postgresql_using='gin', postgresql_ops={'title': 'gin_trgm_ops'})
    op.create_table('users',
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('display_name', sa.String(length=80), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=True),
    sa.Column('avatar_url', sa.String(length=500), nullable=True),
    sa.Column('role_id', sa.SmallInteger(), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('google_sub', sa.String(length=255), nullable=True),
    sa.Column('billing_customer_id', sa.String(length=255), nullable=True),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], name=op.f('fk_users_role_id_roles'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('billing_customer_id', name=op.f('uq_users_billing_customer_id')),
    sa.UniqueConstraint('email', name=op.f('uq_users_email')),
    sa.UniqueConstraint('google_sub', name=op.f('uq_users_google_sub'))
    )
    op.create_index(op.f('ix_users_role_id'), 'users', ['role_id'], unique=False)
    op.create_table('followed_artists',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('artist_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['artist_id'], ['artists.id'], name=op.f('fk_followed_artists_artist_id_artists'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_followed_artists_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'artist_id', name=op.f('pk_followed_artists'))
    )
    op.create_index(op.f('ix_followed_artists_artist_id'), 'followed_artists', ['artist_id'], unique=False)
    op.create_table('password_reset_tokens',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('requested_ip', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_password_reset_tokens_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_password_reset_tokens')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_password_reset_tokens_token_hash'))
    )
    op.create_index(op.f('ix_password_reset_tokens_user_id'), 'password_reset_tokens', ['user_id'], unique=False)
    op.create_table('playlists',
    sa.Column('owner_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('cover_url', sa.String(length=500), nullable=True),
    sa.Column('is_public', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('is_collaborative', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('collab_invite_code', sa.String(length=32), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('NOT (is_public AND is_collaborative)', name=op.f('ck_playlists_collab_not_public')),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_playlists_owner_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_playlists')),
    sa.UniqueConstraint('collab_invite_code', name=op.f('uq_playlists_collab_invite_code'))
    )
    op.create_index('ix_playlists_name_trgm', 'playlists', ['name'], unique=False, postgresql_using='gin', postgresql_ops={'name': 'gin_trgm_ops'})
    op.create_index(op.f('ix_playlists_owner_id'), 'playlists', ['owner_id'], unique=False)
    op.create_table('refresh_tokens',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('family_id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('rotated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('user_agent', sa.String(length=255), nullable=True),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_refresh_tokens_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_refresh_tokens')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_refresh_tokens_token_hash'))
    )
    op.create_index('ix_refresh_tokens_expires_at', 'refresh_tokens', ['expires_at'], unique=False)
    op.create_index(op.f('ix_refresh_tokens_family_id'), 'refresh_tokens', ['family_id'], unique=False)
    op.create_index(op.f('ix_refresh_tokens_user_id'), 'refresh_tokens', ['user_id'], unique=False)
    op.create_table('saved_albums',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('album_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['album_id'], ['albums.id'], name=op.f('fk_saved_albums_album_id_albums'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_saved_albums_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'album_id', name=op.f('pk_saved_albums'))
    )
    op.create_index(op.f('ix_saved_albums_album_id'), 'saved_albums', ['album_id'], unique=False)
    op.create_table('songs',
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('artist_id', sa.UUID(), nullable=False),
    sa.Column('album_id', sa.UUID(), nullable=True),
    sa.Column('genre_id', sa.Integer(), nullable=True),
    sa.Column('track_number', sa.Integer(), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=False),
    sa.Column('audio_key', sa.String(length=500), nullable=True),
    sa.Column('audio_mime', sa.String(length=100), nullable=True),
    sa.Column('audio_size', sa.BigInteger(), nullable=True),
    sa.Column('explicit', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('is_premium', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('is_published', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('play_count', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('duration_ms > 0', name=op.f('ck_songs_duration_positive')),
    sa.CheckConstraint('play_count >= 0', name=op.f('ck_songs_play_count_non_negative')),
    sa.ForeignKeyConstraint(['album_id'], ['albums.id'], name=op.f('fk_songs_album_id_albums'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['artist_id'], ['artists.id'], name=op.f('fk_songs_artist_id_artists'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['genre_id'], ['genres.id'], name=op.f('fk_songs_genre_id_genres'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_songs')),
    sa.UniqueConstraint('album_id', 'track_number', name='uq_songs_album_track')
    )
    op.create_index(op.f('ix_songs_album_id'), 'songs', ['album_id'], unique=False)
    op.create_index(op.f('ix_songs_artist_id'), 'songs', ['artist_id'], unique=False)
    op.create_index(op.f('ix_songs_genre_id'), 'songs', ['genre_id'], unique=False)
    op.create_index('ix_songs_play_count', 'songs', [sa.literal_column('play_count DESC')], unique=False)
    op.create_index('ix_songs_title_trgm', 'songs', ['title'], unique=False, postgresql_using='gin', postgresql_ops={'title': 'gin_trgm_ops'})
    op.create_table('subscriptions',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('plan', sa.Enum('premium_monthly', 'premium_yearly', name='subscription_plan'), nullable=False),
    sa.Column('status', sa.Enum('incomplete', 'trialing', 'active', 'past_due', 'canceled', 'unpaid', 'incomplete_expired', name='subscription_status'), nullable=False),
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('provider_subscription_id', sa.String(length=255), nullable=True),
    sa.Column('current_period_start', sa.DateTime(timezone=True), nullable=True),
    sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancel_at_period_end', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('canceled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_subscriptions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_subscriptions')),
    sa.UniqueConstraint('provider_subscription_id', name=op.f('uq_subscriptions_provider_subscription_id'))
    )
    op.create_index('ix_subscriptions_user_status', 'subscriptions', ['user_id', 'status'], unique=False)
    op.create_table('liked_songs',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('song_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['song_id'], ['songs.id'], name=op.f('fk_liked_songs_song_id_songs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_liked_songs_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'song_id', name=op.f('pk_liked_songs'))
    )
    op.create_index(op.f('ix_liked_songs_song_id'), 'liked_songs', ['song_id'], unique=False)
    op.create_index('ix_liked_songs_user_created', 'liked_songs', ['user_id', 'created_at'], unique=False)
    op.create_table('listening_history',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('song_id', sa.UUID(), nullable=False),
    sa.Column('played_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('ms_played', sa.Integer(), nullable=False),
    sa.Column('completed', sa.Boolean(), nullable=False),
    sa.Column('context_type', sa.String(length=20), nullable=True),
    sa.Column('context_id', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['song_id'], ['songs.id'], name=op.f('fk_listening_history_song_id_songs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_listening_history_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_listening_history'))
    )
    op.create_index('ix_listening_history_played_at', 'listening_history', ['played_at'], unique=False)
    op.create_index(op.f('ix_listening_history_song_id'), 'listening_history', ['song_id'], unique=False)
    op.create_index('ix_listening_history_user_played', 'listening_history', ['user_id', sa.literal_column('played_at DESC')], unique=False)
    op.create_table('payments',
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('subscription_id', sa.UUID(), nullable=True),
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('provider_payment_id', sa.String(length=255), nullable=False),
    sa.Column('amount_cents', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('status', sa.Enum('pending', 'succeeded', 'failed', 'refunded', name='payment_status'), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('amount_cents >= 0', name=op.f('ck_payments_amount_non_negative')),
    sa.ForeignKeyConstraint(['subscription_id'], ['subscriptions.id'], name=op.f('fk_payments_subscription_id_subscriptions'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_payments_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_payments')),
    sa.UniqueConstraint('provider_payment_id', name=op.f('uq_payments_provider_payment_id'))
    )
    op.create_index('ix_payments_created_at', 'payments', ['created_at'], unique=False)
    op.create_index(op.f('ix_payments_subscription_id'), 'payments', ['subscription_id'], unique=False)
    op.create_index(op.f('ix_payments_user_id'), 'payments', ['user_id'], unique=False)
    op.create_table('playback_sessions',
    sa.Column('host_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('invite_code', sa.String(length=32), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('current_song_id', sa.UUID(), nullable=True),
    sa.Column('position_ms', sa.Integer(), nullable=False),
    sa.Column('is_playing', sa.Boolean(), nullable=False),
    sa.Column('queue', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('state_updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['current_song_id'], ['songs.id'], name=op.f('fk_playback_sessions_current_song_id_songs'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['host_id'], ['users.id'], name=op.f('fk_playback_sessions_host_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_playback_sessions')),
    sa.UniqueConstraint('invite_code', name=op.f('uq_playback_sessions_invite_code'))
    )
    op.create_index(op.f('ix_playback_sessions_current_song_id'), 'playback_sessions', ['current_song_id'], unique=False)
    op.create_index(op.f('ix_playback_sessions_host_id'), 'playback_sessions', ['host_id'], unique=False)
    op.create_table('player_states',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('current_song_id', sa.UUID(), nullable=True),
    sa.Column('position_ms', sa.Integer(), nullable=False),
    sa.Column('queue', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('context', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('shuffle', sa.Boolean(), nullable=False),
    sa.Column('repeat_mode', sa.Enum('off', 'all', 'one', name='repeat_mode'), nullable=False),
    sa.Column('volume', sa.Float(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['current_song_id'], ['songs.id'], name=op.f('fk_player_states_current_song_id_songs'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_player_states_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_player_states'))
    )
    op.create_index(op.f('ix_player_states_current_song_id'), 'player_states', ['current_song_id'], unique=False)
    op.create_table('playlist_collaborators',
    sa.Column('playlist_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['playlist_id'], ['playlists.id'], name=op.f('fk_playlist_collaborators_playlist_id_playlists'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_playlist_collaborators_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('playlist_id', 'user_id', name=op.f('pk_playlist_collaborators'))
    )
    op.create_index(op.f('ix_playlist_collaborators_user_id'), 'playlist_collaborators', ['user_id'], unique=False)
    op.create_table('playlist_tracks',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('playlist_id', sa.UUID(), nullable=False),
    sa.Column('song_id', sa.UUID(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('added_by_id', sa.UUID(), nullable=True),
    sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('position >= 0', name=op.f('ck_playlist_tracks_position_non_negative')),
    sa.ForeignKeyConstraint(['added_by_id'], ['users.id'], name=op.f('fk_playlist_tracks_added_by_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['playlist_id'], ['playlists.id'], name=op.f('fk_playlist_tracks_playlist_id_playlists'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['song_id'], ['songs.id'], name=op.f('fk_playlist_tracks_song_id_songs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_playlist_tracks')),
    sa.UniqueConstraint('playlist_id', 'position', deferrable=True, initially='DEFERRED', name='uq_playlist_tracks_position')
    )
    op.create_index(op.f('ix_playlist_tracks_added_by_id'), 'playlist_tracks', ['added_by_id'], unique=False)
    op.create_index(op.f('ix_playlist_tracks_song_id'), 'playlist_tracks', ['song_id'], unique=False)
    op.create_table('saved_playlists',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('playlist_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['playlist_id'], ['playlists.id'], name=op.f('fk_saved_playlists_playlist_id_playlists'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_saved_playlists_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'playlist_id', name=op.f('pk_saved_playlists'))
    )
    op.create_index(op.f('ix_saved_playlists_playlist_id'), 'saved_playlists', ['playlist_id'], unique=False)
    op.create_table('playback_session_members',
    sa.Column('session_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['playback_sessions.id'], name=op.f('fk_playback_session_members_session_id_playback_sessions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_playback_session_members_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('session_id', 'user_id', name=op.f('pk_playback_session_members'))
    )
    op.create_index(op.f('ix_playback_session_members_user_id'), 'playback_session_members', ['user_id'], unique=False)

    # Reference data: role ids are referenced by application code (app/core/permissions.py).
    roles = sa.table("roles", sa.column("id", sa.SmallInteger), sa.column("name", sa.String),
                     sa.column("description", sa.String))
    op.bulk_insert(roles, [
        {"id": 1, "name": "listener", "description": "Regular user"},
        {"id": 2, "name": "content_manager", "description": "Manages the music catalog"},
        {"id": 3, "name": "admin", "description": "Full administrative access"},
    ])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_playback_session_members_user_id'), table_name='playback_session_members')
    op.drop_table('playback_session_members')
    op.drop_index(op.f('ix_saved_playlists_playlist_id'), table_name='saved_playlists')
    op.drop_table('saved_playlists')
    op.drop_index(op.f('ix_playlist_tracks_song_id'), table_name='playlist_tracks')
    op.drop_index(op.f('ix_playlist_tracks_added_by_id'), table_name='playlist_tracks')
    op.drop_table('playlist_tracks')
    op.drop_index(op.f('ix_playlist_collaborators_user_id'), table_name='playlist_collaborators')
    op.drop_table('playlist_collaborators')
    op.drop_index(op.f('ix_player_states_current_song_id'), table_name='player_states')
    op.drop_table('player_states')
    op.drop_index(op.f('ix_playback_sessions_host_id'), table_name='playback_sessions')
    op.drop_index(op.f('ix_playback_sessions_current_song_id'), table_name='playback_sessions')
    op.drop_table('playback_sessions')
    op.drop_index(op.f('ix_payments_user_id'), table_name='payments')
    op.drop_index(op.f('ix_payments_subscription_id'), table_name='payments')
    op.drop_index('ix_payments_created_at', table_name='payments')
    op.drop_table('payments')
    op.drop_index('ix_listening_history_user_played', table_name='listening_history')
    op.drop_index(op.f('ix_listening_history_song_id'), table_name='listening_history')
    op.drop_index('ix_listening_history_played_at', table_name='listening_history')
    op.drop_table('listening_history')
    op.drop_index('ix_liked_songs_user_created', table_name='liked_songs')
    op.drop_index(op.f('ix_liked_songs_song_id'), table_name='liked_songs')
    op.drop_table('liked_songs')
    op.drop_index('ix_subscriptions_user_status', table_name='subscriptions')
    op.drop_table('subscriptions')
    op.drop_index('ix_songs_title_trgm', table_name='songs', postgresql_using='gin', postgresql_ops={'title': 'gin_trgm_ops'})
    op.drop_index('ix_songs_play_count', table_name='songs')
    op.drop_index(op.f('ix_songs_genre_id'), table_name='songs')
    op.drop_index(op.f('ix_songs_artist_id'), table_name='songs')
    op.drop_index(op.f('ix_songs_album_id'), table_name='songs')
    op.drop_table('songs')
    op.drop_index(op.f('ix_saved_albums_album_id'), table_name='saved_albums')
    op.drop_table('saved_albums')
    op.drop_index(op.f('ix_refresh_tokens_user_id'), table_name='refresh_tokens')
    op.drop_index(op.f('ix_refresh_tokens_family_id'), table_name='refresh_tokens')
    op.drop_index('ix_refresh_tokens_expires_at', table_name='refresh_tokens')
    op.drop_table('refresh_tokens')
    op.drop_index(op.f('ix_playlists_owner_id'), table_name='playlists')
    op.drop_index('ix_playlists_name_trgm', table_name='playlists', postgresql_using='gin', postgresql_ops={'name': 'gin_trgm_ops'})
    op.drop_table('playlists')
    op.drop_index(op.f('ix_password_reset_tokens_user_id'), table_name='password_reset_tokens')
    op.drop_table('password_reset_tokens')
    op.drop_index(op.f('ix_followed_artists_artist_id'), table_name='followed_artists')
    op.drop_table('followed_artists')
    op.drop_index(op.f('ix_users_role_id'), table_name='users')
    op.drop_table('users')
    op.drop_index('ix_albums_title_trgm', table_name='albums', postgresql_using='gin', postgresql_ops={'title': 'gin_trgm_ops'})
    op.drop_index(op.f('ix_albums_release_date'), table_name='albums')
    op.drop_index(op.f('ix_albums_artist_id'), table_name='albums')
    op.drop_table('albums')
    op.drop_index('ix_webhook_events_status_retry', table_name='webhook_events')
    op.drop_index('ix_webhook_events_received_at', table_name='webhook_events')
    op.drop_table('webhook_events')
    op.drop_table('roles')
    op.drop_table('genres')
    op.drop_index('ix_artists_name_trgm', table_name='artists', postgresql_using='gin', postgresql_ops={'name': 'gin_trgm_ops'})
    op.drop_table('artists')
    for enum_name in ("album_type", "subscription_plan", "subscription_status", "payment_status",
                      "webhook_status", "repeat_mode"):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
