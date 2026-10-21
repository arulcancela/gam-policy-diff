import json
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import pytest

from gam_policy_diff.diff import compare_policy_sets
from gam_policy_diff.errors import OutputError
from gam_policy_diff.loader import load_policy_set
from gam_policy_diff.models import DiffEntry, Impact, ScopeType
from gam_policy_diff.report import (
    REPORT_NOTE,
    render_html,
    render_json,
    write_reports,
)

REPORT_DATE = date(2026, 10, 20)


@pytest.fixture
def entries(fixtures_dir: Path) -> list[DiffEntry]:
    return compare_policy_sets(
        load_policy_set(fixtures_dir / "tenant-origen.csv"),
        load_policy_set(fixtures_dir / "tenant-destino.csv"),
    )


@pytest.fixture
def report_html(entries: list[DiffEntry]) -> str:
    return render_html(
        entries,
        old_tenant="acme-origen",
        new_tenant="acme-destino",
        generated_on=REPORT_DATE,
    )


def test_header_has_tenants_date_and_policy_count(report_html: str) -> None:
    assert '<html lang="es">' in report_html
    assert "acme-origen" in report_html
    assert "acme-destino" in report_html
    assert "20/10/2026" in report_html
    assert "Políticas comparadas" in report_html
    assert "<dd>15</dd>" in report_html
    assert "Cambios" in report_html
    assert "<dd>9</dd>" in report_html


def test_three_blocks_are_in_the_required_order(report_html: str) -> None:
    breaks = report_html.index('id="bloque-rompe_flujo"')
    training = report_html.index('id="bloque-requiere_formacion"')
    no_impact = report_html.index('id="bloque-sin_impacto"')

    assert breaks < training < no_impact
    assert '<span class="block-count">4</span>' in report_html
    assert '<span class="block-count">5</span>' in report_html
    assert '<span class="block-count">6</span>' in report_html


def test_tables_have_the_required_columns_and_values(report_html: str) -> None:
    for header in (
        "Política",
        "Ámbito",
        "Valor en origen",
        "Valor en destino",
        "Cubo",
        "Impacto para el usuario",
    ):
        assert f'<th scope="col">{header}</th>' in report_html

    assert "Retención de correo (días)" in report_html
    assert "mail_retention_days" in report_html
    assert "2555" in report_html
    assert "1095" in report_html
    assert "OU: /Ventas" in report_html
    assert "Reenvío automático externo" in report_html
    assert "Se bloquea el reenvío automático externo" in report_html
    assert report_html.count('class="policy-cell"') == 15


def test_equal_policies_are_in_the_no_impact_block(report_html: str) -> None:
    assert report_html.count("El valor efectivo es el mismo en origen y destino.") == 6


def test_report_has_cube_and_scope_anchors(report_html: str) -> None:
    assert report_html.count("<details") == 3
    assert 'href="#bloque-rompe_flujo"' in report_html
    assert 'href="#bloque-rompe_flujo-ambito-1"' in report_html
    assert 'id="bloque-rompe_flujo-ambito-1"' in report_html
    assert "Tenant (3)" in report_html
    assert "OU: /Ventas (1)" in report_html


def test_report_has_print_styles(report_html: str) -> None:
    assert "@page" in report_html
    assert "size: A4" in report_html
    assert "@media print" in report_html
    assert "break-inside: avoid" in report_html


def test_report_has_no_external_resources(report_html: str) -> None:
    for forbidden in ("<script src", "<link", "<img", "http://", "https://", "@import", "url("):
        assert forbidden not in report_html


def test_report_has_search_and_filter_controls(report_html: str) -> None:
    assert 'id="search-input"' in report_html
    assert 'id="toggle-changed"' in report_html
    assert 'id="report-filter-script"' in report_html
    assert 'data-filter="rompe_flujo"' in report_html
    assert 'data-impact="rompe_flujo"' in report_html
    assert 'data-changed="true"' in report_html


def test_footer_contains_the_required_note(report_html: str) -> None:
    assert f"<p>{REPORT_NOTE}</p>" in report_html


def test_report_escapes_user_values() -> None:
    entry = DiffEntry(
        policy_id="x<y",
        policy_name='<script>alert("x")</script>',
        scope_type=ScopeType.OU,
        scope_name="/<Ventas>",
        old_value="<b>",
        new_value=None,
        impact=Impact.NO_IMPACT,
        reason='<img src=x onerror="alert(1)">',
    )

    report = render_html(
        [entry],
        old_tenant="<Origen>",
        new_tenant="Destino & Cía",
        generated_on=REPORT_DATE,
    )

    assert "<script>" not in report
    assert "<img" not in report
    assert "&lt;script&gt;" in report
    assert "&lt;img" in report
    assert "&lt;Origen&gt;" in report
    assert "Destino &amp; Cía" in report
    assert "No definida" in report


def test_empty_blocks_show_an_explicit_message() -> None:
    entry = DiffEntry(
        policy_id="mail_retention_days",
        policy_name="Retención",
        scope_type=ScopeType.TENANT,
        scope_name="",
        old_value="365",
        new_value="180",
        impact=Impact.BREAKS_FLOW,
        reason="Baja la retención.",
    )

    report = render_html(
        [entry],
        old_tenant="origen",
        new_tenant="destino",
        generated_on=REPORT_DATE,
    )

    assert report.count("No hay políticas en este cubo.") == 2
    assert '<span class="block-count">1</span>' in report
    assert '<span class="block-count">0</span>' in report


def test_json_contains_the_same_information(entries: list[DiffEntry]) -> None:
    payload = json.loads(
        render_json(
            entries,
            old_tenant="acme-origen",
            new_tenant="acme-destino",
            generated_on=REPORT_DATE,
        )
    )

    assert payload["schema_version"] == 1
    assert payload["generated_on"] == "2026-10-20"
    assert payload["old_tenant"] == "acme-origen"
    assert payload["new_tenant"] == "acme-destino"
    assert payload["policies_compared"] == 15
    assert payload["changes"] == 9
    assert payload["summary"] == {
        "rompe_flujo": 4,
        "requiere_formacion": 5,
        "sin_impacto": 6,
    }
    assert len(payload["entries"]) == 15


def test_json_entries_are_grouped_by_impact_and_have_all_fields(
    entries: list[DiffEntry],
) -> None:
    text = render_json(
        entries,
        old_tenant="acme-origen",
        new_tenant="acme-destino",
        generated_on=REPORT_DATE,
    )
    payload = json.loads(text)
    impacts = [entry["impact"] for entry in payload["entries"]]

    assert impacts == sorted(
        impacts, key=["rompe_flujo", "requiere_formacion", "sin_impacto"].index
    )
    retention = next(
        entry for entry in payload["entries"] if entry["policy_id"] == "mail_retention_days"
    )
    assert retention["old_value"] == "2555"
    assert retention["new_value"] == "1095"
    assert retention["impact"] == "rompe_flujo"
    assert retention["impact_label"] == "Rompe flujo"
    assert retention["scope_label"] == "Tenant"
    assert retention["changed"] is True
    assert retention["reason"]
    assert "Compartición" in text
    assert "\\u00f3" not in text


def test_write_reports_creates_html_and_json(tmp_path: Path, entries: list[DiffEntry]) -> None:
    html_path, json_path = write_reports(
        entries,
        old_tenant="acme-origen",
        new_tenant="acme-destino",
        html_path=tmp_path / "salida" / "informe.html",
        generated_on=REPORT_DATE,
    )

    assert html_path == tmp_path / "salida" / "informe.html"
    assert json_path == tmp_path / "salida" / "informe.json"
    assert html_path.is_file()
    assert json_path.is_file()
    assert html_path.read_text(encoding="utf-8").startswith("<!doctype html>")
    assert json.loads(json_path.read_text(encoding="utf-8"))["policies_compared"] == 15


def test_write_reports_rejects_a_non_html_output(tmp_path: Path, entries: list[DiffEntry]) -> None:
    with pytest.raises(OutputError, match=r"debe terminar en \.html"):
        write_reports(
            entries,
            old_tenant="origen",
            new_tenant="destino",
            html_path=tmp_path / "informe.txt",
            generated_on=REPORT_DATE,
        )


def test_write_reports_reports_a_directory_output(tmp_path: Path, entries: list[DiffEntry]) -> None:
    destination = tmp_path / "informe.html"
    destination.mkdir()

    with pytest.raises(OutputError, match="es un directorio"):
        write_reports(
            entries,
            old_tenant="origen",
            new_tenant="destino",
            html_path=destination,
            generated_on=REPORT_DATE,
        )


def test_write_reports_reports_a_permission_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    entries: list[DiffEntry],
) -> None:
    monkeypatch.setattr(Path, "write_text", Mock(side_effect=PermissionError))

    with pytest.raises(OutputError, match="permiso"):
        write_reports(
            entries,
            old_tenant="origen",
            new_tenant="destino",
            html_path=tmp_path / "informe.html",
            generated_on=REPORT_DATE,
        )


def test_write_reports_reports_a_generic_os_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    entries: list[DiffEntry],
) -> None:
    monkeypatch.setattr(
        Path,
        "write_text",
        Mock(side_effect=OSError(28, "No space left on device")),
    )

    with pytest.raises(OutputError, match="no puedo escribir"):
        write_reports(
            entries,
            old_tenant="origen",
            new_tenant="destino",
            html_path=tmp_path / "informe.html",
            generated_on=REPORT_DATE,
        )


def test_render_reports_with_changes_only(entries: list[DiffEntry]) -> None:
    html = render_html(
        entries,
        old_tenant="origen",
        new_tenant="destino",
        generated_on=REPORT_DATE,
        changes_only=True,
    )
    assert "solo cambios" in html
    assert "checked" in html

    json_text = render_json(
        entries,
        old_tenant="origen",
        new_tenant="destino",
        generated_on=REPORT_DATE,
        changes_only=True,
    )
    payload = json.loads(json_text)
    assert payload["changes_only"] is True
