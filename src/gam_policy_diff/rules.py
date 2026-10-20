"""Reglas de clasificación de impacto.

La precedencia es explícita:

1. Si la política solo está en origen, el destino pierde una configuración:
   ``rompe_flujo``.
2. Si solo está en destino, hay una configuración nueva que revisar:
   ``requiere_formacion``.
3. Si el valor normalizado coincide, ``sin_impacto``.
4. Si existe una regla para el ``policy_id`` en ``DECISION_TABLE``, decide esa regla.
5. Si no existe, el cambio se marca como ``requiere_formacion`` y se explica que
   falta una regla específica.

Para añadir una política nueva basta con añadir una ``PolicyRule`` a
``DECISION_TABLE``. ``diff.py`` no cambia.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from .models import Impact
from .normalization import normalize_value

_REMOVED_REASON = (
    "La política está definida en origen y no en destino; "
    "el ámbito pierde una configuración que tenía."
)
_ADDED_REASON = (
    "La política está definida en destino y no en origen; hay que revisar la configuración nueva."
)
_EQUAL_REASON = "El valor efectivo es el mismo en origen y destino."
_UNKNOWN_REASON = (
    "No hay una regla específica para esta política; el valor cambia y conviene revisarlo."
)

_QUANTITY = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:d[ií]as?|days?|horas?|hours?|h|d)?",
    re.IGNORECASE,
)

_TRUE_VALUES = frozenset(
    {"true", "yes", "enabled", "activado", "activo", "si", "sí", "allow", "allowed", "on"}
)
_FALSE_VALUES = frozenset(
    {
        "false",
        "no",
        "disabled",
        "desactivado",
        "inactivo",
        "deny",
        "denied",
        "blocked",
        "off",
        "bloqueado",
    }
)

_SHARING_LEVELS = {
    "off": 0,
    "disabled": 0,
    "false": 0,
    "blocked": 0,
    "none": 0,
    "domain": 1,
    "internal": 1,
    "restricted": 1,
    "private": 1,
    "anyone_with_link": 2,
    "anyone": 2,
    "public": 2,
    "external": 2,
}

_POST_LEVELS = {
    "anyone": 0,
    "all": 0,
    "members": 1,
    "owners": 2,
    "managers": 2,
}


@dataclass(frozen=True, slots=True)
class Classification:
    """Resultado de clasificar un cambio."""

    impact: Impact
    reason: str


Classifier = Callable[[str, str], Classification | None]


@dataclass(frozen=True, slots=True)
class PolicyRule:
    """Regla específica para un ``policy_id``."""

    policy_id: str
    description: str
    classifier: Classifier


def _parse_quantity(raw: str) -> float | None:
    match = _QUANTITY.fullmatch(raw.strip())
    if match is None:
        return None
    return float(match.group(1).replace(",", "."))


def _format_number(value: float) -> str:
    return f"{value:g}"


def _as_bool(raw: str) -> bool | None:
    value = raw.strip().casefold()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    return None


def _classify_retention(old_value: str, new_value: str) -> Classification | None:
    old_days = _parse_quantity(old_value)
    new_days = _parse_quantity(new_value)
    if old_days is None or new_days is None:
        return None
    if new_days < old_days:
        return Classification(
            Impact.BREAKS_FLOW,
            f"La retención de correo baja de {_format_number(old_days)} a "
            f"{_format_number(new_days)} días; se pueden perder mensajes que antes se conservaban.",
        )
    if new_days > old_days:
        return Classification(
            Impact.NO_IMPACT,
            "La retención de correo aumenta; no se pierde ningún mensaje.",
        )
    return Classification(Impact.NO_IMPACT, "La retención efectiva no cambia.")


def _classify_session(old_value: str, new_value: str) -> Classification | None:
    old_hours = _parse_quantity(old_value)
    new_hours = _parse_quantity(new_value)
    if old_hours is None or new_hours is None:
        return None
    if new_hours < old_hours:
        if new_hours <= old_hours / 2:
            return Classification(
                Impact.BREAKS_FLOW,
                f"La sesión se reduce al menos a la mitad (de {_format_number(old_hours)} a "
                f"{_format_number(new_hours)} horas); los usuarios tendrán que identificarse "
                "con más frecuencia.",
            )
        return Classification(
            Impact.NEEDS_TRAINING,
            f"La sesión se acorta de {_format_number(old_hours)} a "
            f"{_format_number(new_hours)} horas; cambia la frecuencia con la que hay que "
            "identificarse.",
        )
    if new_hours > old_hours:
        return Classification(
            Impact.NO_IMPACT,
            "La sesión se alarga; no se impide ninguna tarea.",
        )
    return Classification(Impact.NO_IMPACT, "La duración efectiva de la sesión no cambia.")


def _classify_drive_sharing(old_value: str, new_value: str) -> Classification | None:
    old_level = _SHARING_LEVELS.get(normalize_value(old_value))
    new_level = _SHARING_LEVELS.get(normalize_value(new_value))
    if old_level is None or new_level is None:
        return None
    if new_level < old_level:
        return Classification(
            Impact.BREAKS_FLOW,
            f"Se restringe la compartición externa en Drive (de {old_value} a {new_value}); "
            "los enlaces públicos existentes pueden dejar de funcionar.",
        )
    if new_level > old_level:
        return Classification(
            Impact.NEEDS_TRAINING,
            f"Se amplía la compartición externa en Drive (de {old_value} a {new_value}); "
            "hay que revisar los enlaces y permisos.",
        )
    return Classification(
        Impact.NO_IMPACT,
        "El nivel efectivo de compartición externa no cambia.",
    )


def _classify_default_sharing(old_value: str, new_value: str) -> Classification:
    return Classification(
        Impact.NEEDS_TRAINING,
        f"Cambia la compartición predeterminada en Drive (de {old_value} a {new_value}); "
        "los usuarios deben saber con qué permisos se crean los archivos nuevos.",
    )


def _classify_two_step(old_value: str, new_value: str) -> Classification | None:
    old_required = _as_bool(old_value)
    new_required = _as_bool(new_value)
    if old_required is None or new_required is None:
        return None
    if new_required and not old_required:
        return Classification(
            Impact.NEEDS_TRAINING,
            "Se exige la verificación en dos pasos; los usuarios que aún no la tengan "
            "deberán inscribirse.",
        )
    if old_required and not new_required:
        return Classification(
            Impact.NO_IMPACT,
            "Deja de exigirse la verificación en dos pasos; no se impide ninguna tarea.",
        )
    return Classification(
        Impact.NO_IMPACT,
        "La exigencia efectiva de verificación en dos pasos no cambia.",
    )


def _classify_calendar_invites(old_value: str, new_value: str) -> Classification:
    return Classification(
        Impact.NEEDS_TRAINING,
        f"Cambia la política de invitaciones externas de calendario "
        f"(de {old_value} a {new_value}); los usuarios deben conocer el nuevo comportamiento.",
    )


def _classify_calendar_view(old_value: str, new_value: str) -> Classification:
    return Classification(
        Impact.NO_IMPACT,
        f"Cambia la vista predeterminada del calendario (de {old_value} a {new_value}); "
        "no se impide ninguna tarea.",
    )


def _classify_forwarding(old_value: str, new_value: str) -> Classification | None:
    old_allowed = _as_bool(old_value)
    new_allowed = _as_bool(new_value)
    if old_allowed is None or new_allowed is None:
        return None
    if old_allowed and not new_allowed:
        return Classification(
            Impact.BREAKS_FLOW,
            "Se bloquea el reenvío automático externo; los usuarios que lo usaban dejarán "
            "de recibir esos correos.",
        )
    if new_allowed and not old_allowed:
        return Classification(
            Impact.NEEDS_TRAINING,
            "Se permite el reenvío automático externo; conviene explicar cómo funciona y sus "
            "riesgos.",
        )
    return Classification(
        Impact.NO_IMPACT,
        "La configuración efectiva del reenvío externo no cambia.",
    )


def _classify_alias(old_value: str, new_value: str) -> Classification:
    return Classification(
        Impact.NEEDS_TRAINING,
        f"Cambia el dominio de alias (de {old_value} a {new_value}); los usuarios y sus "
        "contactos deben conocer el nuevo nombre.",
    )


def _classify_group_join(old_value: str, new_value: str) -> Classification:
    return Classification(
        Impact.NEEDS_TRAINING,
        f"Cambia quién puede unirse al grupo (de {old_value} a {new_value}); los nuevos "
        "miembros deben conocer el requisito.",
    )


def _classify_group_discovery(old_value: str, new_value: str) -> Classification:
    return Classification(
        Impact.NO_IMPACT,
        f"Cambia la visibilidad del grupo en el directorio (de {old_value} a {new_value}); "
        "no se impide ninguna tarea.",
    )


def _classify_external_members(old_value: str, new_value: str) -> Classification | None:
    old_allowed = _as_bool(old_value)
    new_allowed = _as_bool(new_value)
    if old_allowed is None or new_allowed is None:
        return None
    if old_allowed and not new_allowed:
        return Classification(
            Impact.BREAKS_FLOW,
            "Se prohíben los miembros externos del grupo; los miembros externos actuales "
            "pueden perder el acceso.",
        )
    if new_allowed and not old_allowed:
        return Classification(
            Impact.NEEDS_TRAINING,
            "Se permiten miembros externos en el grupo; hay que revisar quién puede entrar.",
        )
    return Classification(
        Impact.NO_IMPACT,
        "La configuración efectiva de miembros externos no cambia.",
    )


def _classify_group_posting(old_value: str, new_value: str) -> Classification | None:
    old_level = _POST_LEVELS.get(normalize_value(old_value))
    new_level = _POST_LEVELS.get(normalize_value(new_value))
    if old_level is None or new_level is None:
        return None
    if new_level > old_level:
        return Classification(
            Impact.BREAKS_FLOW,
            f"Se restringe quién puede publicar en el grupo (de {old_value} a {new_value}); "
            "algunos miembros pierden una capacidad.",
        )
    if new_level < old_level:
        return Classification(
            Impact.NEEDS_TRAINING,
            f"Se amplía quién puede publicar en el grupo (de {old_value} a {new_value}); "
            "cambia el comportamiento del grupo.",
        )
    return Classification(
        Impact.NO_IMPACT,
        "El nivel efectivo de publicación en el grupo no cambia.",
    )


def _classify_contact_sharing(old_value: str, new_value: str) -> Classification:
    return Classification(
        Impact.NEEDS_TRAINING,
        f"Cambia la compartición de contactos del directorio (de {old_value} a {new_value}); "
        "los usuarios deben conocer el nuevo alcance.",
    )


DECISION_TABLE: tuple[PolicyRule, ...] = (
    PolicyRule(
        "mail_retention_days",
        "Bajar la retención rompe; subirla no tiene impacto.",
        _classify_retention,
    ),
    PolicyRule(
        "session_length_hours",
        "Reducir la sesión a la mitad o menos rompe; el resto de cambios exige formación "
        "o no impacta.",
        _classify_session,
    ),
    PolicyRule(
        "drive_sharing_external",
        "Cerrar el nivel de compartición rompe; abrirlo requiere formación.",
        _classify_drive_sharing,
    ),
    PolicyRule(
        "drive_default_sharing",
        "Cualquier cambio requiere formación.",
        _classify_default_sharing,
    ),
    PolicyRule(
        "enforce_2sv",
        "Activar la exigencia requiere formación; desactivarla no impacta.",
        _classify_two_step,
    ),
    PolicyRule(
        "calendar_external_invites",
        "Cualquier cambio requiere formación.",
        _classify_calendar_invites,
    ),
    PolicyRule(
        "calendar_default_view",
        "Cualquier cambio es sin impacto.",
        _classify_calendar_view,
    ),
    PolicyRule(
        "mail_forwarding_external",
        "Cerrar el reenvío rompe; abrirlo requiere formación.",
        _classify_forwarding,
    ),
    PolicyRule(
        "alias_domain",
        "Cualquier cambio requiere formación.",
        _classify_alias,
    ),
    PolicyRule(
        "group_who_can_join",
        "Cualquier cambio requiere formación.",
        _classify_group_join,
    ),
    PolicyRule(
        "group_discovery",
        "Cualquier cambio es sin impacto.",
        _classify_group_discovery,
    ),
    PolicyRule(
        "group_external_members",
        "Prohibir miembros externos rompe; permitirlos requiere formación.",
        _classify_external_members,
    ),
    PolicyRule(
        "group_who_can_post",
        "Restringir quién publica rompe; ampliarlo requiere formación.",
        _classify_group_posting,
    ),
    PolicyRule(
        "directory_contact_sharing",
        "Cualquier cambio requiere formación.",
        _classify_contact_sharing,
    ),
)

_RULES_BY_POLICY: dict[str, PolicyRule] = {rule.policy_id: rule for rule in DECISION_TABLE}


def classify_change(
    policy_id: str,
    old_value: str | None,
    new_value: str | None,
) -> Classification:
    """Clasifica un cambio aplicando la precedencia documentada en el módulo."""
    if old_value is None:
        return Classification(Impact.NEEDS_TRAINING, _ADDED_REASON)
    if new_value is None:
        return Classification(Impact.BREAKS_FLOW, _REMOVED_REASON)
    if normalize_value(old_value) == normalize_value(new_value):
        return Classification(Impact.NO_IMPACT, _EQUAL_REASON)
    rule = _RULES_BY_POLICY.get(policy_id)
    if rule is not None:
        classification = rule.classifier(old_value, new_value)
        if classification is not None:
            return classification
    return Classification(Impact.NEEDS_TRAINING, _UNKNOWN_REASON)
