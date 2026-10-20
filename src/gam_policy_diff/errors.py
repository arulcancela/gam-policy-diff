"""Errores de entrada y salida que se muestran al usuario sin traza de Python."""

from __future__ import annotations


class InputError(Exception):
    """Un fichero de entrada no se puede leer o no tiene el formato esperado."""


class OutputError(Exception):
    """El informe no se puede escribir en la ruta indicada."""


class DuplicatePolicyError(ValueError):
    """Dos políticas comparten identificador y ámbito dentro del mismo tenant."""

    def __init__(self, key: tuple[str, str, str]) -> None:
        policy_id, scope_type, scope_name = key
        scope = f"{scope_type} {scope_name}".strip()
        super().__init__(f"política duplicada: {policy_id} en {scope}")
