"""Adaptador para exportaciones XLSX de GAM Policy API.

La exportación es ancha: cada fila es un ajuste y el valor está en una columna
``setting.value.*`` distinta. Este adaptador convierte solo los ajustes con un
mapeo explícito al modelo normalizado de la herramienta. El resto se ignora.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from .errors import DuplicatePolicyError, InputError
from .models import Policy, PolicySet, ScopeType

_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_NS = {"m": _MAIN_NS}

_REQUIRED_HEADERS = (
    "setting.type",
    "policyQuery.orgUnitPath",
    "policyQuery.groupEmail",
)

_SECONDS = re.compile(r"^(\d+(?:[.,]\d+)?)s$", re.IGNORECASE)
_HOURS = re.compile(r"^(\d+(?:[.,]\d+)?)h$", re.IGNORECASE)
_ISO_DURATION = re.compile(
    r"^PT(?:(\d+(?:[.,]\d+)?)H)?(?:(\d+(?:[.,]\d+)?)M)?(?:(\d+(?:[.,]\d+)?)S)?$",
    re.IGNORECASE,
)

_DRIVE_OFF = frozenset({"BLOCKED", "DISABLED", "OFF", "NO_ONE", "NONE"})
_DRIVE_ANYONE = frozenset({"ALL_ELIGIBLE_USERS", "ANYONE", "PUBLIC"})
_DRIVE_DOMAIN = frozenset({"DOMAIN", "ALL_ELIGIBLE_USERS_IN_DOMAIN", "INTERNAL"})


@dataclass(frozen=True, slots=True)
class GamMapping:
    """Ajuste de GAM que se traduce a una política normalizada."""

    setting_type: str
    policy_id: str
    policy_name: str
    extract: Callable[[Mapping[str, str]], str | None]


def _field(record: Mapping[str, str], name: str) -> str:
    return record.get(name, "").strip()


def _format_number(value: float) -> str:
    return f"{value:g}"


def _extract_session(record: Mapping[str, str]) -> str | None:
    raw = _field(record, "setting.value.webSessionDuration")
    if not raw:
        return None
    seconds = _SECONDS.fullmatch(raw)
    if seconds:
        return _format_number(float(seconds.group(1).replace(",", ".")) / 3600)
    hours = _HOURS.fullmatch(raw)
    if hours:
        return _format_number(float(hours.group(1).replace(",", ".")))
    iso = _ISO_DURATION.fullmatch(raw)
    if iso:
        total = 0.0
        for group, multiplier in zip(iso.groups(), (3600, 60, 1), strict=True):
            if group:
                total += float(group.replace(",", ".")) * multiplier
        return _format_number(total / 3600)
    return None


def _extract_forwarding(record: Mapping[str, str]) -> str | None:
    value = _field(record, "setting.value.enableAutoForwarding").casefold()
    if value in {"true", "allow", "allowed", "enabled"}:
        return "allow"
    if value in {"false", "deny", "denied", "disabled"}:
        return "deny"
    return None


def _extract_two_step(record: Mapping[str, str]) -> str | None:
    value = _field(record, "setting.value.enforcedFrom")
    if not value:
        return None
    return "false" if value.startswith("1970-01-01") else "true"


def _extract_drive_sharing(record: Mapping[str, str]) -> str | None:
    mode = _field(record, "setting.value.externalSharingMode").upper()
    parties = _field(record, "setting.value.allowedPartiesForDistributingContent").upper()
    if mode in _DRIVE_OFF or parties in _DRIVE_OFF:
        return "off"
    if parties in _DRIVE_ANYONE:
        return "anyone_with_link"
    if parties in _DRIVE_DOMAIN:
        return "domain"
    return None


GAM_POLICY_MAPPINGS: tuple[GamMapping, ...] = (
    GamMapping(
        setting_type="settings/security.session_controls",
        policy_id="session_length_hours",
        policy_name="Duración de la sesión (horas)",
        extract=_extract_session,
    ),
    GamMapping(
        setting_type="settings/gmail.auto_forwarding",
        policy_id="mail_forwarding_external",
        policy_name="Reenvío automático externo",
        extract=_extract_forwarding,
    ),
    GamMapping(
        setting_type="settings/security.two_step_verification_enforcement",
        policy_id="enforce_2sv",
        policy_name="Exigir verificación en dos pasos",
        extract=_extract_two_step,
    ),
    GamMapping(
        setting_type="settings/drive_and_docs.external_sharing",
        policy_id="drive_sharing_external",
        policy_name="Compartición externa en Drive",
        extract=_extract_drive_sharing,
    ),
)

_MAPPINGS_BY_TYPE: dict[str, GamMapping] = {
    mapping.setting_type: mapping for mapping in GAM_POLICY_MAPPINGS
}


def load_gam_policy_export(path: str | Path) -> PolicySet:
    """Carga un XLSX de GAM y devuelve solo los ajustes con mapeo explícito."""
    file_path = Path(path)
    headers, records = _read_rows(file_path)
    _validate_headers(headers)
    policy_set = PolicySet(tenant=file_path.stem)
    for record in records:
        mapping = _MAPPINGS_BY_TYPE.get(_field(record, "setting.type"))
        if mapping is None:
            continue
        value = mapping.extract(record)
        if value is None:
            continue
        scope_type, scope_name = _scope(record)
        policy = Policy(
            policy_id=mapping.policy_id,
            name=mapping.policy_name,
            scope_type=scope_type,
            scope_name=scope_name,
            value=value,
            tenant=file_path.stem,
        )
        try:
            policy_set.add(policy)
        except DuplicatePolicyError:
            existing = policy_set.policies[policy.key]
            if existing.value == policy.value:
                continue
            raise InputError(
                f"el XLSX repite la política {policy.policy_id!r} en "
                f"{policy.scope_type.value} {policy.scope_name!r} con valores distintos"
            ) from None
    if not len(policy_set):
        raise InputError(
            "el XLSX no contiene políticas de los tipos soportados: "
            + ", ".join(mapping.setting_type for mapping in GAM_POLICY_MAPPINGS)
        )
    return policy_set


def _validate_headers(headers: list[str]) -> None:
    missing = [header for header in _REQUIRED_HEADERS if header not in headers]
    if missing:
        raise InputError(
            "faltan columnas en el XLSX de GAM: "
            + ", ".join(missing)
            + ". Se esperaba una exportación de policyQuery con setting.type y ámbito."
        )


def _scope(record: Mapping[str, str]) -> tuple[ScopeType, str]:
    group = _field(record, "policyQuery.groupEmail")
    if group:
        return ScopeType.GROUP, group
    path = _field(record, "policyQuery.orgUnitPath")
    if path in {"", "/"}:
        return ScopeType.TENANT, ""
    return ScopeType.OU, path


def _read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    try:
        with ZipFile(path) as archive:
            shared = _read_shared_strings(archive)
            sheet_path = _sheet_path(archive)
            sheet_xml = archive.read(sheet_path)
        return _parse_sheet(sheet_xml, shared, path)
    except FileNotFoundError:
        raise InputError(f"no encuentro el fichero {path}") from None
    except BadZipFile:
        raise InputError(f"{path} no es un XLSX válido") from None
    except KeyError:
        raise InputError(f"{path} no tiene la estructura de un XLSX de GAM") from None
    except ET.ParseError:
        raise InputError(f"{path} contiene XML no válido") from None
    except OSError as exc:
        reason = exc.strerror or str(exc)
        raise InputError(f"no puedo leer {path}: {reason}") from None


def _sheet_path(archive: ZipFile) -> str:
    try:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        sheet = workbook.find("m:sheets/m:sheet", _NS)
        rel_id = sheet.get(f"{{{_REL_NS}}}id") if sheet is not None else None
        if rel_id:
            rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            for relationship in rels.findall(f"{{{_PKG_REL_NS}}}Relationship"):
                if relationship.get("Id") == rel_id:
                    return _resolve_target(relationship.get("Target", ""))
    except KeyError:
        pass
    candidates = sorted(
        name for name in archive.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)
    )
    if not candidates:
        raise InputError("el XLSX no contiene ninguna hoja de cálculo")
    return candidates[0]


def _resolve_target(target: str) -> str:
    target = target.lstrip("/")
    if target.startswith("xl/"):
        return target
    return posixpath.normpath(posixpath.join("xl", target))


def _read_shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(text.text or "" for text in item.iter(f"{{{_MAIN_NS}}}t"))
        for item in root.findall(f"{{{_MAIN_NS}}}si")
    ]


def _parse_sheet(
    sheet_xml: bytes,
    shared: list[str],
    path: Path,
) -> tuple[list[str], list[dict[str, str]]]:
    root = ET.fromstring(sheet_xml)
    sheet_data = root.find(f"{{{_MAIN_NS}}}sheetData")
    if sheet_data is None:
        raise InputError(f"{path} no contiene datos")
    raw_rows: list[dict[str, str]] = []
    for row in sheet_data.findall(f"{{{_MAIN_NS}}}row"):
        cells: dict[str, str] = {}
        for cell in row.findall(f"{{{_MAIN_NS}}}c"):
            column = _column_letters(cell.get("r", ""))
            value = _cell_value(cell, shared)
            if column and value:
                cells[column] = value
        if cells:
            raw_rows.append(cells)
    if not raw_rows:
        raise InputError(f"{path} no contiene datos")
    header_by_column = raw_rows[0]
    headers = list(header_by_column.values())
    records = [
        {
            header_by_column[column]: value
            for column, value in cells.items()
            if column in header_by_column
        }
        for cells in raw_rows[1:]
    ]
    return headers, records


def _cell_value(cell: ET.Element, shared: list[str]) -> str:
    cell_type = cell.get("t")
    value = cell.find(f"{{{_MAIN_NS}}}v")
    if cell_type == "s":
        if value is None or value.text is None:
            return ""
        try:
            return shared[int(value.text)].strip()
        except (ValueError, IndexError):
            raise InputError("el XLSX tiene una referencia de texto no válida") from None
    if cell_type == "inlineStr":
        return "".join(text.text or "" for text in cell.iter(f"{{{_MAIN_NS}}}t")).strip()
    if cell_type == "b":
        return "TRUE" if value is not None and value.text == "1" else "FALSE"
    return (value.text or "").strip() if value is not None else ""


def _column_letters(reference: str) -> str:
    match = re.match(r"([A-Z]+)", reference)
    return match.group(1) if match else ""
