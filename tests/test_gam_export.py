import json
from collections.abc import Callable
from pathlib import Path
from zipfile import ZipFile

import pytest

from gam_policy_diff.cli import main
from gam_policy_diff.errors import InputError
from gam_policy_diff.gam_export import GAM_POLICY_MAPPINGS, load_gam_policy_export
from gam_policy_diff.loader import load_policy_set

HEADERS = [
    "name",
    "policyQuery.orgUnit",
    "policyQuery.orgUnitPath",
    "policyQuery.sortOrder",
    "setting.type",
    "type",
    "setting.value.webSessionDuration",
    "setting.value.enableAutoForwarding",
    "setting.value.enforcedFrom",
    "setting.value.externalSharingMode",
    "setting.value.allowedPartiesForDistributingContent",
    "policyQuery.group",
    "policyQuery.groupEmail",
]

ROWS = [
    {
        "name": "policy-root-session",
        "policyQuery.orgUnitPath": "/",
        "setting.type": "settings/security.session_controls",
        "setting.value.webSessionDuration": "1209600s",
    },
    {
        "name": "policy-ou-session",
        "policyQuery.orgUnitPath": "/Ventas",
        "setting.type": "settings/security.session_controls",
        "setting.value.webSessionDuration": "43200s",
    },
    {
        "name": "policy-root-forwarding",
        "policyQuery.orgUnitPath": "/",
        "setting.type": "settings/gmail.auto_forwarding",
        "setting.value.enableAutoForwarding": "TRUE",
    },
    {
        "name": "policy-root-2sv",
        "policyQuery.orgUnitPath": "/",
        "setting.type": "settings/security.two_step_verification_enforcement",
        "setting.value.enforcedFrom": "1970-01-01T00:00:00Z",
    },
    {
        "name": "policy-ou-2sv",
        "policyQuery.orgUnitPath": "/Direccion",
        "setting.type": "settings/security.two_step_verification_enforcement",
        "setting.value.enforcedFrom": "2022-01-01T00:00:00Z",
    },
    {
        "name": "policy-group-2sv",
        "policyQuery.group": "grupo-prueba",
        "policyQuery.groupEmail": "Grupo@Example.test",
        "setting.type": "settings/security.two_step_verification_enforcement",
        "setting.value.enforcedFrom": "2022-01-01T00:00:00Z",
    },
    {
        "name": "policy-root-drive",
        "policyQuery.orgUnitPath": "/",
        "setting.type": "settings/drive_and_docs.external_sharing",
        "setting.value.externalSharingMode": "ALLOWED",
        "setting.value.allowedPartiesForDistributingContent": "ALL_ELIGIBLE_USERS",
    },
    {
        "name": "policy-ou-drive",
        "policyQuery.orgUnitPath": "/Tiendas",
        "setting.type": "settings/drive_and_docs.external_sharing",
        "setting.value.externalSharingMode": "BLOCKED",
        "setting.value.allowedPartiesForDistributingContent": "NO_ONE",
    },
    {
        "name": "policy-other-drive",
        "policyQuery.orgUnitPath": "/Direccion",
        "setting.type": "settings/drive_and_docs.external_sharing",
        "setting.value.externalSharingMode": "ALLOWED",
        "setting.value.allowedPartiesForDistributingContent": "DOMAIN",
    },
    {
        "name": "policy-unknown",
        "policyQuery.orgUnitPath": "/",
        "setting.type": "settings/unknown.setting",
    },
]


@pytest.fixture
def synthetic_export(
    tmp_path: Path,
    xlsx_factory: Callable[..., Path],
) -> Path:
    return xlsx_factory(tmp_path / "tenant-prueba.xlsx", HEADERS, ROWS)


def test_maps_only_supported_settings(synthetic_export: Path) -> None:
    policies = load_gam_policy_export(synthetic_export)

    assert len(policies) == 9
    assert policies.tenant == "tenant-prueba"
    assert policies.policies[("session_length_hours", "tenant", "")].value == "336"
    assert policies.policies[("session_length_hours", "ou", "/Ventas")].value == "12"
    assert policies.policies[("mail_forwarding_external", "tenant", "")].value == "allow"
    assert policies.policies[("enforce_2sv", "tenant", "")].value == "false"
    assert policies.policies[("enforce_2sv", "ou", "/Direccion")].value == "true"
    assert policies.policies[("enforce_2sv", "group", "grupo@example.test")].value == "true"
    assert policies.policies[("drive_sharing_external", "tenant", "")].value == "anyone_with_link"
    assert policies.policies[("drive_sharing_external", "ou", "/Tiendas")].value == "off"
    assert policies.policies[("drive_sharing_external", "ou", "/Direccion")].value == "domain"


def test_load_policy_set_detects_xlsx(synthetic_export: Path) -> None:
    policies = load_policy_set(synthetic_export)

    assert len(policies) == 9
    assert policies.tenant == "tenant-prueba"


def test_duplicate_rows_with_same_value_are_ignored(
    tmp_path: Path,
    xlsx_factory: Callable[..., Path],
) -> None:
    rows = [dict(ROWS[0]), dict(ROWS[0])]
    path = xlsx_factory(tmp_path / "duplicado-igual.xlsx", HEADERS, rows)

    policies = load_gam_policy_export(path)

    assert len(policies) == 1
    assert policies.policies[("session_length_hours", "tenant", "")].value == "336"


def test_conflicting_duplicate_rows_are_rejected(
    tmp_path: Path,
    xlsx_factory: Callable[..., Path],
) -> None:
    rows = [dict(ROWS[0]), dict(ROWS[0])]
    rows[1]["setting.value.webSessionDuration"] = "43200s"
    path = xlsx_factory(tmp_path / "duplicado.xlsx", HEADERS, rows)

    with pytest.raises(InputError, match="valores distintos"):
        load_gam_policy_export(path)


def test_missing_required_header_is_reported(
    tmp_path: Path,
    xlsx_factory: Callable[..., Path],
) -> None:
    headers = [header for header in HEADERS if header != "policyQuery.groupEmail"]
    path = xlsx_factory(tmp_path / "sin-cabecera.xlsx", headers, ROWS)

    with pytest.raises(InputError, match="faltan columnas"):
        load_gam_policy_export(path)


def test_export_without_supported_settings_is_reported(
    tmp_path: Path,
    xlsx_factory: Callable[..., Path],
) -> None:
    rows = [dict(ROWS[-1])]
    path = xlsx_factory(tmp_path / "sin-politicas.xlsx", HEADERS, rows)

    with pytest.raises(InputError, match="no contiene políticas"):
        load_gam_policy_export(path)


def test_malformed_xlsx_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "malo.xlsx"
    path.write_text("no es un xlsx", encoding="utf-8")

    with pytest.raises(InputError, match="no es un XLSX válido"):
        load_policy_set(path)


def test_map_is_rejected_for_xlsx(synthetic_export: Path) -> None:
    with pytest.raises(InputError, match="no se aplica"):
        load_policy_set(synthetic_export, {"policy_id": "x"})


def test_old_excel_format_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "export.xls"
    path.write_text("", encoding="utf-8")

    with pytest.raises(InputError, match="no está soportado"):
        load_policy_set(path)


def test_missing_xlsx_is_reported(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="no encuentro el fichero"):
        load_gam_policy_export(tmp_path / "no-existe.xlsx")


def test_session_accepts_hours_and_iso_durations(
    tmp_path: Path,
    xlsx_factory: Callable[..., Path],
) -> None:
    rows = [dict(ROWS[0]), dict(ROWS[0]), dict(ROWS[0])]
    variants = (("/A", "12h"), ("/B", "PT12H"), ("/C", "0s"))
    for row, (path, value) in zip(rows, variants, strict=True):
        row["policyQuery.orgUnitPath"] = path
        row["setting.value.webSessionDuration"] = value
    export = xlsx_factory(tmp_path / "duraciones.xlsx", HEADERS, rows)

    policies = load_gam_policy_export(export)

    assert policies.policies[("session_length_hours", "ou", "/A")].value == "12"
    assert policies.policies[("session_length_hours", "ou", "/B")].value == "12"
    assert policies.policies[("session_length_hours", "ou", "/C")].value == "0"


def test_forwarding_false_and_unknown_values(
    tmp_path: Path,
    xlsx_factory: Callable[..., Path],
) -> None:
    rows = [dict(ROWS[2]), dict(ROWS[2])]
    rows[0]["setting.value.enableAutoForwarding"] = "FALSE"
    rows[1]["policyQuery.orgUnitPath"] = "/Ventas"
    rows[1]["setting.value.enableAutoForwarding"] = "OTRO"
    export = xlsx_factory(tmp_path / "forwarding.xlsx", HEADERS, rows)

    policies = load_gam_policy_export(export)

    assert len(policies) == 1
    assert policies.policies[("mail_forwarding_external", "tenant", "")].value == "deny"


def test_two_step_without_enforced_date_is_skipped(
    tmp_path: Path,
    xlsx_factory: Callable[..., Path],
) -> None:
    rows = [dict(ROWS[3]), dict(ROWS[2])]
    del rows[0]["setting.value.enforcedFrom"]
    export = xlsx_factory(tmp_path / "2sv-vacio.xlsx", HEADERS, rows)

    policies = load_gam_policy_export(export)

    assert len(policies) == 1
    assert ("enforce_2sv", "tenant", "") not in policies.policies


def test_invalid_sheet_xml_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "xml-malo.xlsx"
    with ZipFile(path, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", "<worksheet>")

    with pytest.raises(InputError, match="XML no válido"):
        load_gam_policy_export(path)


def test_sheet_without_data_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "sin-datos.xlsx"
    sheet = (
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData/></worksheet>"
    )
    with ZipFile(path, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", sheet)

    with pytest.raises(InputError, match="no contiene datos"):
        load_gam_policy_export(path)


def test_invalid_shared_string_reference_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "texto-malo.xlsx"
    sheet = (
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData><row r="1"><c r="A1" t="s"><v>99</v></c></row></sheetData>'
        "</worksheet>"
    )
    with ZipFile(path, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", sheet)

    with pytest.raises(InputError, match="referencia de texto"):
        load_gam_policy_export(path)


def test_empty_zip_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "vacio.xlsx"
    with ZipFile(path, "w"):
        pass

    with pytest.raises(InputError, match="ninguna hoja"):
        load_gam_policy_export(path)


def test_invalid_session_value_is_skipped(
    tmp_path: Path,
    xlsx_factory: Callable[..., Path],
) -> None:
    rows = [dict(ROWS[0]), dict(ROWS[2])]
    rows[0]["setting.value.webSessionDuration"] = "n/a"
    path = xlsx_factory(tmp_path / "sesion-invalida.xlsx", HEADERS, rows)

    policies = load_gam_policy_export(path)

    assert len(policies) == 1
    assert policies.policies[("mail_forwarding_external", "tenant", "")].value == "allow"


def test_drive_sharing_requires_a_known_mapping(
    tmp_path: Path,
    xlsx_factory: Callable[..., Path],
) -> None:
    rows = [dict(ROWS[2]), dict(ROWS[6])]
    rows[1]["setting.value.allowedPartiesForDistributingContent"] = "OTROS"
    path = xlsx_factory(tmp_path / "drive-desconocido.xlsx", HEADERS, rows)

    policies = load_gam_policy_export(path)

    assert len(policies) == 1
    assert ("drive_sharing_external", "tenant", "") not in policies.policies


def test_mapping_table_is_unique_and_documented() -> None:
    settings = [mapping.setting_type for mapping in GAM_POLICY_MAPPINGS]

    assert len(settings) == len(set(settings))
    assert all(mapping.policy_id for mapping in GAM_POLICY_MAPPINGS)
    assert all(mapping.policy_name for mapping in GAM_POLICY_MAPPINGS)


def test_cli_compares_two_xlsx_exports(
    tmp_path: Path,
    xlsx_factory: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    old_rows = [dict(ROWS[0]), dict(ROWS[2])]
    new_rows = [dict(ROWS[0]), dict(ROWS[2])]
    new_rows[0]["setting.value.webSessionDuration"] = "604800s"
    new_rows[1]["setting.value.enableAutoForwarding"] = "FALSE"
    old_path = xlsx_factory(tmp_path / "tenant-origen.xlsx", HEADERS, old_rows)
    new_path = xlsx_factory(tmp_path / "tenant-destino.xlsx", HEADERS, new_rows)
    output_path = tmp_path / "report.html"

    assert (
        main(
            [
                "--old",
                str(old_path),
                "--new",
                str(new_path),
                "--out",
                str(output_path),
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "Rompe flujo: 2" in output
    assert output_path.is_file()
    payload = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert payload["policies_compared"] == 2
    assert payload["summary"]["rompe_flujo"] == 2
