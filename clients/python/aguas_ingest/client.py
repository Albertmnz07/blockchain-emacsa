"""
Cliente HTTP fino sobre `requests`. Dos métodos: `post_dry_run` y `post_ingest`.

Ninguno reintenta automáticamente — el contrato de idempotencia exige firmar
una vez por batch y reenviar bit-a-bit los mismos bytes en cada reintento
(ver `docs/stack/backend/api-ingest.md` sección "Idempotencia"). El caller
es quien orquesta backoff + reenvío.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from aguas_ingest.types import IngestRequest


@dataclass(frozen=True)
class IngestResponse:
    """Respuesta deserializada del POST real (`201 Created`)."""

    batch_id: str
    tx_hash: str


@dataclass(frozen=True)
class DryRunResponse:
    """Respuesta del endpoint de verificación (`200 OK`)."""

    recovered_signer: str
    vehicles_root: str


class IngestApiError(RuntimeError):
    """
    Error HTTP tipado devuelto por la API. Expone `status_code` y el `code`
    estable del contrato (p. ej. `vehicles_root_mismatch`, `signer_mismatch`,
    `signer_not_authorized`, `batch_id_conflict`).
    """

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(f"{status_code} {code}: {message}")
        self.status_code = status_code
        self.code = code
        self.api_message = message


def _request_json(request: IngestRequest) -> str:
    """
    Serializa el batch al JSON exacto que viaja en el wire. Usa
    `model_dump_json(by_alias=True)` para producir camelCase + uint256 como
    string. El body resultante tiene que ser idéntico bit-a-bit en cada
    reintento del mismo batchId.
    """
    return request.model_dump_json(by_alias=True)


def _headers(signature: str, signer_address: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Signature": signature,
        "X-Signer": signer_address,
    }


def _raise_for_api_error(response: requests.Response) -> None:
    if response.ok:
        return
    try:
        body: dict[str, Any] = response.json()
        code = str(body.get("error", "unknown_error"))
        message = str(body.get("message", ""))
    except ValueError:
        code = "unknown_error"
        message = response.text[:500]
    raise IngestApiError(response.status_code, code, message)


def post_dry_run(
    base_url: str,
    request: IngestRequest,
    signature: str,
    signer_address: str,
    timeout_s: float = 10.0,
    auth: tuple[str, str] | None = None,
) -> DryRunResponse:
    """
    Llama a `POST {base_url}/v1/lodos/batches/dry-run`. No persiste nada.

    `auth` es `(usuario, password)` para HTTP Basic Auth — necesaria cuando el
    backend está detrás de un reverse-proxy protegido (Caddy, nginx, ngrok).
    `requests` añade el header `Authorization: Basic` por nosotros. None = sin
    Basic Auth (mock local, backend expuesto sin proxy).
    """
    url = f"{base_url.rstrip('/')}/v1/lodos/batches/dry-run"
    resp = requests.post(
        url,
        data=_request_json(request),
        headers=_headers(signature, signer_address),
        timeout=timeout_s,
        auth=auth,
    )
    _raise_for_api_error(resp)
    body: dict[str, Any] = resp.json()
    return DryRunResponse(
        recovered_signer=str(body["recoveredSigner"]),
        vehicles_root=str(body["vehiclesRoot"]),
    )


def post_ingest(
    base_url: str,
    request: IngestRequest,
    signature: str,
    signer_address: str,
    timeout_s: float = 30.0,
    auth: tuple[str, str] | None = None,
) -> IngestResponse:
    """Llama a `POST {base_url}/v1/lodos/batches`. Persiste + envía tx."""
    url = f"{base_url.rstrip('/')}/v1/lodos/batches"
    resp = requests.post(
        url,
        data=_request_json(request),
        headers=_headers(signature, signer_address),
        timeout=timeout_s,
        auth=auth,
    )
    _raise_for_api_error(resp)
    body: dict[str, Any] = resp.json()
    return IngestResponse(
        batch_id=str(body["batchId"]),
        tx_hash=str(body["txHash"]),
    )
