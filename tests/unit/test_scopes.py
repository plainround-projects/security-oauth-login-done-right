import pytest

from oidc_login.domain.errors import InsufficientScopeError
from oidc_login.domain.scopes import requested_scope, require

ALLOWED = frozenset({"reports:read"})


def test_the_base_scope_is_always_requested():
    assert requested_scope([], ALLOWED) == "openid profile email"


def test_an_allow_listed_extra_scope_is_added_once():
    assert requested_scope(["reports:read", "reports:read"], ALLOWED) == "openid profile email reports:read"


def test_scopes_that_are_not_on_the_allow_list_are_dropped_not_forwarded():
    assert requested_scope(["admin", "reports:read", "offline_access"], ALLOWED) == "openid profile email reports:read"


def test_require_passes_for_a_granted_scope_and_names_the_missing_one():
    require(frozenset({"openid", "reports:read"}), "reports:read")
    with pytest.raises(InsufficientScopeError, match="reports:read") as error:
        require(frozenset({"openid"}), "reports:read")
    assert error.value.scope == "reports:read"
