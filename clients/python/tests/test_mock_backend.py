"""
Tests del mock backend stdlib. Arrancan el servidor en un puerto efímero
dentro de un hilo y le pegan POST reales con `requests`, de modo que se
prueba el wire HTTP completo (headers, status, body) y no solo la lógica
del handler aislada.

Tres escenarios cubren el pipeline espejo de `verifyAndRecover`:
- Happy path: firma y root válidos → 200 con `{ recoveredSigner, vehiclesRoot }`.
- `vehicles_root_mismatch`: el root firmado no coincide con el recomputado → 400.
- `signer_mismatch`: el header `X-Signer` no coincide con el recovered → 401.

Los tests reutilizan `sign_batch` y `compute_vehicles_root` del propio
paquete; si esos divergen del backend real, los tests cross-language en
`test_merkle.py` lo cazan antes — aquí basta con la coherencia interna.
"""

from __future__ import annotations

import threading
from collections.abc import Generator
from typing import Any

import pytest
import requests
from eth_account import Account

from aguas_ingest.domain import build_domain
from aguas_ingest.eip712 import sign_batch
from aguas_ingest.merkle import compute_vehicles_root
from aguas_ingest.mock_backend import make_server
from aguas_ingest.types import Eip712Domain, IngestRequest, LodoBatch, VehicleEntry

_DOMAIN: Eip712Domain = build_domain(
    name="AguasDeCordoba",
    version="1",
    chain_id=1337,
    verifying_contract="0x000000000000000000000000000000000000dead",
)

_PRIVATE_KEY = "0x0000000000000000000000000000000000000000000000000000000000000042"


@pytest.fixture
def server_url() -> Generator[str, None, None]:
    """Arranca el mock en puerto efímero, devuelve la URL base, lo apaga al final."""
    server = make_server("127.0.0.1", 0, _DOMAIN)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _build_signed_request() -> tuple[IngestRequest, str, str]:
    """Construye un request válido firmado con `_PRIVATE_KEY`. Devuelve (request, sig, signer)."""
    vehicles = [
        VehicleEntry(vehicle_id="truck-01", time_iso="2026-04-16T09:00:00+00:00", weight_kg=1_200),
        VehicleEntry(vehicle_id="truck-02", time_iso="2026-04-16T10:00:00+00:00", weight_kg=950),
    ]
    batch = LodoBatch(
        batch_id="batch-mock-1",
        edar="la-golondrina",
        date_iso="2026-04-16",
        polielectrolito=1_234,
        materia_organica_bp=5_678,
        vehicles_root=compute_vehicles_root(vehicles),
        submitted_at_iso="2026-04-16T08:00:00+00:00",
    )
    signature = sign_batch(_PRIVATE_KEY, _DOMAIN, batch)
    signer_address = Account.from_key(_PRIVATE_KEY).address
    return IngestRequest(batch=batch, vehicles=vehicles), signature, signer_address


def _post(url: str, request: IngestRequest, signature: str, signer: str) -> requests.Response:
    return requests.post(
        f"{url}/v1/lodos/batches/dry-run",
        data=request.model_dump_json(by_alias=True),
        headers={
            "Content-Type": "application/json",
            "X-Signature": signature,
            "X-Signer": signer,
        },
        timeout=5,
    )


def test_happy_path_returns_200_with_recovered_signer_and_root(server_url: str) -> None:
    request, signature, signer = _build_signed_request()

    resp = _post(server_url, request, signature, signer)

    assert resp.status_code == 200
    body: dict[str, Any] = resp.json()
    assert body["recoveredSigner"].lower() == signer.lower()
    assert body["vehiclesRoot"] == request.batch.vehicles_root


def test_vehicles_root_mismatch_returns_400_with_canonical_error_code(server_url: str) -> None:
    request, signature, signer = _build_signed_request()
    # Forzamos un root inconsistente sin re-firmar: el body lleva un root
    # que no coincide con el recomputado del array vehicles → 400.
    tampered_batch = request.batch.model_copy(update={"vehicles_root": "0x" + "00" * 32})
    tampered = IngestRequest(batch=tampered_batch, vehicles=request.vehicles)

    resp = _post(server_url, tampered, signature, signer)

    assert resp.status_code == 400
    body: dict[str, Any] = resp.json()
    assert body == {
        "error": "vehicles_root_mismatch",
        "message": "Recomputed vehiclesRoot does not match the signed batch.vehiclesRoot",
    }


def test_signer_mismatch_returns_401_with_canonical_error_code(server_url: str) -> None:
    request, signature, _real_signer = _build_signed_request()
    # X-Signer apunta a una dirección distinta a la que firmó → 401.
    other_signer = Account.create().address

    resp = _post(server_url, request, signature, other_signer)

    assert resp.status_code == 401
    body: dict[str, Any] = resp.json()
    assert body["error"] == "signer_mismatch"
    assert "Recovered signer does not match X-Signer header" in body["message"]


def test_malformed_signature_returns_400_before_pipeline(server_url: str) -> None:
    """
    Espejo de la regex Zod del backend (`SIGNATURE_REGEX`): una firma con
    longitud inválida sale por validación de header (400) antes de tocar
    el pipeline criptográfico (que devolvería 401). El fixture Postman
    `malformed_signature.json` cuenta con este 400.
    """
    request, _good_sig, signer = _build_signed_request()

    resp = _post(server_url, request, "0xdeadbeef", signer)

    assert resp.status_code == 400
    body: dict[str, Any] = resp.json()
    assert body["error"] == "validation_error"
    assert "X-Signature" in body["message"]
