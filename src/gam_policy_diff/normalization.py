"""Normalización de valores y nombres usados en las comparaciones."""

from __future__ import annotations

import re
import unicodedata

_WHITESPACE = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_INTEGER_DECIMAL = re.compile(r"^-?\d+\.0+$")

_TRUE_VALUES = frozenset({"true", "yes", "enabled", "activado", "activo", "si", "sí"})
_FALSE_VALUES = frozenset({"false", "no", "disabled", "desactivado", "inactivo"})


def normalize_value(raw: str) -> str:
    """Devuelve el valor en una forma estable para comparar, sin perder el original."""
    text = _WHITESPACE.sub(" ", raw.strip()).casefold()
    if _INTEGER_DECIMAL.fullmatch(text):
        return text.split(".", 1)[0]
    if text in _TRUE_VALUES:
        return "true"
    if text in _FALSE_VALUES:
        return "false"
    return text


def normalize_header(raw: str) -> str:
    """Normaliza una cabecera o un nombre para buscarlo sin depender de tildes ni separadores."""
    text = _strip_accents(raw.strip().casefold())
    return _NON_ALNUM.sub("_", text).strip("_")


def normalize_identifier(raw: str) -> str:
    """Normaliza el identificador de una política."""
    return normalize_header(raw)


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(character for character in decomposed if not unicodedata.combining(character))
