from pathlib import Path
from unittest.mock import Mock

import pytest

from gam_policy_diff.cli import main


def test_demo_generates_reports_with_default_path(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["--demo"]) == 0

    output = capsys.readouterr().out
    assert "Origen: acme-origen (15 políticas)" in output
    assert "Destino: acme-destino (15 políticas)" in output
    assert "Rompe flujo: 4" in output
    assert "Requiere formación: 5" in output
    assert "Sin impacto: 6" in output
    assert "Informe HTML: report.html" in output
    assert "Datos JSON: report.json" in output
    assert (tmp_path / "report.html").is_file()
    assert (tmp_path / "report.json").is_file()


def test_without_inputs_shows_a_clear_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 1

    assert "indica --old y --new" in capsys.readouterr().err


def test_demo_does_not_accept_file_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--demo", "--old", "origen.csv"]) == 1

    assert "--demo no se combina" in capsys.readouterr().err


def test_demo_without_fixtures_returns_one(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(Path, "is_file", Mock(return_value=False))

    assert main(["--demo"]) == 1

    assert "no encuentro los fixtures" in capsys.readouterr().err


def test_missing_file_returns_one(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    assert main(["--old", str(tmp_path / "no.csv"), "--new", str(tmp_path / "no.csv")]) == 1

    assert "no encuentro el fichero" in capsys.readouterr().err


def test_unknown_argument_returns_one(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--inventado"]) == 1

    assert "unrecognized arguments" in capsys.readouterr().err


def test_no_differences_returns_two_and_writes_nothing(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    fixtures_dir: Path,
) -> None:
    source = fixtures_dir / "tenant-origen.csv"
    destination = tmp_path / "report.html"

    assert (
        main(
            [
                "--old",
                str(source),
                "--new",
                str(source),
                "--out",
                str(destination),
            ]
        )
        == 2
    )

    assert "No hay diferencias entre los tenants." in capsys.readouterr().out
    assert not destination.exists()
    assert not (tmp_path / "report.json").exists()


def test_invalid_output_extension_returns_one(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    assert main(["--demo", "--out", str(tmp_path / "report.txt")]) == 1

    assert "debe terminar en .html" in capsys.readouterr().err


def test_output_directory_error_returns_one(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    destination = tmp_path / "report.html"
    destination.mkdir()

    assert main(["--demo", "--out", str(destination)]) == 1

    assert "es un directorio" in capsys.readouterr().err


def test_inline_mapping_is_applied(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    old_path = tmp_path / "origen.csv"
    new_path = tmp_path / "destino.csv"
    header = "id_pol,nombre,tipo,ambito,valor,empresa\n"
    old_path.write_text(
        header + "alias_domain,Alias,tenant,,acme-viejo.test,acme-prueba\n",
        encoding="utf-8",
    )
    new_path.write_text(
        header + "alias_domain,Alias,tenant,,acme-nuevo.test,acme-prueba\n",
        encoding="utf-8",
    )
    mapping = "policy_id=id_pol,policy_name=nombre,scope_type=tipo,"
    mapping += "scope_name=ambito,value=valor,tenant=empresa"
    output_path = tmp_path / "report.html"

    assert (
        main(
            [
                "--old",
                str(old_path),
                "--new",
                str(new_path),
                "--map",
                mapping,
                "--out",
                str(output_path),
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "acme-prueba" in output
    assert "Requiere formación: 1" in output
    assert output_path.is_file()
    assert (tmp_path / "report.json").is_file()
