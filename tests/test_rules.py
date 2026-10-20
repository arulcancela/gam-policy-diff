import pytest

from gam_policy_diff.models import Impact
from gam_policy_diff.rules import DECISION_TABLE, classify_change


@pytest.mark.parametrize(
    ("policy_id", "old_value", "new_value", "impact"),
    [
        ("mail_retention_days", "2555", "1095", Impact.BREAKS_FLOW),
        ("drive_sharing_external", "anyone_with_link", "off", Impact.BREAKS_FLOW),
        ("session_length_hours", "12", "4", Impact.BREAKS_FLOW),
        ("enforce_2sv", "false", "true", Impact.NEEDS_TRAINING),
        (
            "alias_domain",
            "acme-origen.test",
            "acme-destino.test",
            Impact.NEEDS_TRAINING,
        ),
        ("drive_default_sharing", "anyone_with_link", "domain", Impact.NEEDS_TRAINING),
        ("calendar_external_invites", "allow", "warn", Impact.NEEDS_TRAINING),
        ("mail_forwarding_external", "allow", "deny", Impact.BREAKS_FLOW),
        ("group_who_can_join", "anyone", "invited", Impact.NEEDS_TRAINING),
        ("calendar_default_view", "week", "month", Impact.NO_IMPACT),
        ("group_discovery", "true", "false", Impact.NO_IMPACT),
        ("directory_contact_sharing", "all", "domain", Impact.NEEDS_TRAINING),
    ],
)
def test_policy_rules(
    policy_id: str,
    old_value: str,
    new_value: str,
    impact: Impact,
) -> None:
    result = classify_change(policy_id, old_value, new_value)

    assert result.impact is impact
    assert result.reason


def test_removed_policy_breaks_the_flow() -> None:
    result = classify_change("drive_sharing_external", "off", None)

    assert result.impact is Impact.BREAKS_FLOW
    assert "pierde una configuración" in result.reason


def test_added_policy_requires_training() -> None:
    result = classify_change("drive_sharing_external", None, "off")

    assert result.impact is Impact.NEEDS_TRAINING
    assert "configuración nueva" in result.reason


def test_equal_values_have_no_impact() -> None:
    result = classify_change("mail_retention_days", "2555", "2555")

    assert result.impact is Impact.NO_IMPACT
    assert "el mismo" in result.reason


def test_equal_values_ignore_case_and_boolean_aliases() -> None:
    assert classify_change("enforce_2sv", "FALSE", "no").impact is Impact.NO_IMPACT


def test_unknown_policy_falls_back_to_training() -> None:
    result = classify_change("politica_sin_regla", "uno", "dos")

    assert result.impact is Impact.NEEDS_TRAINING
    assert "regla específica" in result.reason


def test_retention_can_rise_without_impact() -> None:
    result = classify_change("mail_retention_days", "365", "730")

    assert result.impact is Impact.NO_IMPACT
    assert "aumenta" in result.reason


def test_retention_accepts_units_and_decimal_separator() -> None:
    result = classify_change("mail_retention_days", "2555 days", "1095 días")

    assert result.impact is Impact.BREAKS_FLOW
    assert "2555" in result.reason
    assert "1095" in result.reason


def test_retention_non_numeric_values_fall_back() -> None:
    result = classify_change("mail_retention_days", "mucho", "poco")

    assert result.impact is Impact.NEEDS_TRAINING
    assert "regla específica" in result.reason


def test_session_shortening_threshold() -> None:
    assert classify_change("session_length_hours", "12", "6").impact is Impact.BREAKS_FLOW
    assert classify_change("session_length_hours", "12", "7").impact is Impact.NEEDS_TRAINING
    assert classify_change("session_length_hours", "12", "24").impact is Impact.NO_IMPACT


def test_session_accepts_hour_units() -> None:
    result = classify_change("session_length_hours", "12 h", "4 horas")

    assert result.impact is Impact.BREAKS_FLOW
    assert "12" in result.reason
    assert "4" in result.reason


def test_session_non_numeric_values_fall_back() -> None:
    assert classify_change("session_length_hours", "mucho", "poco").impact is (
        Impact.NEEDS_TRAINING
    )


def test_drive_sharing_compares_levels() -> None:
    assert classify_change("drive_sharing_external", "anyone", "domain").impact is (
        Impact.BREAKS_FLOW
    )
    assert classify_change("drive_sharing_external", "domain", "anyone").impact is (
        Impact.NEEDS_TRAINING
    )
    assert classify_change("drive_sharing_external", "off", "disabled").impact is (Impact.NO_IMPACT)


def test_drive_sharing_unknown_values_fall_back() -> None:
    result = classify_change("drive_sharing_external", "raro", "otro")

    assert result.impact is Impact.NEEDS_TRAINING
    assert "regla específica" in result.reason


def test_default_sharing_always_requires_training() -> None:
    assert classify_change("drive_default_sharing", "domain", "off").impact is (
        Impact.NEEDS_TRAINING
    )
    assert classify_change("drive_default_sharing", "off", "anyone").impact is (
        Impact.NEEDS_TRAINING
    )


def test_two_step_changes_have_explicit_directions() -> None:
    assert classify_change("enforce_2sv", "false", "true").impact is Impact.NEEDS_TRAINING
    assert classify_change("enforce_2sv", "true", "false").impact is Impact.NO_IMPACT
    assert classify_change("enforce_2sv", "true", "enabled").impact is Impact.NO_IMPACT


def test_two_step_unknown_values_fall_back() -> None:
    assert classify_change("enforce_2sv", "tal vez", "quizá").impact is (Impact.NEEDS_TRAINING)


def test_forwarding_changes_have_explicit_directions() -> None:
    assert classify_change("mail_forwarding_external", "allow", "deny").impact is (
        Impact.BREAKS_FLOW
    )
    assert classify_change("mail_forwarding_external", "deny", "allow").impact is (
        Impact.NEEDS_TRAINING
    )
    assert classify_change("mail_forwarding_external", "allow", "allowed").impact is (
        Impact.NO_IMPACT
    )


def test_forwarding_unknown_values_fall_back() -> None:
    assert classify_change("mail_forwarding_external", "tal vez", "quizá").impact is (
        Impact.NEEDS_TRAINING
    )


def test_external_group_members_have_explicit_directions() -> None:
    assert classify_change("group_external_members", "true", "false").impact is (Impact.BREAKS_FLOW)
    assert classify_change("group_external_members", "false", "true").impact is (
        Impact.NEEDS_TRAINING
    )
    assert classify_change("group_external_members", "true", "enabled").impact is (Impact.NO_IMPACT)


def test_group_posting_compares_restriction_levels() -> None:
    assert classify_change("group_who_can_post", "members", "owners").impact is (Impact.BREAKS_FLOW)
    assert classify_change("group_who_can_post", "owners", "members").impact is (
        Impact.NEEDS_TRAINING
    )
    assert classify_change("group_who_can_post", "anyone", "members").impact is (Impact.BREAKS_FLOW)
    assert classify_change("group_who_can_post", "invitados", "mixto").impact is (
        Impact.NEEDS_TRAINING
    )


def test_effective_equality_with_different_representation() -> None:
    assert classify_change("mail_retention_days", "365 days", "365").impact is (Impact.NO_IMPACT)
    assert classify_change("session_length_hours", "12h", "12 hours").impact is (Impact.NO_IMPACT)
    assert classify_change("enforce_2sv", "allow", "yes").impact is Impact.NO_IMPACT
    assert classify_change("group_external_members", "allow", "yes").impact is (Impact.NO_IMPACT)
    assert classify_change("group_who_can_post", "anyone", "all").impact is Impact.NO_IMPACT


def test_external_members_unknown_values_fall_back() -> None:
    result = classify_change("group_external_members", "tal vez", "quizá")

    assert result.impact is Impact.NEEDS_TRAINING
    assert "regla específica" in result.reason


def test_decision_table_is_unique_and_documented() -> None:
    policy_ids = [rule.policy_id for rule in DECISION_TABLE]

    assert len(policy_ids) == len(set(policy_ids))
    assert all(rule.description for rule in DECISION_TABLE)
