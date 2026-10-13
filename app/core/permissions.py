import enum


class RoleName(enum.StrEnum):
    listener = "listener"
    content_manager = "content_manager"
    admin = "admin"


# Must match the rows inserted by the initial migration.
ROLE_IDS = {RoleName.listener: 1, RoleName.content_manager: 2, RoleName.admin: 3}


class Perm(enum.StrEnum):
    catalog_write = "catalog:write"
    analytics_view = "analytics:view"
    playlists_moderate = "playlists:moderate"
    users_manage = "users:manage"
    billing_manage = "billing:manage"
    webhooks_manage = "webhooks:manage"


ROLE_PERMISSIONS: dict[str, frozenset[Perm]] = {
    RoleName.listener: frozenset(),
    RoleName.content_manager: frozenset({Perm.catalog_write, Perm.analytics_view, Perm.playlists_moderate}),
    RoleName.admin: frozenset(Perm),
}


def has_permission(role: str, perm: Perm) -> bool:
    return perm in ROLE_PERMISSIONS.get(role, frozenset())


def permissions_for(role: str) -> list[str]:
    return sorted(p.value for p in ROLE_PERMISSIONS.get(role, frozenset()))
