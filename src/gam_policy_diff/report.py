"""Generación del informe HTML autocontenido y del JSON."""

from __future__ import annotations

import html
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from string import Template

from .errors import OutputError
from .models import IMPACT_ORDER, DiffEntry, Impact, ScopeType

REPORT_NOTE = (
    "Informe generado a partir de exportaciones de GAM. No contiene datos de usuarios finales"
)

CUBE_DESCRIPTIONS: dict[Impact, str] = {
    Impact.BREAKS_FLOW: "Cambios que impiden hacer algo que se hacía antes.",
    Impact.NEEDS_TRAINING: "Cambios que alteran el comportamiento sin bloquearlo.",
    Impact.NO_IMPACT: "Mismo valor o cambios que no afectan al usuario final.",
}

_SCOPE_ORDER: dict[ScopeType, int] = {
    ScopeType.TENANT: 0,
    ScopeType.OU: 1,
    ScopeType.GROUP: 2,
    ScopeType.USER: 3,
}
_IMPACT_INDEX = {impact: index for index, impact in enumerate(IMPACT_ORDER)}


def render_html(
    entries: Sequence[DiffEntry],
    *,
    old_tenant: str,
    new_tenant: str,
    generated_on: date,
) -> str:
    """Genera el documento HTML completo, sin recursos externos."""
    entries = list(entries)
    counts = Counter(entry.impact for entry in entries)
    title = f"Informe de políticas: {old_tenant} a {new_tenant}"
    return _HTML_DOCUMENT.substitute(
        css=_CSS,
        title=_escape(title),
        header=_render_header(
            old_tenant=old_tenant,
            new_tenant=new_tenant,
            generated_on=generated_on,
            total=len(entries),
            changed=sum(entry.changed for entry in entries),
            counts=counts,
        ),
        blocks="\n".join(_render_block(impact, entries) for impact in IMPACT_ORDER),
        note=REPORT_NOTE,
    )


def render_json(
    entries: Sequence[DiffEntry],
    *,
    old_tenant: str,
    new_tenant: str,
    generated_on: date,
) -> str:
    """Genera el JSON con la misma información que el informe."""
    payload = _json_payload(
        entries,
        old_tenant=old_tenant,
        new_tenant=new_tenant,
        generated_on=generated_on,
    )
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def write_reports(
    entries: Sequence[DiffEntry],
    *,
    old_tenant: str,
    new_tenant: str,
    html_path: str | Path,
    generated_on: date | None = None,
) -> tuple[Path, Path]:
    """Escribe el HTML y el JSON hermano; devuelve las dos rutas."""
    destination = Path(html_path)
    if destination.suffix.lower() not in {".html", ".htm"}:
        raise OutputError("la salida del informe debe terminar en .html o .htm")
    report_date = generated_on if generated_on is not None else date.today()
    json_path = destination.with_suffix(".json")
    _write_text(
        destination,
        render_html(
            entries,
            old_tenant=old_tenant,
            new_tenant=new_tenant,
            generated_on=report_date,
        ),
    )
    _write_text(
        json_path,
        render_json(
            entries,
            old_tenant=old_tenant,
            new_tenant=new_tenant,
            generated_on=report_date,
        ),
    )
    return destination, json_path


def _render_header(
    *,
    old_tenant: str,
    new_tenant: str,
    generated_on: date,
    total: int,
    changed: int,
    counts: Mapping[Impact, int],
) -> str:
    links = "".join(
        f'<a class="cube-link cube-{impact.value}" href="#bloque-{impact.value}">'
        f'{_escape(impact.label)}<span class="count">{counts[impact]}</span></a>'
        for impact in IMPACT_ORDER
    )
    return f"""
    <header class="report-header">
      <p class="kicker">Google Workspace · migración de tenant</p>
      <h1>Informe de diferencias de políticas</h1>
      <p class="tenants">
        <span class="tenant-label">Origen</span> <strong>{_escape(old_tenant)}</strong>
        <span class="arrow" aria-hidden="true">→</span>
        <span class="tenant-label">Destino</span> <strong>{_escape(new_tenant)}</strong>
      </p>
      <dl class="facts">
        <div><dt>Fecha</dt><dd>{generated_on:%d/%m/%Y}</dd></div>
        <div><dt>Políticas comparadas</dt><dd>{total}</dd></div>
        <div><dt>Cambios</dt><dd>{changed}</dd></div>
      </dl>
      <nav class="cube-nav no-print" aria-label="Resumen por impacto">{links}</nav>
    </header>
"""


def _render_block(impact: Impact, entries: Sequence[DiffEntry]) -> str:
    block_entries = [entry for entry in entries if entry.impact is impact]
    groups = _group_by_scope(block_entries)
    if groups:
        body = _render_scope_nav(groups, impact)
        body += "".join(
            _render_scope_group(group, index, impact) for index, group in enumerate(groups, start=1)
        )
    else:
        body = '<p class="empty">No hay políticas en este cubo.</p>'
    return f"""
      <details class="block block-{impact.value}" id="bloque-{impact.value}" open>
        <summary>
          <h2 class="block-title">{_escape(impact.label)}</h2>
          <span class="block-count">{len(block_entries)}</span>
        </summary>
        <p class="block-note">{_escape(CUBE_DESCRIPTIONS[impact])}</p>
        {body}
      </details>
"""


def _render_scope_nav(groups: Sequence[Sequence[DiffEntry]], impact: Impact) -> str:
    links = "".join(
        f'<a href="#bloque-{impact.value}-ambito-{index}">'
        f"{_escape(group[0].scope_label)} ({len(group)})</a>"
        for index, group in enumerate(groups, start=1)
    )
    return (
        f'<nav class="scope-nav no-print" aria-label="Ámbitos de {_escape(impact.label)}">'
        f"<span>Ámbitos:</span>{links}</nav>"
    )


def _render_scope_group(group: Sequence[DiffEntry], index: int, impact: Impact) -> str:
    anchor = f"bloque-{impact.value}-ambito-{index}"
    return f"""
        <section class="scope-group" id="{anchor}" aria-labelledby="{anchor}-titulo">
          <h3 id="{anchor}-titulo">{_escape(group[0].scope_label)}
            <span class="scope-count">{len(group)}</span>
          </h3>
          {_render_table(group)}
        </section>
"""


def _render_table(entries: Sequence[DiffEntry]) -> str:
    rows = "".join(_render_row(entry) for entry in entries)
    return f"""
          <div class="table-wrap">
            <table>
              <colgroup>
                <col class="col-policy"><col class="col-scope"><col class="col-value">
                <col class="col-value"><col class="col-cube"><col class="col-impact">
              </colgroup>
              <thead>
                <tr>
                  <th scope="col">Política</th>
                  <th scope="col">Ámbito</th>
                  <th scope="col">Valor en origen</th>
                  <th scope="col">Valor en destino</th>
                  <th scope="col">Cubo</th>
                  <th scope="col">Impacto para el usuario</th>
                </tr>
              </thead>
              <tbody>{rows}</tbody>
            </table>
          </div>
"""


def _render_row(entry: DiffEntry) -> str:
    return f"""
                <tr>
                  <td class="policy-cell"><strong>{_escape(entry.policy_name)}</strong>
                    <span class="policy-id">{_escape(entry.policy_id)}</span></td>
                  <td>{_escape(entry.scope_label)}</td>
                  <td>{_value_cell(entry.old_value)}</td>
                  <td>{_value_cell(entry.new_value)}</td>
                  <td><span class="badge badge-{entry.impact.value}">
                    {_escape(entry.impact.label)}</span></td>
                  <td class="reason">{_escape(entry.reason)}</td>
                </tr>"""


def _value_cell(value: str | None) -> str:
    if value is None:
        return '<span class="value missing">No definida</span>'
    return f'<span class="value">{_breakable(value)}</span>'


def _breakable(value: str) -> str:
    safe = _escape(value)
    for separator in ("_", "/", "."):
        safe = safe.replace(separator, f"{separator}<wbr>")
    return safe


def _group_by_scope(entries: Sequence[DiffEntry]) -> list[list[DiffEntry]]:
    groups: dict[tuple[str, str], list[DiffEntry]] = {}
    for entry in sorted(entries, key=_entry_sort_key):
        groups.setdefault((entry.scope_type.value, entry.scope_name), []).append(entry)
    return list(groups.values())


def _entry_sort_key(entry: DiffEntry) -> tuple[int, str, str, str]:
    return (
        _SCOPE_ORDER[entry.scope_type],
        entry.scope_name.casefold(),
        entry.policy_name.casefold(),
        entry.policy_id,
    )


def _report_sort_key(entry: DiffEntry) -> tuple[int, tuple[int, str, str, str]]:
    return (_IMPACT_INDEX[entry.impact], _entry_sort_key(entry))


def _json_payload(
    entries: Sequence[DiffEntry],
    *,
    old_tenant: str,
    new_tenant: str,
    generated_on: date,
) -> dict[str, object]:
    counts = Counter(entry.impact for entry in entries)
    ordered = sorted(entries, key=_report_sort_key)
    return {
        "schema_version": 1,
        "generated_on": generated_on.isoformat(),
        "old_tenant": old_tenant,
        "new_tenant": new_tenant,
        "policies_compared": len(entries),
        "changes": sum(entry.changed for entry in entries),
        "summary": {impact.value: counts[impact] for impact in IMPACT_ORDER},
        "entries": [_entry_payload(entry) for entry in ordered],
    }


def _entry_payload(entry: DiffEntry) -> dict[str, object]:
    return {
        "policy_id": entry.policy_id,
        "policy_name": entry.policy_name,
        "scope_type": entry.scope_type.value,
        "scope_name": entry.scope_name,
        "scope_label": entry.scope_label,
        "old_value": entry.old_value,
        "new_value": entry.new_value,
        "impact": entry.impact.value,
        "impact_label": entry.impact.label,
        "reason": entry.reason,
        "changed": entry.changed,
    }


def _escape(value: str) -> str:
    return html.escape(value, quote=True)


def _write_text(path: Path, content: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except IsADirectoryError:
        raise OutputError(f"{path} es un directorio") from None
    except PermissionError:
        raise OutputError(f"no tengo permiso para escribir {path}") from None
    except OSError as exc:
        reason = exc.strerror or str(exc)
        raise OutputError(f"no puedo escribir {path}: {reason}") from None


_CSS = """
:root {
  --ink: #17212b;
  --muted: #5b6773;
  --line: #d9e0e6;
  --soft: #f4f7f9;
  --breaks: #9b2c2c;
  --breaks-soft: #fbeeee;
  --training: #8a5a00;
  --training-soft: #fff6df;
  --neutral: #27613f;
  --neutral-soft: #eaf5ee;
}
* { box-sizing: border-box; }
html { color-scheme: light; }
body {
  margin: 0;
  background: #fff;
  color: var(--ink);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
    "Helvetica Neue", Arial, sans-serif;
  font-size: 16px;
  line-height: 1.5;
}
.report { max-width: 1120px; margin: 0 auto; padding: 40px 28px 56px; }
.report-header {
  border-bottom: 3px solid var(--ink); padding-bottom: 24px; margin-bottom: 30px;
}
.kicker {
  margin: 0 0 8px; color: var(--muted); font-size: .78rem; letter-spacing: .09em;
  text-transform: uppercase;
}
h1 {
  margin: 0 0 18px; font-size: clamp(1.9rem, 4vw, 2.8rem); line-height: 1.08;
  letter-spacing: -.02em;
}
.tenants { margin: 0 0 20px; font-size: 1.02rem; }
.tenant-label {
  color: var(--muted); font-size: .85rem; text-transform: uppercase;
  letter-spacing: .06em; margin-right: 4px;
}
.arrow { color: var(--muted); margin: 0 8px; }
.facts { display: flex; flex-wrap: wrap; gap: 10px 30px; margin: 0 0 22px; }
.facts div { display: flex; align-items: baseline; gap: 8px; }
.facts dt { color: var(--muted); font-size: .85rem; }
.facts dd { margin: 0; font-weight: 700; }
.cube-nav { display: flex; flex-wrap: wrap; gap: 10px; }
.cube-link {
  display: inline-flex; align-items: center; gap: 8px; border: 1px solid var(--line);
  border-radius: 999px; padding: 7px 12px; color: var(--ink); text-decoration: none;
  font-size: .9rem; background: #fff;
}
.cube-link:hover, .cube-link:focus { border-color: var(--ink); outline: none; }
.cube-link .count {
  display: inline-grid; place-items: center; min-width: 22px; height: 22px; padding: 0 6px;
  border-radius: 999px; background: var(--soft); font-size: .78rem; font-weight: 700;
}
.cube-rompe_flujo .count { background: var(--breaks-soft); color: var(--breaks); }
.cube-requiere_formacion .count { background: var(--training-soft); color: var(--training); }
.cube-sin_impacto .count { background: var(--neutral-soft); color: var(--neutral); }
.block { border-top: 1px solid var(--line); padding: 22px 0 6px; margin-top: 10px; }
.block-rompe_flujo { border-top: 4px solid var(--breaks); }
.block-requiere_formacion { border-top: 4px solid var(--training); }
.block-sin_impacto { border-top: 4px solid var(--neutral); }
.block > summary {
  display: flex; align-items: center; gap: 12px; cursor: pointer; list-style: none;
}
.block > summary::-webkit-details-marker { display: none; }
.block > summary::before { content: "▸"; color: var(--muted); font-size: .85rem; width: .9em; }
.block[open] > summary::before { content: "▾"; }
.block-title { margin: 0; font-size: 1.45rem; font-weight: 700; letter-spacing: -.01em; }
.block-count {
  display: inline-grid; place-items: center; min-width: 28px; height: 28px; padding: 0 8px;
  border-radius: 999px; background: var(--soft); font-size: .9rem; font-weight: 700;
}
.block-note { margin: 6px 0 8px 26px; color: var(--muted); font-size: .92rem; }
.scope-nav {
  display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 14px;
  margin: 10px 0 18px 26px; font-size: .85rem;
}
.scope-nav span { color: var(--muted); }
.scope-nav a { color: var(--ink); text-decoration: none; border-bottom: 1px solid var(--line); }
.scope-nav a:hover { border-color: var(--ink); }
.scope-group { margin: 18px 0 10px 26px; padding-top: 4px; }
.scope-group h3 {
  display: flex; align-items: baseline; gap: 8px; margin: 0 0 8px; font-size: 1rem;
}
.scope-count { color: var(--muted); font-size: .8rem; font-weight: 500; }
.table-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 8px; }
table {
  width: 100%; min-width: 720px; table-layout: fixed; border-collapse: collapse;
  font-size: .87rem;
}
col.col-policy { width: 22%; }
col.col-scope { width: 14%; }
col.col-value { width: 17%; }
col.col-cube { width: 10%; }
col.col-impact { width: 20%; }
thead { background: var(--soft); }
th {
  text-align: left; font-size: .72rem; text-transform: uppercase; letter-spacing: .05em;
  color: var(--muted); padding: 9px 10px; border-bottom: 1px solid var(--line);
}
td {
  padding: 10px; border-bottom: 1px solid var(--line); vertical-align: top;
  overflow-wrap: break-word;
}
tbody tr:last-child td { border-bottom: 0; }
tbody tr:nth-child(even) { background: #fbfcfd; }
.policy-cell strong { display: block; }
.policy-id {
  display: block; margin-top: 3px; color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: .72rem; overflow-wrap: break-word;
}
.value {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: .82rem; overflow-wrap: break-word;
}
.value.missing { font-family: inherit; color: var(--muted); font-style: italic; }
.badge {
  display: inline-block; max-width: 100%; padding: 3px 7px; border-radius: 4px;
  font-size: .73rem; font-weight: 700; white-space: normal;
}
.badge-rompe_flujo { color: var(--breaks); background: var(--breaks-soft); }
.badge-requiere_formacion { color: var(--training); background: var(--training-soft); }
.badge-sin_impacto { color: var(--neutral); background: var(--neutral-soft); }
.reason { color: #33414d; }
.empty { margin: 12px 0 12px 26px; color: var(--muted); }
.report-footer {
  border-top: 1px solid var(--line); margin-top: 36px; padding-top: 14px;
  color: var(--muted); font-size: .78rem;
}
@media (max-width: 720px) {
  .report { padding: 24px 16px 40px; }
  .block-note, .scope-nav, .scope-group { margin-left: 14px; }
  .facts { display: grid; grid-template-columns: 1fr; }
}
@media print {
  @page { size: A4; margin: 14mm 12mm; }
  body { font-size: 9pt; line-height: 1.35; }
  .report { max-width: none; padding: 0; }
  .no-print { display: none !important; }
  .report-header { padding-bottom: 12px; margin-bottom: 16px; }
  h1 { font-size: 20pt; }
  .block { padding-top: 12px; margin-top: 0; }
  .block + .block { break-before: page; }
  .block-title { font-size: 13pt; }
  .block-note { margin-left: 0; font-size: 8.5pt; }
  .scope-group { margin-left: 0; break-inside: avoid; }
  .table-wrap { overflow: visible; border-color: #bbb; }
  table { min-width: 0; font-size: 8pt; }
  th { font-size: 6.5pt; padding: 5px 6px; }
  td { padding: 6px; }
  .policy-id { font-size: 6.4pt; }
  .value { font-size: 7pt; }
  thead { display: table-header-group; }
  tr { break-inside: avoid; }
  .badge { border: 1px solid currentColor; font-size: 6.4pt; }
  a { color: inherit; text-decoration: none; }
  .report-footer { margin-top: 20px; }
}
"""

_HTML_DOCUMENT = Template(
    """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <meta name="generator" content="gam-policy-diff">
  <title>$title</title>
  <style>
$css
  </style>
</head>
<body>
  <div class="report">
$header
    <main>
$blocks
    </main>
    <footer class="report-footer">
      <p>$note</p>
    </footer>
  </div>
</body>
</html>
"""
)
