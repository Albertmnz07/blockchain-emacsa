"""
Tests de firma + recuperación EIP-712.

El caso crítico es el roundtrip: firmar con una clave privada, recuperar la
dirección que firmó y comprobar que es la del par público. Si este test
falla, el backend responderá siempre `401 signer_mismatch` al cliente.
"""

from __future__ import annotations

import pytest
from eth_account import Account

from aguas_ingest.domain import build_domain
from aguas_ingest.eip712 import recover_signer, sign_batch
from aguas_ingest.merkle import compute_vehicles_root
from aguas_ingest.types import Eip712Domain, LodoBatch, VehicleEntry

_DOMAIN = build_domain(
    name="AguasDeCordoba",
    version="1",
    chain_id=1337,
    verifying_contract="0x000000000000000000000000000000000000dead",
)

_PRIVATE_KEY = "0x0000000000000000000000000000000000000000000000000000000000000042"


def _make_batch(batch_id: str = "batch-eip712-1") -> tuple[LodoBatch, list[VehicleEntry]]:
    vehicles = [
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
    batch = LodoBatch(
        batch_id=batch_id,
        edar="la-golondrina",
        date_iso="2026-04-16",
        polielectrolito=1_234,
        materia_organica_bp=5_678,
        vehicles_root=compute_vehicles_root(vehicles),
        submitted_at_iso="2026-04-16T08:00:00+00:00",
    )
    return batch, vehicles


def test_sign_recover_roundtrip_yields_signer_address() -> None:
    batch, _ = _make_batch()
    account = Account.from_key(_PRIVATE_KEY)

    signature = sign_batch(_PRIVATE_KEY, _DOMAIN, batch)
    recovered = recover_signer(_DOMAIN, batch, signature)

    assert recovered.lower() == account.address.lower()


def test_signature_has_expected_wire_shape() -> None:
    batch, _ = _make_batch()
    signature = sign_batch(_PRIVATE_KEY, _DOMAIN, batch)
    # 0x + 130 hex chars = 65 bytes, tal y como exige el schema del backend.
    assert signature.startswith("0x")
    assert len(signature) == 2 + 130
    int(signature, 16)  # no lanza → es hex válido


def test_tampering_batch_after_signing_breaks_recovery() -> None:
    batch, _ = _make_batch()
    signature = sign_batch(_PRIVATE_KEY, _DOMAIN, batch)

    account = Account.from_key(_PRIVATE_KEY)
    tampered = batch.model_copy(update={"polielectrolito": batch.polielectrolito + 1})
    recovered = recover_signer(_DOMAIN, tampered, signature)

    assert recovered.lower() != account.address.lower()


def test_domain_drift_breaks_recovery() -> None:
    """Si el cliente firma con un `verifying_contract` distinto del backend,
    la dirección recuperada contra el dominio del backend es otra → 401."""
    batch, _ = _make_batch()
    signature = sign_batch(_PRIVATE_KEY, _DOMAIN, batch)

    drifted = Eip712Domain(
        name=_DOMAIN.name,
        version=_DOMAIN.version,
        chain_id=_DOMAIN.chain_id,
        verifying_contract="0x000000000000000000000000000000000000beef",
    )
    account = Account.from_key(_PRIVATE_KEY)
    recovered = recover_signer(drifted, batch, signature)

    assert recovered.lower() != account.address.lower()


@pytest.mark.parametrize("private_key_without_0x", [False, True])
def test_accepts_key_with_or_without_0x_prefix(private_key_without_0x: bool) -> None:
    batch, _ = _make_batch()
    key = _PRIVATE_KEY[2:] if private_key_without_0x else _PRIVATE_KEY
    signature = sign_batch(key, _DOMAIN, batch)
    recovered = recover_signer(_DOMAIN, batch, signature)
    assert recovered.lower() == Account.from_key(_PRIVATE_KEY).address.lower()
