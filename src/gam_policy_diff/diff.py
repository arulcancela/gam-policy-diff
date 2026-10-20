"""Motor de diferencias entre dos conjuntos de políticas."""

from __future__ import annotations

from .models import DiffEntry, PolicySet, ScopeType
from .rules import classify_change


def compare_policy_sets(old: PolicySet, new: PolicySet) -> list[DiffEntry]:
    """Compara la unión de políticas y devuelve una entrada por política y ámbito."""
    entries: list[DiffEntry] = []
    for key in sorted(old.policies.keys() | new.policies.keys()):
        old_policy = old.policies.get(key)
        new_policy = new.policies.get(key)
        old_value = old_policy.value if old_policy is not None else None
        new_value = new_policy.value if new_policy is not None else None
        policy = new_policy if new_policy is not None else old_policy
        assert policy is not None
        classification = classify_change(key[0], old_value, new_value)
        entries.append(
            DiffEntry(
                policy_id=key[0],
                policy_name=policy.name,
                scope_type=ScopeType(key[1]),
                scope_name=key[2],
                old_value=old_value,
                new_value=new_value,
                impact=classification.impact,
                reason=classification.reason,
            )
        )
    return entries
