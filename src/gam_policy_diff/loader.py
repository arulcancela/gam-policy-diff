"""Lectura de exportaciones de GAM en CSV o JSON."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from .errors import DuplicatePolicyError, InputError
from .models import Policy, PolicySet, ScopeType
from .normalization import normalize_header, normalize_identifier

REQUIRED_COLUMNS = ("policy_id", "scope_type", "scope_name", "value")

COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "policy_id": ("policy_id", "policy", "id", "id_politica", "politica_id"),
    "policy_name": ("policy_name", "name", "nombre", "nombre_politica"),
    "scope_type": ("scope_type", "tipo_ambito", "tipo_de_ambito", "scope"),
    "scope_name": ("scope_name", "nombre_ambito", "ambito", "ou", "grupo", "group"),
    "value": ("value", "valor", "setting", "configuracion"),
    "tenant": ("tenant", "cliente", "inquilino"),
}


def load_policy_set(
    path: str | Path,
    column_map: Mapping[str, str] | None = None,
) -> PolicySet:
    """Carga un fichero de políticas y lo devuelve indexado por política y ámbito."""
    file_path = Path(path)
    text = _read_text(file_path)
    if not text.strip():
        raise InputError(f"el fichero {file_path} está vacío")
    if _looks_like_json(text):
        headers, rows, top_tenant = _read_json(text, file_path)
    else:
        headers, rows = _read_csv(text, file_path)
        top_tenant = None
    columns = resolve_columns(headers, column_map)
    return _build_policy_set(rows, columns, top_tenant, file_path)


def parse_column_map(raw: str) -> dict[str, str]:
    """Convierte `campo=columna,...` o un fichero JSON en un mapeo de columnas."""
    if not raw.strip():
        raise InputError("el mapeo de columnas está vacío")
    candidate = Path(raw)
    try:
        is_file = candidate.is_file()
    except OSError:
        is_file = False
    if is_file:
        return _read_mapping_file(candidate)
    if "=" not in raw:
        raise InputError(
            f"no encuentro el fichero de mapeo {raw!r}; para indicar columnas usa campo=columna"
        )
    mapping: dict[str, str] = {}
    for part in raw.split(","):
        field, separator, column = part.partition("=")
        if not separator or not field.strip() or not column.strip():
            raise InputError(f"mapeo no válido: {part!r}; usa el formato campo=columna")
        mapping[field.strip()] = column.strip()
    return mapping


def resolve_columns(
    headers: list[str],
    overrides: Mapping[str, str] | None = None,
) -> dict[str, str | None]:
    """Resuelve las columnas del fichero contra los nombres canónicos."""
    available = _index_headers(headers)
    if overrides:
        unknown = sorted(set(overrides) - set(COLUMN_ALIASES))
        if unknown:
            allowed = ", ".join(COLUMN_ALIASES)
            raise InputError(
                "campos de mapeo desconocidos: "
                + ", ".join(unknown)
                + f"; valores admitidos: {allowed}"
            )
    resolved = {
        field: _resolve_column(field, aliases, available, overrides)
        for field, aliases in COLUMN_ALIASES.items()
    }
    missing = [field for field in REQUIRED_COLUMNS if resolved[field] is None]
    if missing:
        raise InputError(
            "faltan columnas obligatorias: "
            + ", ".join(missing)
            + ". Columnas encontradas: "
            + ", ".join(headers)
            + ". Usa --map campo=columna o un fichero de mapeo"
        )
    return resolved


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise InputError(f"no encuentro el fichero {path}") from None
    except IsADirectoryError:
        raise InputError(f"{path} es un directorio, no un fichero") from None
    except UnicodeDecodeError:
        raise InputError(f"el fichero {path} no está codificado en UTF-8") from None
    except OSError as exc:
        reason = exc.strerror or str(exc)
        raise InputError(f"no puedo leer {path}: {reason}") from None


def _looks_like_json(text: str) -> bool:
    return text.lstrip().startswith(("{", "["))


def _read_json(
    text: str,
    path: Path,
) -> tuple[list[str], list[tuple[int, dict[str, str]]], str | None]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputError(
            f"{path.name} no es un JSON válido (línea {exc.lineno}, columna {exc.colno})"
        ) from None
    top_tenant = None
    if isinstance(payload, dict):
        if "policies" not in payload:
            raise InputError(
                f"{path.name}: el JSON debe ser una lista o un objeto con la clave 'policies'"
            )
        top_tenant = _json_scalar(payload.get("tenant"), path.name, "tenant")
        payload = payload["policies"]
    if not isinstance(payload, list):
        raise InputError(f"{path.name}: la clave 'policies' debe contener una lista")
    if not payload:
        raise InputError(f"{path.name} no contiene políticas")
    headers: list[str] = []
    rows: list[tuple[int, dict[str, str]]] = []
    for position, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise InputError(f"{path.name}: el elemento {position} no es un objeto")
        row = {
            str(key): _json_scalar(value, path.name, f"elemento {position}, campo {key!r}")
            for key, value in item.items()
        }
        _extend_unique(headers, row)
        rows.append((position, row))
    return headers, rows, top_tenant


def _read_csv(
    text: str,
    path: Path,
) -> tuple[list[str], list[tuple[int, dict[str, str]]]]:
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=_detect_delimiter(text))
    headers = _read_header(reader, path)
    rows: list[tuple[int, dict[str, str]]] = []
    for row in reader:
        line_number = reader.line_num
        if not any(cell.strip() for cell in row):
            continue
        if len(row) > len(headers):
            raise InputError(
                f"{path.name}, línea {line_number}: hay más columnas que en la cabecera"
            )
        padded = [*row, *([""] * (len(headers) - len(row)))]
        rows.append((line_number, dict(zip(headers, padded, strict=True))))
    if not rows:
        raise InputError(f"{path.name} no contiene políticas")
    return headers, rows


def _read_header(reader: Iterator[list[str]], path: Path) -> list[str]:
    for row in reader:
        if not any(cell.strip() for cell in row):
            continue
        headers = [cell.strip() for cell in row]
        if any(not cell for cell in headers):
            raise InputError(f"{path.name}, línea {reader.line_num}: hay una columna sin nombre")
        return headers
    raise InputError(f"{path.name} no tiene cabecera")


def _detect_delimiter(text: str) -> str:
    try:
        return csv.Sniffer().sniff(text[:4096], delimiters=",;\t").delimiter
    except csv.Error:
        return ","


def _index_headers(headers: list[str]) -> dict[str, str]:
    available: dict[str, str] = {}
    for header in headers:
        if not header.strip():
            raise InputError("hay una columna sin nombre")
        key = normalize_header(header)
        if key in available:
            raise InputError(
                f"las columnas {available[key]!r} y {header!r} son ambiguas; renombra una"
            )
        available[key] = header
    return available


def _resolve_column(
    field: str,
    aliases: tuple[str, ...],
    available: dict[str, str],
    overrides: Mapping[str, str] | None,
) -> str | None:
    if overrides and field in overrides:
        requested = overrides[field]
        source = available.get(normalize_header(requested))
        if source is None:
            raise InputError(f"la columna {requested!r} indicada para {field!r} no existe")
        return source
    for alias in aliases:
        source = available.get(normalize_header(alias))
        if source is not None:
            return source
    return None


def _extend_unique(headers: list[str], row: dict[str, str]) -> None:
    for key in row:
        if key not in headers:
            headers.append(key)


def _json_scalar(value: Any, filename: str, context: str) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        return str(value).strip()
    raise InputError(f"{filename}: {context} debe ser un valor simple, no una lista u objeto")


def _read_mapping_file(path: Path) -> dict[str, str]:
    text = _read_text(path)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputError(
            f"{path} no es un JSON válido (línea {exc.lineno}, columna {exc.colno})"
        ) from None
    if not isinstance(payload, dict):
        raise InputError(f"{path} debe contener un objeto JSON con el mapeo")
    mapping: dict[str, str] = {}
    for field, column in payload.items():
        if not isinstance(field, str) or not isinstance(column, str):
            raise InputError(f"{path}: el mapeo debe usar cadenas de texto")
        mapping[field.strip()] = column.strip()
    if not mapping:
        raise InputError(f"{path} no contiene ningún mapeo")
    return mapping


def _build_policy_set(
    rows: list[tuple[int, dict[str, str]]],
    columns: dict[str, str | None],
    top_tenant: str | None,
    path: Path,
) -> PolicySet:
    tenant = _resolve_tenant(rows, columns["tenant"], top_tenant, path)
    policy_set = PolicySet(tenant=tenant)
    first_lines: dict[tuple[str, str, str], int] = {}
    for line_number, record in rows:
        policy = _build_policy(record, columns, tenant, line_number)
        try:
            policy_set.add(policy)
        except DuplicatePolicyError:
            first = first_lines[policy.key]
            raise InputError(
                f"línea {line_number}: la política {policy.policy_id!r} en "
                f"{policy.scope_type.value} {policy.scope_name!r} ya aparece en la línea {first}"
            ) from None
        first_lines[policy.key] = line_number
    return policy_set


def _resolve_tenant(
    rows: list[tuple[int, dict[str, str]]],
    tenant_column: str | None,
    top_tenant: str | None,
    path: Path,
) -> str:
    labels = {top_tenant} if top_tenant else set()
    for _, record in rows:
        label = _field(record, tenant_column)
        if label:
            labels.add(label)
    if len(labels) > 1:
        raise InputError(f"{path.name} contiene varios tenants: " + ", ".join(sorted(labels)))
    return next(iter(labels), path.stem)


def _build_policy(
    record: dict[str, str],
    columns: dict[str, str | None],
    tenant: str,
    line_number: int,
) -> Policy:
    policy_id = normalize_identifier(_field(record, columns["policy_id"]))
    if not policy_id:
        raise InputError(f"línea {line_number}: el identificador de la política está vacío")
    try:
        scope_type = ScopeType.parse(_field(record, columns["scope_type"]))
    except ValueError as exc:
        raise InputError(f"línea {line_number}: {exc}") from None
    value = _field(record, columns["value"])
    if not value:
        raise InputError(f"línea {line_number}: la política {policy_id!r} no tiene valor")
    name = _field(record, columns["policy_name"]) or policy_id
    try:
        return Policy(
            policy_id=policy_id,
            name=name,
            scope_type=scope_type,
            scope_name=_field(record, columns["scope_name"]),
            value=value,
            tenant=tenant,
        )
    except ValueError as exc:
        raise InputError(f"línea {line_number}: {exc}") from None


def _field(record: dict[str, str], column: str | None) -> str:
    if column is None:
        return ""
    return record.get(column, "").strip()
