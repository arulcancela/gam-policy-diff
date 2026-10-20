"""Modelo de datos de las políticas y sus ámbitos de aplicación."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import StrEnum

from .errors import DuplicatePolicyError
from .normalization import normalize_header, normalize_value

_MULTIPLE_SLASHES = re.compile(r"/+")


class ScopeType(StrEnum):
    """Ámbito al que se aplica una política."""

    TENANT = "tenant"
    OU = "ou"
    GROUP = "group"
    USER = "user"

    @classmethod
    def parse(cls, raw: str) -> ScopeType:
        key = normalize_header(raw)
        try:
            return _SCOPE_ALIASES[key]
        except KeyError:
            allowed = ", ".join(item.value for item in cls)
            raise ValueError(
                f"tipo de ámbito desconocido: {raw!r}; valores admitidos: {allowed}"
            ) from None


_SCOPE_ALIASES: dict[str, ScopeType] = {
    "tenant": ScopeType.TENANT,
    "cliente": ScopeType.TENANT,
    "organizacion": ScopeType.TENANT,
    "organization": ScopeType.TENANT,
    "customer": ScopeType.TENANT,
    "ou": ScopeType.OU,
    "unidad_organizativa": ScopeType.OU,
    "organizational_unit": ScopeType.OU,
    "org_unit": ScopeType.OU,
    "orgunit": ScopeType.OU,
    "group": ScopeType.GROUP,
    "grupo": ScopeType.GROUP,
    "user": ScopeType.USER,
    "usuario": ScopeType.USER,
}


class Impact(StrEnum):
    """Cubo de impacto de un cambio para el usuario final."""

    BREAKS_FLOW = "rompe_flujo"
    NEEDS_TRAINING = "requiere_formacion"
    NO_IMPACT = "sin_impacto"

    @property
    def label(self) -> str:
        return _IMPACT_LABELS[self]


_IMPACT_LABELS: dict[Impact, str] = {
    Impact.BREAKS_FLOW: "Rompe flujo",
    Impact.NEEDS_TRAINING: "Requiere formación",
    Impact.NO_IMPACT: "Sin impacto",
}

IMPACT_ORDER: tuple[Impact, ...] = (
    Impact.BREAKS_FLOW,
    Impact.NEEDS_TRAINING,
    Impact.NO_IMPACT,
)


def normalize_scope_name(scope_type: ScopeType, raw: str) -> str:
    """Normaliza el nombre del ámbito para que el índice sea estable."""
    name = raw.strip()
    if scope_type is ScopeType.TENANT:
        return ""
    if not name:
        raise ValueError(f"el ámbito {scope_type.value} necesita un nombre")
    if scope_type is ScopeType.OU:
        path = name.replace("\\", "/")
        return "/" + _MULTIPLE_SLASHES.sub("/", path).strip("/")
    return name.casefold()


PolicyKey = tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class Policy:
    """Una política aplicada a un ámbito concreto de un tenant."""

    policy_id: str
    name: str
    scope_type: ScopeType
    scope_name: str
    value: str
    tenant: str

    def __post_init__(self) -> None:
        if not self.policy_id:
            raise ValueError("el identificador de la política está vacío")
        if not self.name:
            raise ValueError("el nombre de la política está vacío")
        object.__setattr__(
            self,
            "scope_name",
            normalize_scope_name(self.scope_type, self.scope_name),
        )

    @property
    def key(self) -> PolicyKey:
        """Clave que identifica la política dentro de un tenant."""
        return (self.policy_id, self.scope_type.value, self.scope_name)


@dataclass(slots=True)
class PolicySet:
    """Colección de políticas de un tenant, indexada por política y ámbito."""

    tenant: str
    policies: dict[PolicyKey, Policy] = field(default_factory=dict)

    def add(self, policy: Policy) -> None:
        if policy.key in self.policies:
            raise DuplicatePolicyError(policy.key)
        self.policies[policy.key] = policy

    def __len__(self) -> int:
        return len(self.policies)

    def __iter__(self) -> Iterator[Policy]:
        return iter(self.policies.values())


@dataclass(frozen=True, slots=True)
class DiffEntry:
    """Diferencia de una política entre los dos tenants, con su impacto explicado."""

    policy_id: str
    policy_name: str
    scope_type: ScopeType
    scope_name: str
    old_value: str | None
    new_value: str | None
    impact: Impact
    reason: str

    @property
    def key(self) -> PolicyKey:
        return (self.policy_id, self.scope_type.value, self.scope_name)

    @property
    def changed(self) -> bool:
        if self.old_value is None or self.new_value is None:
            return True
        return normalize_value(self.old_value) != normalize_value(self.new_value)

    @property
    def scope_label(self) -> str:
        if self.scope_type is ScopeType.TENANT:
            return "Tenant"
        labels = {"ou": "OU", "group": "Grupo", "user": "Usuario"}
        return f"{labels[self.scope_type.value]}: {self.scope_name}"
