"""Interfaz de línea de comandos."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from .diff import compare_policy_sets
from .errors import InputError, OutputError
from .loader import load_policy_set, parse_column_map
from .models import IMPACT_ORDER
from .report import write_reports


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise InputError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="gam-policy-diff",
        description="Compara dos exportaciones de políticas de Google Workspace.",
    )
    parser.add_argument(
        "--old",
        metavar="FICHERO",
        help="exportación del tenant de origen (CSV, JSON o XLSX de GAM)",
    )
    parser.add_argument(
        "--new",
        metavar="FICHERO",
        help="exportación del tenant de destino (CSV, JSON o XLSX de GAM)",
    )
    parser.add_argument(
        "--map",
        metavar="MAPEO",
        help="mapeo de columnas para CSV/JSON: campo=columna separado por comas, o fichero JSON",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="usa los fixtures incluidos en el repositorio",
    )
    parser.add_argument(
        "--changes-only",
        action="store_true",
        help="incluye solo las políticas con cambios efectivos entre origen y destino",
    )
    parser.add_argument(
        "--out",
        metavar="FICHERO",
        default="report.html",
        help="ruta del informe HTML; el JSON se escribe al lado (por defecto: report.html)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        old_path, new_path = _resolve_inputs(args)
        column_map = parse_column_map(args.map) if args.map else None
        old_set = load_policy_set(old_path, column_map)
        new_set = load_policy_set(new_path, column_map)
        entries = compare_policy_sets(old_set, new_set)
    except InputError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Origen: {old_set.tenant} ({len(old_set)} políticas)")
    print(f"Destino: {new_set.tenant} ({len(new_set)} políticas)")
    if not any(entry.changed for entry in entries):
        print("No hay diferencias entre los tenants.")
        return 2
    if args.changes_only:
        entries = [entry for entry in entries if entry.changed]
    counts = Counter(entry.impact for entry in entries)
    for impact in IMPACT_ORDER:
        print(f"{impact.label}: {counts[impact]}")
    try:
        html_path, json_path = write_reports(
            entries,
            old_tenant=old_set.tenant,
            new_tenant=new_set.tenant,
            html_path=args.out,
            changes_only=args.changes_only,
        )
    except OutputError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Informe HTML: {html_path}")
    print(f"Datos JSON: {json_path}")
    return 0


def _resolve_inputs(args: argparse.Namespace) -> tuple[Path, Path]:
    if args.demo:
        if args.old or args.new:
            raise InputError("--demo no se combina con --old ni con --new")
        return _demo_paths()
    if not args.old or not args.new:
        raise InputError("indica --old y --new, o usa --demo")
    return Path(args.old), Path(args.new)


def _demo_paths() -> tuple[Path, Path]:
    repository = Path(__file__).resolve().parents[2]
    candidates = [repository / "fixtures", Path.cwd() / "fixtures"]
    for directory in candidates:
        old = directory / "tenant-origen.csv"
        new = directory / "tenant-destino.csv"
        if old.is_file() and new.is_file():
            return old, new
    raise InputError(
        "no encuentro los fixtures de demostración; ejecuta --demo desde el repositorio"
    )
