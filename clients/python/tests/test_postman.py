"""
Tests del escritor de environment Postman. Asertamos la forma del JSON
emitido — lo suficiente para que Postman lo importe sin preguntar.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from aguas_ingest.postman import PostmanEnvValues, build_env, write_env


def _values() -> PostmanEnvValues:
    return PostmanEnvValues(
        base_url="http://localhost:3000",
        signer_address="0x000000000000000000000000000000000000abcd",
        signature="0x" + "aa" * 65,
        batch_body='{"batch":{"batchId":"foo"},"vehicles":[]}',
    )


def test_build_env_has_required_top_level_shape() -> None:
    env = build_env("AguasDeCordoba — local", _values())

    assert env["name"] == "AguasDeCordoba — local"
    assert env["_postman_variable_scope"] == "environment"
    values = cast("list[dict[str, Any]]", env["values"])
    keys = [v["key"] for v in values]
    assert keys == [
        "baseUrl",
        "signerAddress",
        "signature",
        "batchBody",
        "basicAuthUser",
        "basicAuthPassword",
    ]


def test_build_env_all_variables_are_enabled() -> None:
    env = build_env("x", _values())
    values = cast("list[dict[str, Any]]", env["values"])
    for v in values:
        assert v["enabled"] is True


def test_write_env_produces_parseable_file_with_lf_line_endings(tmp_path: Path) -> None:
    target = tmp_path / "sub" / "local.postman_environment.json"

    write_env(target, _values())

    # Fichero existe y se crea el directorio intermedio.
    assert target.is_file()

    raw = target.read_bytes()
    # Nada de CRLF, incluso si corriésemos en WSL con core.autocrlf mal puesto.
    assert b"\r\n" not in raw
    # Acaba en newline final (discreta: facilita diffs limpios).
    assert raw.endswith(b"\n")

    parsed = cast("dict[str, Any]", json.loads(raw.decode("utf-8")))
    assert parsed["name"] == "AguasDeCordoba — local"
    values = cast("list[dict[str, Any]]", parsed["values"])
    assert {v["key"]: v["value"] for v in values}["baseUrl"] == "http://localhost:3000"
