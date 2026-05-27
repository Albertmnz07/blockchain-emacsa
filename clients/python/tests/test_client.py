"""
Tests unitarios del cliente HTTP. No hablan con ninguna red: mockeamos
`requests.post` para asertar que el cliente construye la URL, headers y body
correctos, y que mapea errores del API a `IngestApiError`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

import pytest

from aguas_ingest.client import (
    DryRunResponse,
    IngestApiError,
    IngestResponse,
    post_dry_run,
    post_ingest,
)
from aguas_ingest.merkle import compute_vehicles_root
from aguas_ingest.types import IngestRequest, LodoBatch, VehicleEntry


@dataclass
class _FakeResponse:
    status_code: int
    _json: dict[str, Any]
    text: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> dict[str, Any]:
        return self._json


def _valid_request() -> IngestRequest:
    vehicles = [
        VehicleEntry(vehicle_id="truck-01", time_iso="2026-04-16T09:00:00+00:00", weight_kg=1_200),
    ]
    batch = LodoBatch(
        batch_id="batch-client-1",
        edar="la-golondrina",
        date_iso="2026-04-16",
        polielectrolito=100,
        materia_organica_bp=200,
        vehicles_root=compute_vehicles_root(vehicles),
        submitted_at_iso="2026-04-16T08:00:00+00:00",
    )
    return IngestRequest(batch=batch, vehicles=vehicles)


def test_post_dry_run_hits_the_right_url_headers_and_parses_body() -> None:
    req = _valid_request()
    fake = _FakeResponse(
        status_code=200,
        _json={"recoveredSigner": "0xabc", "vehiclesRoot": req.batch.vehicles_root},
    )

    with patch("aguas_ingest.client.requests.post", return_value=fake) as m:
        out = post_dry_run(
            base_url="http://localhost:3000",
            request=req,
            signature="0x" + "aa" * 65,
            signer_address="0xabc",
        )

    assert isinstance(out, DryRunResponse)
    assert out.recovered_signer == "0xabc"
    assert out.vehicles_root == req.batch.vehicles_root

    ((url,), kwargs) = m.call_args
    assert url == "http://localhost:3000/v1/lodos/batches/dry-run"
    assert kwargs["headers"]["X-Signature"] == "0x" + "aa" * 65
    assert kwargs["headers"]["X-Signer"] == "0xabc"
    assert kwargs["headers"]["Content-Type"] == "application/json"
    # El body tiene que ir como string JSON exacto (idempotencia).
    assert isinstance(kwargs["data"], str)
    assert '"batchId":"batch-client-1"' in kwargs["data"]


def test_post_ingest_maps_201_body_to_IngestResponse() -> None:
    req = _valid_request()
    fake = _FakeResponse(
        status_code=201,
        _json={"batchId": "batch-client-1", "txHash": "0x" + "bb" * 32},
    )

    with patch("aguas_ingest.client.requests.post", return_value=fake):
        out = post_ingest(
            base_url="http://localhost:3000/",
            request=req,
            signature="0x" + "aa" * 65,
            signer_address="0xdef",
        )

    assert isinstance(out, IngestResponse)
    assert out.batch_id == "batch-client-1"
    assert out.tx_hash == "0x" + "bb" * 32


def test_api_error_raises_IngestApiError_with_code_and_status() -> None:
    req = _valid_request()
    fake = _FakeResponse(
        status_code=400,
        _json={"error": "vehicles_root_mismatch", "message": "nope"},
    )

    with patch("aguas_ingest.client.requests.post", return_value=fake):
        with pytest.raises(IngestApiError) as exc:
            post_dry_run(
                base_url="http://localhost:3000",
                request=req,
                signature="0x" + "aa" * 65,
                signer_address="0xabc",
            )

    assert exc.value.status_code == 400
    assert exc.value.code == "vehicles_root_mismatch"


def test_api_error_handles_non_json_body() -> None:
    req = _valid_request()

    class _NonJson:
        status_code = 502
        ok = False
        text = "bad gateway"

        def json(self) -> dict[str, Any]:
            raise ValueError("not json")

    with patch("aguas_ingest.client.requests.post", return_value=_NonJson()):
        with pytest.raises(IngestApiError) as exc:
            post_ingest(
                base_url="http://localhost:3000",
                request=req,
                signature="0x" + "aa" * 65,
                signer_address="0xabc",
            )

    assert exc.value.status_code == 502
    assert exc.value.code == "unknown_error"
