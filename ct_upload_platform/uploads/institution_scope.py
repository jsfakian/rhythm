"""
Institution-wide data sharing helpers.

Colleagues who belong to the same institution (identified by
UserProfile.site_code) get full read/write access to each other's
scanners, protocols, examinations, and upload jobs. `created_by`/
`uploader_id` remain as audit trail fields only and are no longer used
for authorization.
"""

from typing import Optional

from django.db.models import QuerySet
from rest_framework import permissions


def user_site_code(user) -> str:
    """Return *user*'s institution site code, or '' if they lack a profile/site_code."""
    try:
        return user.profile.site_code or ''
    except Exception:
        return ''


def is_institution_admin(user) -> bool:
    """Staff/superusers bypass institution scoping and see everything."""
    return bool(user.is_staff or user.is_superuser)


def scope_queryset(
    qs: QuerySet,
    user,
    *,
    site_code_field: str = 'site_code',
    owner_field: Optional[str] = None,
    owner_value: Optional[str] = None,
) -> QuerySet:
    """
    Restrict *qs* to the caller's institution.

    Staff/superusers see everything. Users with a site_code see every row
    sharing that site_code. Users without one (no profile, or a profile
    predating institution assignment) fall back to `owner_field=owner_value`
    if given, otherwise see nothing — never default-open.
    """
    if is_institution_admin(user):
        return qs
    code = user_site_code(user)
    if code:
        return qs.filter(**{site_code_field: code})
    if owner_field and owner_value:
        return qs.filter(**{owner_field: owner_value})
    return qs.none()


def can_access(
    obj,
    user,
    *,
    site_code_field: str = 'site_code',
    owner_field: Optional[str] = None,
    owner_value: Optional[str] = None,
) -> bool:
    """Object-level counterpart to scope_queryset, for get_object_or_404 checks."""
    if is_institution_admin(user):
        return True
    code = user_site_code(user)
    if code:
        return getattr(obj, site_code_field, None) == code
    if owner_field and owner_value:
        return getattr(obj, owner_field, None) == owner_value
    return False


class IsSameInstitutionOrAdmin(permissions.BasePermission):
    """
    DRF object-level permission: allows staff/superusers, or requesters
    whose site_code matches the object's site_code. Falls back to
    `view.owner_field`/request.user.username for profile-less users,
    mirroring scope_queryset's queryset-level fallback.
    """

    def has_object_permission(self, request, view, obj) -> bool:
        owner_field = getattr(view, 'owner_field', 'created_by')
        return can_access(
            obj,
            request.user,
            owner_field=owner_field,
            owner_value=request.user.username,
        )


class InstitutionScopedQuerysetMixin:
    """
    Mixin for Django generic CBVs: scopes get_queryset() to the caller's
    institution. get_object() then 404s automatically for out-of-scope
    records (matching this app's existing "404 not 403" convention)
    instead of leaking existence via a 403.
    """

    site_code_field = 'site_code'
    owner_field = 'created_by'

    def get_owner_value(self):
        return self.request.user.username

    def get_queryset(self):
        qs = super().get_queryset()
        return scope_queryset(
            qs,
            self.request.user,
            site_code_field=self.site_code_field,
            owner_field=self.owner_field,
            owner_value=self.get_owner_value(),
        )
