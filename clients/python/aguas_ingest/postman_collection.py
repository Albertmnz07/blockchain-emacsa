"""
Composición de la colección Postman a partir de fixtures en disco.

Dos modos:

1. **Dry-run only** — versión versionada en git (`clients/postman/
   AguasDeCordoba.postman_collection.json`). Sin auth, sin matriz POST
   real. Es el baseline que se importa contra el `aguas-ingest mock-backend`
   o cualquier backend abierto sin Caddy delante.

2. **Matriz completa** — extensión con basic auth a nivel collection y la
   sección "POST real" de 4 requests (happy/replay/conflict/unauthorized).
   Requiere fixtures de matriz pre-generados (ver `aguas_ingest.postman_matrix`).
   Se escribe en `.out/postman/` (gitignored), generada al vuelo por
   `aguas-ingest gen-postman`.

Funciones puras: las paths se pasan por parámetro, no se hardcodean.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

# Nombres canónicos de los fixtures de matriz. Sincronizar con
# `aguas_ingest.postman_matrix.MATRIX_FIXTURE_NAMES`.
_MATRIX_NAMES: tuple[str, ...] = (
    "happy_real_post",
    "idempotent_replay",
    "conflict_real_post",
    "unauthorized_real_post",
)


def _load_fixture(fixtures_dir: Path, name: str) -> dict[str, Any]:
    return cast(
        "dict[str, Any]",
        json.loads((fixtures_dir / f"{name}.json").read_text(encoding="utf-8")),
    )


def matrix_fixtures_present(matrix_fixtures_dir: Path) -> bool:
    return all((matrix_fixtures_dir / f"{n}.json").exists() for n in _MATRIX_NAMES)


def _header_list(headers: dict[str, str]) -> list[dict[str, str]]:
    return [{"key": k, "value": v} for k, v in headers.items()]


def _body(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": "raw",
        "raw": json.dumps(payload, ensure_ascii=False, indent=2),
        "options": {"raw": {"language": "json"}},
    }


def _url_raw(endpoint: str) -> str:
    """
    URL en forma string (no objeto). Postman v2.1 acepta ambos, pero el
    objeto con `host`/`path` arrays parsea `{{baseUrl}}` y, si la variable
    contiene un path (ej. `.../api`), lo descarta porque `path` ya está
    fijado en el array. La string opaca con `{{baseUrl}}/...` la resuelve
    Postman/Newman como concatenación literal — el path en la variable se
    preserva.

    Newman además exige `host` cuando el campo `url` es objeto; un objeto
    con solo `raw` lo rechaza con "request url is empty". String puro
    funciona en ambos.
    """
    return "{{baseUrl}}" + endpoint


def _happy_dry_run_request() -> dict[str, Any]:
    """Request env-driven: usa {{signature}}, {{signerAddress}}, {{batchBody}}."""
    return {
        "name": "dry-run (env-driven happy path)",
        "event": [
            {
                "listen": "test",
                "script": {
                    "type": "text/javascript",
                    "exec": [
                        "pm.test('200 OK', () => pm.response.to.have.status(200));",
                        "const body = pm.response.json();",
                        "pm.test('recoveredSigner matches X-Signer', () => {",
                        "  pm.expect(body.recoveredSigner.toLowerCase())",
                        "    .to.equal(pm.environment.get('signerAddress').toLowerCase());",
                        "});",
                        "pm.test('vehiclesRoot echoed', () => {",
                        "  pm.expect(body.vehiclesRoot).to.match(/^0x[0-9a-fA-F]{64}$/);",
                        "});",
                    ],
                },
            }
        ],
        "request": {
            "method": "POST",
            "header": [
                {"key": "Content-Type", "value": "application/json"},
                {"key": "X-Signature", "value": "{{signature}}"},
                {"key": "X-Signer", "value": "{{signerAddress}}"},
            ],
            "body": {
                "mode": "raw",
                "raw": "{{batchBody}}",
                "options": {"raw": {"language": "json"}},
            },
            "url": _url_raw("/v1/lodos/batches/dry-run"),
        },
    }


def _dry_run_error_request(fixtures_dir: Path, fixture_name: str) -> dict[str, Any]:
    fx = _load_fixture(fixtures_dir, fixture_name)
    headers = cast("dict[str, str]", fx["headers"])
    body = cast("dict[str, Any]", fx["body"])
    exp = cast("dict[str, Any]", fx["expectation"])

    tests: list[str] = [
        f"pm.test('status {exp['status']}', () => pm.response.to.have.status({exp['status']}));",
    ]
    if "error" in exp and not str(exp["error"]).startswith("*"):
        code = exp["error"]
        tests.append(
            f"pm.test('error code is {code}', () => {{"
            f"  pm.expect(pm.response.json().error).to.equal('{code}');"
            f"}});"
        )

    return {
        "name": f"error: {fixture_name}",
        "event": [
            {"listen": "test", "script": {"type": "text/javascript", "exec": tests}}
        ],
        "request": {
            "method": "POST",
            "header": _header_list(headers),
            "body": _body(body),
            "url": _url_raw("/v1/lodos/batches/dry-run"),
        },
    }


def _matrix_request(
    matrix_fixtures_dir: Path,
    fixture_name: str,
    request_label: str,
    extra_tests: list[str] | None = None,
) -> dict[str, Any]:
    """
    Request derivado de un fixture de matriz. A diferencia de los dry-run
    estáticos, lee `endpoint` del propio fixture (la matriz usa
    `/v1/lodos/batches`, no `/dry-run`).
    """
    fx = _load_fixture(matrix_fixtures_dir, fixture_name)
    headers = cast("dict[str, str]", fx["headers"])
    body = cast("dict[str, Any]", fx["body"])
    exp = cast("dict[str, Any]", fx["expectation"])
    endpoint = cast("str", fx.get("endpoint", "/v1/lodos/batches"))

    tests: list[str] = [
        f"pm.test('status {exp['status']}', () => pm.response.to.have.status({exp['status']}));",
    ]
    if "error" in exp and not str(exp["error"]).startswith("*"):
        code = exp["error"]
        tests.append(
            f"pm.test('error code is {code}', () => {{"
            f"  pm.expect(pm.response.json().error).to.equal('{code}');"
            f"}});"
        )
    if extra_tests:
        tests.extend(extra_tests)

    return {
        "name": request_label,
        "event": [
            {"listen": "test", "script": {"type": "text/javascript", "exec": tests}}
        ],
        "request": {
            "method": "POST",
            "header": _header_list(headers),
            "body": _body(body),
            "url": _url_raw(endpoint),
        },
    }


def _basic_auth_block() -> dict[str, Any]:
    """
    Basic Auth a nivel de colección. Postman v2.1 lo aplica a todos los
    requests. Si las env vars están vacías, Postman manda `Authorization:
    Basic Og==` (base64 de `:`); el mock-backend ignora `Authorization`,
    así que es no-op contra el mock. Caddy del entorno protegido lee
    el header y deja pasar (o rechaza con 401 si las creds están mal).
    """
    return {
        "type": "basic",
        "basic": [
            {"key": "username", "value": "{{basicAuthUser}}", "type": "string"},
            {"key": "password", "value": "{{basicAuthPassword}}", "type": "string"},
        ],
    }


def _matrix_section(matrix_fixtures_dir: Path) -> dict[str, Any]:
    return {
        "name": "POST real — matriz completa",
        "description": (
            "Cuatro estados que sólo se reproducen contra un backend real con "
            "registry poblado y la key buena en `AGUAS_PRIVATE_KEY`. Orden "
            "load-bearing — el runner de Postman respeta el orden de la "
            "colección. Si lo lanzas individualmente, hazlo en este orden: "
            "happy → replay → conflict → unauthorized."
        ),
        "item": [
            _matrix_request(
                matrix_fixtures_dir,
                "happy_real_post",
                "real: happy_real_post (201 Created)",
                extra_tests=[
                    "const body = pm.response.json();",
                    "pm.test('txHash returned', () => {",
                    "  pm.expect(body.txHash).to.match(/^0x[0-9a-fA-F]{64}$/);",
                    "});",
                    "// Capturar el txHash para que idempotent_replay lo compare.",
                    "pm.environment.set('matrix_first_tx_hash', body.txHash);",
                ],
            ),
            _matrix_request(
                matrix_fixtures_dir,
                "idempotent_replay",
                "real: idempotent_replay (200, post #143)",
                extra_tests=[
                    "const body = pm.response.json();",
                    "pm.test('txHash matches the original create (idempotent replay)', () => {",
                    "  pm.expect(body.txHash).to.equal(pm.environment.get('matrix_first_tx_hash'));",
                    "});",
                ],
            ),
            _matrix_request(
                matrix_fixtures_dir,
                "conflict_real_post",
                "real: conflict_real_post (409 batch_id_conflict)",
            ),
            _matrix_request(
                matrix_fixtures_dir,
                "unauthorized_real_post",
                "real: unauthorized_real_post (403 signer_not_authorized)",
            ),
        ],
    }


def _description(matrix: bool) -> str:
    base = (
        "Colección para validar la integración EMACSA ↔ Aguas de Córdoba.\n\n"
        "## Variables de entorno\n"
        "- `baseUrl`: URL base (default `http://127.0.0.1:41337` para el `aguas-ingest mock-backend` local).\n"
        "- `signerAddress`, `signature`, `batchBody`: los rellena "
        "`aguas-ingest sign --postman-env .out/env.postman.json`.\n"
    )
    if matrix:
        base += (
            "- `basicAuthUser`, `basicAuthPassword`: Caddy Basic Auth del entorno protegido. "
            "Vacíos contra el mock local (mock ignora `Authorization`).\n"
        )
    base += (
        "\n## Reintentos y `submittedAtIso`\n"
        "Si un POST real devuelve `5xx`, **reenviar los mismos bytes** con el mismo "
        "`X-Signature`. Regenerar `submittedAtIso` o volver a firmar cambia el "
        "`dataHash` → `409 batch_id_conflict`. Replay idéntico bit-a-bit → 200 con "
        "el `txHash` original (RFC 9110 §15.3.2; PR #143)."
    )
    return base


def _base_collection(static_fixtures_dir: Path, matrix: bool) -> dict[str, Any]:
    return {
        "info": {
            "name": "AguasDeCordoba — Ingest" + (" (matriz completa)" if matrix else ""),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            "description": _description(matrix),
        },
        "item": [
            {
                "name": "Dry-run — happy path",
                "item": [_happy_dry_run_request()],
            },
            {
                "name": "Dry-run — error fixtures",
                "description": (
                    "Payloads firmados por el cliente Python con mutaciones "
                    "intencionales para disparar cada código de error. Los "
                    "fixtures viven en `clients/postman/fixtures/`."
                ),
                "item": [
                    _dry_run_error_request(static_fixtures_dir, "wrong_vehicles_root"),
                    _dry_run_error_request(static_fixtures_dir, "tampered_after_signing"),
                    _dry_run_error_request(static_fixtures_dir, "malformed_signature"),
                    _dry_run_error_request(static_fixtures_dir, "bad_date_iso"),
                ],
            },
        ],
    }


def build_dry_run_only_collection(static_fixtures_dir: Path) -> dict[str, Any]:
    """Versión versionada en git: 5 requests, sin matriz, sin auth."""
    return _base_collection(static_fixtures_dir, matrix=False)


def build_matrix_collection(
    static_fixtures_dir: Path,
    matrix_fixtures_dir: Path,
) -> dict[str, Any]:
    """
    Versión extendida: 5 requests dry-run + 4 requests POST real + basic auth
    a nivel collection. Los fixtures de matriz tienen que existir en
    `matrix_fixtures_dir` o se levanta `RuntimeError`.
    """
    if not matrix_fixtures_present(matrix_fixtures_dir):
        missing = [
            n for n in _MATRIX_NAMES if not (matrix_fixtures_dir / f"{n}.json").exists()
        ]
        raise RuntimeError(
            "matrix fixtures missing: "
            f"{', '.join(missing)} (en {matrix_fixtures_dir})"
        )
    collection = _base_collection(static_fixtures_dir, matrix=True)
    collection["auth"] = _basic_auth_block()
    collection["item"].append(_matrix_section(matrix_fixtures_dir))
    return collection


def write_collection(collection: dict[str, Any], path: Path) -> None:
    """Serializa la colección con LF + indent 2."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(collection, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
