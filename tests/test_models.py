import pytest

from gam_policy_diff.errors import DuplicatePolicyError
from gam_policy_diff.models import Policy, PolicySet, ScopeType


def test_scope_type_accepts_aliases() -> None:
    assert ScopeType.parse("Unidad organizativa") is ScopeType.OU
    assert ScopeType.parse("grupo") is ScopeType.GROUP
    assert ScopeType.parse("tenant") is ScopeType.TENANT


def test_scope_type_rejects_unknown_values() -> None:
    with pytest.raises(ValueError, match="tipo de ámbito desconocido"):
        ScopeType.parse("departamento")


def test_policy_normalizes_scope_names() -> None:
    policy = Policy(
        policy_id="drive_sharing_external",
        name="Compartición externa",
        scope_type=ScopeType.OU,
        scope_name="//Ventas//",
        value="off",
        tenant="acme",
    )
    group = Policy(
        policy_id="group_discovery",
        name="Visibilidad",
        scope_type=ScopeType.GROUP,
        scope_name="Ventas-Externos",
        value="true",
        tenant="acme",
    )
    tenant = Policy(
        policy_id="enforce_2sv",
        name="Doble verificación",
        scope_type=ScopeType.TENANT,
        scope_name="acme.test",
        value="true",
        tenant="acme",
    )
    assert policy.scope_name == "/Ventas"
    assert group.scope_name == "ventas-externos"
    assert tenant.scope_name == ""


def test_policy_requires_a_name_for_non_tenant_scopes() -> None:
    with pytest.raises(ValueError, match="necesita un nombre"):
        Policy(
            policy_id="drive_sharing_external",
            name="Compartición externa",
            scope_type=ScopeType.OU,
            scope_name="",
            value="off",
            tenant="acme",
        )


def test_policy_rejects_empty_identifier() -> None:
    with pytest.raises(ValueError, match="identificador"):
        Policy(
            policy_id="",
            name="Política",
            scope_type=ScopeType.TENANT,
            scope_name="",
            value="off",
            tenant="acme",
        )


def test_policy_rejects_empty_name() -> None:
    with pytest.raises(ValueError, match="nombre"):
        Policy(
            policy_id="drive_sharing_external",
            name="",
            scope_type=ScopeType.TENANT,
            scope_name="",
            value="off",
            tenant="acme",
        )


def test_policy_set_indexes_by_policy_and_scope() -> None:
    policy = Policy(
        policy_id="drive_sharing_external",
        name="Compartición externa",
        scope_type=ScopeType.OU,
        scope_name="/Ventas",
        value="off",
        tenant="acme",
    )
    policy_set = PolicySet(tenant="acme")
    policy_set.add(policy)
    assert len(policy_set) == 1
    assert list(policy_set) == [policy]
    assert policy.key == ("drive_sharing_external", "ou", "/Ventas")


def test_policy_set_rejects_duplicates() -> None:
    policy = Policy(
        policy_id="drive_sharing_external",
        name="Compartición externa",
        scope_type=ScopeType.TENANT,
        scope_name="",
        value="off",
        tenant="acme",
    )
    policy_set = PolicySet(tenant="acme")
    policy_set.add(policy)
    with pytest.raises(DuplicatePolicyError, match="drive_sharing_external"):
        policy_set.add(policy)
