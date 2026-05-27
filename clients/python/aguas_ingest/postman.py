"""
Escribe un Postman environment JSON con los valores necesarios para que la
colección `AguasDeCordoba.postman_collection.json` envíe un request firmado.

La colección mantiene el body completamente en `{{batchBody}}`, de modo que
cualquier cambio en los campos de `LodoBatch` se refleja regenerando la env
desde Python sin tener que tocar la colección. Mantiene la colección estable
ante la evolución del schema.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PostmanEnvValues:
    base_url: str
    signer_address: str
    signature: str
    batch_body: str
    # Basic Auth para el Caddy del entorno protegido. Defaults vacíos para
    # retro-compat con `aguas-ingest sign --postman-env` (que no expone basic
    # auth — el subcomando `gen-postman` sí los rellena).
    basic_auth_user: str = ""
    basic_auth_password: str = ""


def build_env(name: str, values: PostmanEnvValues) -> dict[str, Any]:
    """Construye el dict Postman environment. Exportado para tests."""
    return {
        "name": name,
        "values": [
            {"key": "baseUrl", "value": values.base_url, "enabled": True},
            {"key": "signerAddress", "value": values.signer_address, "enabled": True},
            {"key": "signature", "value": values.signature, "enabled": True},
            {"key": "batchBody", "value": values.batch_body, "enabled": True},
            {"key": "basicAuthUser", "value": values.basic_auth_user, "enabled": True},
            {"key": "basicAuthPassword", "value": values.basic_auth_password, "enabled": True},
        ],
        "_postman_variable_scope": "environment",
    }


def write_env(
    path: str | Path,
    values: PostmanEnvValues,
    name: str = "AguasDeCordoba — local",
) -> None:
    """Serializa y escribe el environment. Fuerza LF para evitar CRLF en WSL."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = build_env(name, values)
    # `ensure_ascii=False` para que los acentos en el `name` no se escapen.
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    target.write_text(text, encoding="utf-8", newline="\n")
