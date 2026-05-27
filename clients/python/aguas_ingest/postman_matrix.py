"""
Construcción de la matriz de fixtures POST real para Postman. Cuatro estados
que no cubre el set estático (centrado en errores cripto del dry-run):

  1. happy_real_post       → 201 Created            (batchId nuevo, key buena)
  2. idempotent_replay     → 200 OK   (post PR #143) (mismos bytes que el #1)
  3. conflict_real_post    → 409 batch_id_conflict   (mismo batchId, body distinto)
  4. unauthorized_real_post → 403 signer_not_authorized (key ad-hoc no registrada)

Funciones puras — la entrada es key + dominio + timestamp; el output es un
dict en memoria. El I/O (lectura de env, escritura a disco) lo hacen los
callers (`scripts/gen_postman_matrix.py` y `_cmd_gen_postman` de la CLI).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

from eth_account import Account

from aguas_ingest.eip712 import sign_batch
from aguas_ingest.merkle import compute_vehicles_root
from aguas_ingest.types import Eip712Domain, IngestRequest, LodoBatch, VehicleEntry

# Nombres canónicos que la colección Postman busca cuando arma la sección
# "POST real — matriz completa". Si añades/quitas un fixture, sincroniza
# con `aguas_ingest/postman_collection.py:_MATRIX_NAMES`.
MATRIX_FIXTURE_NAMES: Final[tuple[str, ...]] = (
    "happy_real_post",
    "idempotent_replay",
    "conflict_real_post",
    "unauthorized_real_post",
)


def _baseline_vehicles() -> list[VehicleEntry]:
    return [
        VehicleEntry(
            vehicle_id="truck-01",
            time_iso="2026-04-16T09:00:00+00:00",
            weight_kg=1_200,
        ),
        VehicleEntry(
            vehicle_id="truck-02",
            time_iso="2026-04-16T10:00:00+00:00",
            weight_kg=950,
        ),
    ]


def _build_request(batch_id: str, polielectrolito: int) -> IngestRequest:
    vehicles = _baseline_vehicles()
    batch = LodoBatch(
        batch_id=batch_id,
        edar="la-golondrina",
        date_iso="2026-04-16",
        polielectrolito=polielectrolito,
        materia_organica_bp=5_678,
        vehicles_root=compute_vehicles_root(vehicles),
        submitted_at_iso="2026-04-16T08:00:00+00:00",
    )
    return IngestRequest(batch=batch, vehicles=vehicles)


def _wrap(
    *,
    body: dict[str, Any],
    signature: str,
    signer: str,
    endpoint: str,
    expected: dict[str, Any],
    description: str,
) -> dict[str, Any]:
    return {
        "$description": description,
        "endpoint": endpoint,
        "headers": {
            "Content-Type": "application/json",
            "X-Signature": signature,
            "X-Signer": signer,
        },
        "body": body,
        "expectation": expected,
    }


def build_matrix(
    *,
    domain: Eip712Domain,
    good_private_key: str,
    bad_private_key: str,
    timestamp: int,
) -> dict[str, dict[str, Any]]:
    """
    Construye los 4 fixtures de matriz en memoria. Función pura: misma entrada
    produce mismo output (modulo `Account.from_key` siendo determinista).

    `good_private_key` se usa para los 3 primeros fixtures (happy/replay/conflict);
    su address tiene que estar en SignerRegistry del entorno de destino para que
    happy y replay terminen en 201/200 (sin la whitelist, dan 403 igual que el
    cuarto fixture).

    `bad_private_key` se usa solo para `unauthorized_real_post`. Se espera que
    NO esté en SignerRegistry — el caller la genera con `Account.create()` para
    garantizarlo.
    """
    good_address = Account.from_key(good_private_key).address
    bad_address = Account.from_key(bad_private_key).address

    happy_batch_id = f"batch-postman-matrix-{timestamp}"

    # 1) happy_real_post: P1 firmado por la key buena, batchId único.
    happy_request = _build_request(happy_batch_id, polielectrolito=1_234)
    happy_signature = sign_batch(good_private_key, domain, happy_request.batch)
    happy_body = json.loads(happy_request.model_dump_json(by_alias=True))

    # 2) idempotent_replay: bytes idénticos al #1. Tras PR #143 → 200, no 201.
    #    Mismo body, misma firma — el backend reconoce el dataHash y devuelve
    #    el txHash original sin re-enviar tx on-chain.

    # 3) conflict_real_post: P2 = P1 con `polielectrolito` mutado, mismo
    #    batchId, refirmado con la key buena (la firma cubre el struct).
    #    El backend detecta dataHash distinto bajo el mismo batchId → 409.
    conflict_request = _build_request(happy_batch_id, polielectrolito=9_999)
    conflict_signature = sign_batch(good_private_key, domain, conflict_request.batch)
    conflict_body = json.loads(conflict_request.model_dump_json(by_alias=True))

    # 4) unauthorized_real_post: batchId distinto + key ad-hoc no registrada.
    #    El 403 se dispara en service.ts:89-94 ANTES de la idempotencia.
    unauthorized_batch_id = f"batch-postman-matrix-{timestamp}-unauth"
    unauthorized_request = _build_request(unauthorized_batch_id, polielectrolito=1_234)
    unauthorized_signature = sign_batch(bad_private_key, domain, unauthorized_request.batch)
    unauthorized_body = json.loads(unauthorized_request.model_dump_json(by_alias=True))

    return {
        "happy_real_post": _wrap(
            body=happy_body,
            signature=happy_signature,
            signer=good_address,
            endpoint="/v1/lodos/batches",
            expected={"status": 201},
            description=(
                "Primer POST real con la key buena. 201 Created con un txHash "
                "nuevo. El test de Postman captura ese txHash en la environment "
                "para que el siguiente request (idempotent_replay) lo compare."
            ),
        ),
        "idempotent_replay": _wrap(
            body=happy_body,
            signature=happy_signature,
            signer=good_address,
            endpoint="/v1/lodos/batches",
            expected={"status": 200},
            description=(
                "Replay del happy: mismos bytes (mismo body, misma firma). Tras "
                "PR #143 el backend devuelve 200 (no 201) y echo del txHash "
                "original — RFC 9110 §15.3.2 reserva 201 para creación de "
                "recurso. Antes del merge el assert falla con 201."
            ),
        ),
        "conflict_real_post": _wrap(
            body=conflict_body,
            signature=conflict_signature,
            signer=good_address,
            endpoint="/v1/lodos/batches",
            expected={"status": 409, "error": "batch_id_conflict"},
            description=(
                "Mismo batchId que el happy con `polielectrolito` cambiado a "
                "9999 y refirmado. dataHash distinto bajo batchId existente → "
                "409 batch_id_conflict. Demuestra que la idempotencia es "
                "content-addressed, no batchId-only."
            ),
        ),
        "unauthorized_real_post": _wrap(
            body=unauthorized_body,
            signature=unauthorized_signature,
            signer=bad_address,
            endpoint="/v1/lodos/batches",
            expected={"status": 403, "error": "signer_not_authorized"},
            description=(
                "Firma criptográficamente válida bajo el mismo dominio EIP-712 "
                "pero la address recuperada NO está en SignerRegistry on-chain. "
                "El backend rechaza con 403 antes de tocar idempotencia ni "
                "consultar DB."
            ),
        ),
    }


def write_matrix(out_dir: Path, fixtures: dict[str, dict[str, Any]]) -> None:
    """Serializa cada fixture a `<out_dir>/<name>.json` con LF + indent 2."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, fixture in fixtures.items():
        target = out_dir / f"{name}.json"
        target.write_text(
            json.dumps(fixture, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
