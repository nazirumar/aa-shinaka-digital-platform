"""Template helpers for role-aware navigation.

These only *hide* navigation. Every view re-checks permissions server-side via
``apps.accounts.permissions``.
"""

from django import template

from apps.accounts.permissions import user_capabilities

register = template.Library()


@register.simple_tag
def capabilities(user) -> frozenset[str]:
    return user_capabilities(user)


@register.simple_tag
def has_capability(user, capability: str) -> bool:
    return user.is_superuser or capability in user_capabilities(user)
