import json
from collections import Counter
from pathlib import Path

import pytest

from gam_policy_diff.errors import InputError
from gam_policy_diff.loader import load_policy_set, parse_column_map
from gam_policy_diff.models import ScopeType

CSV_HEADER = "policy_id,policy_name,scope_type,scope_name,value,tenant\n"


def write_csv(path: Path, rows: str, header: str = CSV_HEADER) -> Path:
    path.write_text(header + rows, encoding="utf-8")
    return path


def test_loads_origin_fixture(fixtures_dir: Path) -> None:
    policies = load_policy_set(fixtures_dir / "tenant-origen.csv")

    assert len(policies) == 15
    assert policies.tenant == "acme-origen"
    assert Counter(policy.scope_type for policy in policies) == Counter(
        {ScopeType.TENANT: 5, ScopeType.OU: 8, ScopeType.GROUP: 2}
    )
    policy = policies.policies[("drive_sharing_external", "ou", "/Ventas")]
    assert policy.name == "Compartición externa en Drive"
    assert policy.value == "anyone_with_link"


def test_loads_destination_fixture(fixtures_dir: Path) -> None:
    policies = load_policy_set(fixtures_dir / "tenant-destino.csv")

    assert len(policies) == 15
    assert policies.tenant == "acme-destino"
    assert policies.policies[("mail_retention_days", "tenant", "")].value == "1095"
    assert policies.policies[("session_length_hours", "tenant", "")].value == "4"


def test_same_policy_keeps_separate_entries_per_scope(fixtures_dir: Path) -> None:
    policies = load_policy_set(fixtures_dir / "tenant-origen.csv")
    values = {
        policy.scope_name: policy.value
        for policy in policies
        if policy.policy_id == "drive_sharing_external"
    }

    assert values == {
        "": "anyone_with_link",
        "/Direccion": "off",
        "/Ventas": "anyone_with_link",
        "/Tiendas": "anyone_with_link",
    }


def test_loads_csv_with_custom_headers_and_mapping(tmp_path: Path) -> None:
    path = tmp_path / "custom.csv"
    path.write_text(
        "id_pol;nombre;tipo;ambito;valor;empresa\n"
        "drive_sharing_external;Compartición externa;OU;/Ventas;off;acme-prueba\n",
        encoding="utf-8",
    )
    mapping = {
        "policy_id": "id_pol",
        "policy_name": "nombre",
        "scope_type": "tipo",
        "scope_name": "ambito",
        "value": "valor",
        "tenant": "empresa",
    }

    policies = load_policy_set(path, mapping)

    policy = policies.policies[("drive_sharing_external", "ou", "/Ventas")]
    assert policies.tenant == "acme-prueba"
    assert policy.value == "off"


def test_accepts_known_spanish_headers_without_mapping(tmp_path: Path) -> None:
    path = tmp_path / "spanish.csv"
    path.write_text(
        "id_politica,nombre_politica,tipo_ambito,nombre_ambito,valor,tenant\n"
        "calendar_default_view,Vista,OU,/Tiendas,week,acme-prueba\n",
        encoding="utf-8",
    )

    policies = load_policy_set(path)

    assert policies.policies[("calendar_default_view", "ou", "/Tiendas")].value == "week"


def test_csv_supports_quoted_commas_and_semicolons(tmp_path: Path) -> None:
    path = tmp_path / "quoted.csv"
    path.write_text(
        "policy_id;policy_name;scope_type;scope_name;value;tenant\n"
        'alias_domain;"Alias, principal";tenant;;acme-prueba.test;acme-prueba\n',
        encoding="utf-8",
    )

    policies = load_policy_set(path)

    policy = policies.policies[("alias_domain", "tenant", "")]
    assert policy.name == "Alias, principal"
    assert policy.value == "acme-prueba.test"


def test_loads_json_array(tmp_path: Path) -> None:
    path = tmp_path / "policies.json"
    path.write_text(
        json.dumps(
            [
                {
                    "policy_id": "mail_retention_days",
                    "policy_name": "Retención",
                    "scope_type": "tenant",
                    "scope_name": "",
                    "value": 2555,
                    "tenant": "acme-json",
                }
            ]
        ),
        encoding="utf-8",
    )

    policies = load_policy_set(path)

    assert policies.tenant == "acme-json"
    assert policies.policies[("mail_retention_days", "tenant", "")].value == "2555"


def test_loads_json_object_with_tenant_and_boolean_values(tmp_path: Path) -> None:
    path = tmp_path / "policies.json"
    path.write_text(
        json.dumps(
            {
                "tenant": "acme-json",
                "policies": [
                    {
                        "policy_id": "enforce_2sv",
                        "scope_type": "tenant",
                        "scope_name": "",
                        "value": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    policies = load_policy_set(path)

    policy = policies.policies[("enforce_2sv", "tenant", "")]
    assert policy.value == "true"
    assert policy.name == "enforce_2sv"


def test_json_accepts_one_tenant_per_row(tmp_path: Path) -> None:
    path = tmp_path / "policies.json"
    path.write_text(
        json.dumps(
            [
                {
                    "policy_id": "alias_domain",
                    "scope_type": "tenant",
                    "scope_name": "",
                    "value": "acme.test",
                    "tenant": "acme-json",
                }
            ]
        ),
        encoding="utf-8",
    )

    assert load_policy_set(path).tenant == "acme-json"


def test_tenant_falls_back_to_file_name(tmp_path: Path) -> None:
    path = tmp_path / "tenant-prueba.csv"
    path.write_text(
        "policy_id,policy_name,scope_type,scope_name,value\nalias_domain,Alias,tenant,,acme.test\n",
        encoding="utf-8",
    )

    assert load_policy_set(path).tenant == "tenant-prueba"


def test_missing_required_column_reports_the_field(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path / "missing.csv",
        "alias_domain,Alias,tenant,acme.test,acme\n",
        header="policy_id,policy_name,scope_type,scope_name,tenant\n",
    )

    with pytest.raises(InputError, match="faltan columnas obligatorias: value"):
        load_policy_set(path)


def test_duplicate_policy_reports_both_lines(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path / "duplicate.csv",
        "drive_sharing_external,Compartición,tenant,,off,acme\n"
        "drive_sharing_external,Compartición,tenant,,on,acme\n",
    )

    with pytest.raises(InputError, match="ya aparece en la línea 2"):
        load_policy_set(path)


def test_unknown_scope_type_is_reported_with_the_line(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path / "scope.csv",
        "drive_sharing_external,Compartición,departamento,/Ventas,off,acme\n",
    )

    with pytest.raises(InputError, match="línea 2: tipo de ámbito desconocido"):
        load_policy_set(path)


def test_missing_scope_name_is_reported(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path / "scope-name.csv",
        "drive_sharing_external,Compartición,OU,,off,acme\n",
    )

    with pytest.raises(InputError, match="necesita un nombre"):
        load_policy_set(path)


def test_empty_value_is_reported(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path / "empty-value.csv",
        "drive_sharing_external,Compartición,tenant,,,acme\n",
    )

    with pytest.raises(InputError, match="no tiene valor"):
        load_policy_set(path)


def test_empty_policy_id_is_reported(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path / "empty-id.csv",
        ",Compartición,tenant,,off,acme\n",
    )

    with pytest.raises(InputError, match="identificador de la política está vacío"):
        load_policy_set(path)


def test_mixed_tenants_are_rejected(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path / "mixed.csv",
        "alias_domain,Alias,tenant,,uno.test,acme-uno\n"
        "alias_domain_alias,Alias,tenant,,dos.test,acme-dos\n",
    )

    with pytest.raises(InputError, match="varios tenants"):
        load_policy_set(path)


def test_empty_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("   \n", encoding="utf-8")

    with pytest.raises(InputError, match="está vacío"):
        load_policy_set(path)


def test_missing_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="no encuentro el fichero"):
        load_policy_set(tmp_path / "no-existe.csv")


def test_directory_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="es un directorio"):
        load_policy_set(tmp_path)


def test_non_utf8_file_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "latin.csv"
    path.write_bytes(b"policy_id,policy_name\n\xf1and\xfa\n")

    with pytest.raises(InputError, match="no está codificado en UTF-8"):
        load_policy_set(path)


def test_malformed_json_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text('{"policies": [}', encoding="utf-8")

    with pytest.raises(InputError, match="no es un JSON válido"):
        load_policy_set(path)


def test_json_object_without_policies_key_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text('{"items": []}', encoding="utf-8")

    with pytest.raises(InputError, match="clave 'policies'"):
        load_policy_set(path)


def test_json_policies_must_be_a_list(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text('{"policies": {}}', encoding="utf-8")

    with pytest.raises(InputError, match="debe contener una lista"):
        load_policy_set(path)


def test_json_without_policies_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "empty.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(InputError, match="no contiene políticas"):
        load_policy_set(path)


def test_json_element_must_be_an_object(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text('["policy"]', encoding="utf-8")

    with pytest.raises(InputError, match="no es un objeto"):
        load_policy_set(path)


def test_json_values_must_be_scalars(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text(
        '[{"policy_id": "x", "scope_type": "tenant", "value": ["a"]}]',
        encoding="utf-8",
    )

    with pytest.raises(InputError, match="valor simple"):
        load_policy_set(path)


def test_blank_csv_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("\n\n", encoding="utf-8")

    with pytest.raises(InputError, match="está vacío"):
        load_policy_set(path)


def test_csv_without_a_named_header_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "no-header.csv"
    path.write_text('""\n', encoding="utf-8")

    with pytest.raises(InputError, match="no tiene cabecera"):
        load_policy_set(path)


def test_csv_with_only_header_has_no_policies(tmp_path: Path) -> None:
    path = write_csv(tmp_path / "header.csv", "")

    with pytest.raises(InputError, match="no contiene políticas"):
        load_policy_set(path)


def test_csv_with_more_columns_than_header_is_rejected(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path / "extra.csv",
        "alias_domain,Alias,tenant,,acme.test,acme,sobra\n",
    )

    with pytest.raises(InputError, match="más columnas"):
        load_policy_set(path)


def test_csv_with_unnamed_column_is_rejected(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path / "unnamed.csv",
        "alias_domain,Alias,tenant,,acme.test,acme\n",
        header="policy_id,policy_name,,scope_name,value,tenant\n",
    )

    with pytest.raises(InputError, match="columna sin nombre"):
        load_policy_set(path)


def test_ambiguous_headers_are_rejected(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path / "ambiguous.csv",
        "alias_domain,Alias,tenant,,acme.test,acme\n",
        header="policy_id,Policy ID,scope_type,scope_name,value,tenant\n",
    )

    with pytest.raises(InputError, match="son ambiguas"):
        load_policy_set(path)


def test_mapping_file_is_loaded(tmp_path: Path) -> None:
    mapping_file = tmp_path / "mapping.json"
    mapping_file.write_text(
        json.dumps({"policy_id": "id_pol", "value": "valor"}),
        encoding="utf-8",
    )

    assert parse_column_map(str(mapping_file)) == {"policy_id": "id_pol", "value": "valor"}


def test_inline_mapping_is_parsed() -> None:
    assert parse_column_map("policy_id=id_pol,value=valor") == {
        "policy_id": "id_pol",
        "value": "valor",
    }


def test_missing_mapping_file_is_reported() -> None:
    with pytest.raises(InputError, match="no encuentro el fichero de mapeo"):
        parse_column_map("no-existe.json")


def test_invalid_inline_mapping_is_reported() -> None:
    with pytest.raises(InputError, match="mapeo no válido"):
        parse_column_map("policy_id=")


def test_empty_mapping_is_reported() -> None:
    with pytest.raises(InputError, match="mapeo de columnas está vacío"):
        parse_column_map("  ")


def test_mapping_file_must_be_a_json_object(tmp_path: Path) -> None:
    mapping_file = tmp_path / "mapping.json"
    mapping_file.write_text("[]", encoding="utf-8")

    with pytest.raises(InputError, match="objeto JSON"):
        parse_column_map(str(mapping_file))


def test_mapping_file_must_contain_valid_json(tmp_path: Path) -> None:
    mapping_file = tmp_path / "mapping.json"
    mapping_file.write_text("{", encoding="utf-8")

    with pytest.raises(InputError, match="no es un JSON válido"):
        parse_column_map(str(mapping_file))


def test_mapping_file_must_use_strings(tmp_path: Path) -> None:
    mapping_file = tmp_path / "mapping.json"
    mapping_file.write_text('{"policy_id": 1}', encoding="utf-8")

    with pytest.raises(InputError, match="cadenas de texto"):
        parse_column_map(str(mapping_file))


def test_mapping_file_cannot_be_empty(tmp_path: Path) -> None:
    mapping_file = tmp_path / "mapping.json"
    mapping_file.write_text("{}", encoding="utf-8")

    with pytest.raises(InputError, match="no contiene ningún mapeo"):
        parse_column_map(str(mapping_file))


def test_unknown_mapping_field_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "custom.csv"
    path.write_text(
        "id_pol;nombre;tipo;ambito;valor;empresa\n"
        "drive_sharing_external;Compartición;OU;/Ventas;off;acme\n",
        encoding="utf-8",
    )

    with pytest.raises(InputError, match="campos de mapeo desconocidos"):
        load_policy_set(path, {"inventado": "id_pol"})


def test_mapping_column_must_exist(tmp_path: Path) -> None:
    path = tmp_path / "custom.csv"
    path.write_text(
        "id_pol;nombre;tipo;ambito;valor;empresa\n"
        "drive_sharing_external;Compartición;OU;/Ventas;off;acme\n",
        encoding="utf-8",
    )

    with pytest.raises(InputError, match="no existe"):
        load_policy_set(
            path,
            {
                "policy_id": "id_pol",
                "policy_name": "nombre",
                "scope_type": "tipo",
                "scope_name": "ambito",
                "value": "columna-inexistente",
                "tenant": "empresa",
            },
        )
