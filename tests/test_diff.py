from collections import Counter
from pathlib import Path

from gam_policy_diff.diff import compare_policy_sets
from gam_policy_diff.loader import load_policy_set
from gam_policy_diff.models import (
    IMPACT_ORDER,
    DiffEntry,
    Impact,
    Policy,
    PolicySet,
    ScopeType,
)


def make_policy(
    policy_id: str,
    value: str,
    scope_type: ScopeType = ScopeType.TENANT,
    scope_name: str = "",
    name: str | None = None,
    tenant: str = "acme",
) -> Policy:
    return Policy(
        policy_id=policy_id,
        name=name or policy_id,
        scope_type=scope_type,
        scope_name=scope_name,
        value=value,
        tenant=tenant,
    )


def test_compares_all_fixture_policies(fixtures_dir: Path) -> None:
    entries = compare_policy_sets(
        load_policy_set(fixtures_dir / "tenant-origen.csv"),
        load_policy_set(fixtures_dir / "tenant-destino.csv"),
    )

    assert len(entries) == 15
    assert Counter(entry.impact for entry in entries) == Counter(
        {
            Impact.BREAKS_FLOW: 4,
            Impact.NEEDS_TRAINING: 5,
            Impact.NO_IMPACT: 6,
        }
    )
    assert sum(entry.changed for entry in entries) == 9
    assert [entry.key for entry in entries] == sorted(entry.key for entry in entries)


def test_fixture_diff_contains_the_expected_cases(fixtures_dir: Path) -> None:
    entries = compare_policy_sets(
        load_policy_set(fixtures_dir / "tenant-origen.csv"),
        load_policy_set(fixtures_dir / "tenant-destino.csv"),
    )
    by_key = {entry.key: entry for entry in entries}

    retention = by_key[("mail_retention_days", "tenant", "")]
    assert retention.old_value == "2555"
    assert retention.new_value == "1095"
    assert retention.impact is Impact.BREAKS_FLOW
    assert "retención" in retention.reason

    sharing = by_key[("drive_sharing_external", "tenant", "")]
    assert sharing.impact is Impact.BREAKS_FLOW
    assert sharing.scope_label == "Tenant"

    forwarding = by_key[("mail_forwarding_external", "ou", "/Ventas")]
    assert forwarding.impact is Impact.BREAKS_FLOW
    assert forwarding.scope_label == "OU: /Ventas"

    group = by_key[("group_who_can_join", "group", "ventas-externos")]
    assert group.impact is Impact.NEEDS_TRAINING
    assert group.scope_label == "Grupo: ventas-externos"

    unchanged = by_key[("drive_sharing_external", "ou", "/Direccion")]
    assert unchanged.impact is Impact.NO_IMPACT
    assert unchanged.changed is False
    assert "el mismo" in unchanged.reason


def test_every_entry_has_a_name_and_a_reason(fixtures_dir: Path) -> None:
    entries = compare_policy_sets(
        load_policy_set(fixtures_dir / "tenant-origen.csv"),
        load_policy_set(fixtures_dir / "tenant-destino.csv"),
    )

    assert all(entry.policy_name for entry in entries)
    assert all(entry.reason for entry in entries)


def test_added_and_removed_policies_are_reported() -> None:
    old = PolicySet(tenant="origen")
    old.add(make_policy("retirada", "on", name="Política retirada"))
    old.add(make_policy("igual", "off", name="Política igual"))
    old.add(make_policy("mail_retention_days", "365", name="Retención"))
    new = PolicySet(tenant="destino")
    new.add(make_policy("nueva", "on", name="Política nueva"))
    new.add(make_policy("igual", "off", name="Política igual"))
    new.add(make_policy("mail_retention_days", "180", name="Retención"))

    entries = compare_policy_sets(old, new)
    by_id = {entry.policy_id: entry for entry in entries}

    removed = by_id["retirada"]
    assert removed.old_value == "on"
    assert removed.new_value is None
    assert removed.impact is Impact.BREAKS_FLOW
    assert removed.policy_name == "Política retirada"

    added = by_id["nueva"]
    assert added.old_value is None
    assert added.new_value == "on"
    assert added.impact is Impact.NEEDS_TRAINING
    assert added.policy_name == "Política nueva"

    assert by_id["igual"].impact is Impact.NO_IMPACT
    assert by_id["mail_retention_days"].impact is Impact.BREAKS_FLOW


def test_ou_losing_a_policy_is_breaking() -> None:
    old = PolicySet(tenant="origen")
    old.add(
        make_policy(
            "drive_sharing_external",
            "off",
            scope_type=ScopeType.OU,
            scope_name="/Ventas",
        )
    )

    entries = compare_policy_sets(old, PolicySet(tenant="destino"))

    assert len(entries) == 1
    assert entries[0].scope_name == "/Ventas"
    assert entries[0].old_value == "off"
    assert entries[0].new_value is None
    assert entries[0].impact is Impact.BREAKS_FLOW


def test_same_set_only_produces_no_impact_entries(fixtures_dir: Path) -> None:
    policies = load_policy_set(fixtures_dir / "tenant-origen.csv")

    entries = compare_policy_sets(policies, policies)

    assert len(entries) == 15
    assert all(entry.impact is Impact.NO_IMPACT for entry in entries)
    assert not any(entry.changed for entry in entries)


def test_diff_entry_changed_uses_normalized_values() -> None:
    def entry(old_value: str | None, new_value: str | None) -> DiffEntry:
        return DiffEntry(
            policy_id="enforce_2sv",
            policy_name="Doble verificación",
            scope_type=ScopeType.TENANT,
            scope_name="",
            old_value=old_value,
            new_value=new_value,
            impact=Impact.NO_IMPACT,
            reason="Prueba",
        )

    assert entry("OFF", "off").changed is False
    assert entry("12", "12.0").changed is False
    assert entry("12", "12 horas").changed is True
    assert entry(None, "true").changed is True
    assert entry("true", None).changed is True


def test_diff_entry_scope_labels() -> None:
    assert (
        DiffEntry(
            policy_id="x",
            policy_name="X",
            scope_type=ScopeType.USER,
            scope_name="ana@acme.test",
            old_value="a",
            new_value="b",
            impact=Impact.NO_IMPACT,
            reason="Prueba",
        ).scope_label
        == "Usuario: ana@acme.test"
    )


def test_impact_order_and_labels() -> None:
    assert [impact.label for impact in IMPACT_ORDER] == [
        "Rompe flujo",
        "Requiere formación",
        "Sin impacto",
    ]
