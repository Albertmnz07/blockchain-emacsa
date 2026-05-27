"""
Mock backend stdlib del endpoint POST /v1/lodos/batches/dry-run.

Pensado para que los integradores prueben end-to-end su pipeline HTTP
(headers, status codes, forma del JSON de respuesta) contra un servidor
real, sin Docker y sin dependencias externas más allá del propio paquete
`aguas_ingest`. Ver `clients/docs/quickstart.md` (tier 2 — round-trip HTTP).

Reutiliza `compute_vehicles_root` y `recover_signer` del paquete; no hay
algoritmos duplicados. La fidelidad con el backend real abarca:

- Códigos de error idénticos a `backend/src/modules/ingest/verify.ts`:
  `vehicles_root_mismatch`, `invalid_signature`, `signer_mismatch`.
- Forma de respuesta `{ recoveredSigner, vehiclesRoot }` en 200 y
  `{ error, message }` en 4xx — espejo de `IngestError` del backend.
- Pipeline: Merkle → ecrecover → match con X-Signer.

NO simula `SignerRegistry` (igual que el dry-run real) ni la idempotencia
del POST real. Tampoco reproduce las validaciones temporales del backend
(ventana 90d/1d para `dateIso`/`submittedAtIso`): el mock prueba el wire
del cliente, esas reglas se descubren contra el dry-run real (ver tier 3).
"""

from __future__ import annotations

import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast

from aguas_ingest.eip712 import recover_signer
from aguas_ingest.merkle import compute_vehicles_root
from aguas_ingest.types import Eip712Domain, IngestRequest

_DRY_RUN_PATH = "/v1/lodos/batches/dry-run"

# Regex espejo de backend/src/modules/ingest/schemas.ts (SIGNATURE_REGEX y
# AddressSchema vía viem.isAddress). El backend valida estos headers con Zod
# antes del handler — una firma mal formada sale por aquí con 400, no por el
# pipeline criptográfico con 401. Replicarlo evita falsos 401 contra fixtures.
_SIGNATURE_REGEX = re.compile(r"^0x[0-9a-fA-F]{130}$")
_ADDRESS_REGEX = re.compile(r"^0x[0-9a-fA-F]{40}$")


def _reply_json(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _reply_error(handler: BaseHTTPRequestHandler, status: int, code: str, message: str) -> None:
    _reply_json(handler, status, {"error": code, "message": message})


def _handle_post(handler: BaseHTTPRequestHandler, domain: Eip712Domain) -> None:
    """Pipeline espejo de `backend/src/modules/ingest/verify.ts::verifyAndRecover`."""
    if handler.path != _DRY_RUN_PATH:
        _reply_error(handler, 404, "not_found", f"unknown route: {handler.path}")
        return

    try:
        length = int(handler.headers.get("Content-Length", "0"))
        raw_body = handler.rfile.read(length).decode("utf-8")
        body = cast("dict[str, Any]", json.loads(raw_body))
    except (ValueError, UnicodeDecodeError) as err:
        _reply_error(handler, 400, "invalid_body", f"body is not valid JSON: {err}")
        return

    signature = handler.headers.get("X-Signature", "")
    signer = handler.headers.get("X-Signer", "")
    if not signature or not signer:
        _reply_error(handler, 400, "missing_headers", "X-Signature and X-Signer are required")
        return
    if not _SIGNATURE_REGEX.match(signature):
        _reply_error(
            handler,
            400,
            "validation_error",
            "X-Signature must be 65 bytes (0x-prefixed, 130 hex chars)",
        )
        return
    if not _ADDRESS_REGEX.match(signer):
        _reply_error(
            handler,
            400,
            "validation_error",
            "X-Signer must be a valid 0x-prefixed Ethereum address (40 hex chars)",
        )
        return

    try:
        request = IngestRequest.model_validate(body)
    except Exception as err:  # pydantic ValidationError, AttributeError, KeyError...
        _reply_error(handler, 400, "validation_error", str(err))
        return

    recomputed = compute_vehicles_root(request.vehicles)
    if recomputed != request.batch.vehicles_root:
        _reply_error(
            handler,
            400,
            "vehicles_root_mismatch",
            "Recomputed vehiclesRoot does not match the signed batch.vehiclesRoot",
        )
        return

    try:
        recovered = recover_signer(domain, request.batch, signature)
    except Exception:
        _reply_error(handler, 401, "invalid_signature", "EIP-712 signature is malformed")
        return

    if recovered.lower() != signer.lower():
        _reply_error(
            handler,
            401,
            "signer_mismatch",
            "Recovered signer does not match X-Signer header",
        )
        return

    _reply_json(handler, 200, {"recoveredSigner": recovered, "vehiclesRoot": recomputed})


def make_server(host: str, port: int, domain: Eip712Domain) -> ThreadingHTTPServer:
    """
    Construye un `ThreadingHTTPServer` enlazado a `host:port` con el `domain` dado.

    El caller decide el lifecycle: `serve_forever()` para bloquear hasta Ctrl-C,
    o arrancar en un hilo aparte y `shutdown()` para tests con puerto efímero.
    """

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 — http.server exige este nombre
            _handle_post(self, domain)

        def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
            sys.stderr.write(f"[mock-backend] POST {self.path} → {code}\n")

    return ThreadingHTTPServer((host, port), _Handler)
