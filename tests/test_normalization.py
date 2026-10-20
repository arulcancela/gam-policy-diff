import pytest

from gam_policy_diff.normalization import normalize_header, normalize_identifier, normalize_value


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  ANYONE_WITH_LINK ", "anyone_with_link"),
        ("Sí", "true"),
        ("YES", "true"),
        ("Desactivado", "false"),
        ("12.0", "12"),
        ("  dos   palabras ", "dos palabras"),
        ("OFF", "off"),
        ("", ""),
    ],
)
def test_normalize_value(raw: str, expected: str) -> None:
    assert normalize_value(raw) == expected


def test_normalize_header_ignores_accents_and_separators() -> None:
    assert normalize_header(" Tipo de Ámbito ") == "tipo_de_ambito"
    assert normalize_header("Policy ID") == "policy_id"


def test_normalize_identifier_uses_the_same_rules_as_headers() -> None:
    assert normalize_identifier(" Drive Sharing External ") == "drive_sharing_external"
