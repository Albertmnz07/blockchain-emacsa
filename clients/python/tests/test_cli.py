"""
Tests del CLI. Ejercitamos `keygen`, `sign` → `verify` (roundtrip) y la
interacción con `.env`. `send` se testea a nivel unitario en `test_client.py`
vía mocks de `requests`; aquí nos quedamos en flujo puro local.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from eth_account import Account
from pydantic import ValidationError

from aguas_ingest.cli import main
from aguas_ingest.types import LodoBatch, VehicleEntry

_PRIVATE_KEY = "0x0000000000000000000000000000000000000000000000000000000000000042"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    """Configura el entorno EIP-712 por test; evita colisiones con un `.env` real."""
    monkeypatch.setenv("AGUAS_EIP712_NAME", "AguasDeCordoba")
    monkeypatch.setenv("AGUAS_EIP712_VERSION", "1")
    monkeypatch.setenv("AGUAS_CHAIN_ID", "1337")
    monkeypatch.setenv(
        "AGUAS_VERIFYING_CONTRACT",
        "0x000000000000000000000000000000000000dead",
    )
    monkeypatch.setenv("AGUAS_PRIVATE_KEY", _PRIVATE_KEY)
    monkeypatch.delenv("AGUAS_BASE_URL", raising=False)


def _unsigned_batch_file(tmp_path: Path, batch_id: str = "batch-cli-1") -> Path:
    path = tmp_path / "batch.json"
    path.write_text(
        json.dumps(
            {
                "batch": {
                    "batchId": batch_id,
                    "edar": "la-golondrina",
                    "dateIso": "2026-04-16",
                    "polielectrolito": "100",
                    "materiaOrganicaBp": "200",
                    "submittedAtIso": "2026-04-16T08:00:00+00:00",
                },
                "vehicles": [
                    {
                        "vehicleId": "truck-01",
                        "timeIso": "2026-04-16T09:00:00+00:00",
                        "weightKg": "1200",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_keygen_prints_address_and_private_key(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["keygen"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "# Signer address: 0x" in out
    assert "AGUAS_PRIVATE_KEY=0x" in out


def test_sign_writes_envelope_with_computed_root_and_signature(tmp_path: Path) -> None:
    unsigned = _unsigned_batch_file(tmp_path)
    envelope_path = tmp_path / "signed.json"

    rc = main(["sign", "--batch", str(unsigned), "--out", str(envelope_path)])

    assert rc == 0
    envelope = json.loads(envelope_path.read_text(encoding="utf-8"))

    expected_signer = Account.from_key(_PRIVATE_KEY).address
    assert envelope["signerAddress"].lower() == expected_signer.lower()
    assert envelope["signature"].startswith("0x")
    assert len(envelope["signature"]) == 2 + 130

    # Ha metido vehiclesRoot en el batch firmado.
    assert envelope["request"]["batch"]["vehiclesRoot"].startswith("0x")
    # Dominio volcado tal cual.
    assert envelope["domain"]["name"] == "AguasDeCordoba"
    assert envelope["domain"]["chainId"] == 1337


def test_sign_plus_verify_roundtrip(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    unsigned = _unsigned_batch_file(tmp_path)
    envelope_path = tmp_path / "signed.json"

    assert main(["sign", "--batch", str(unsigned), "--out", str(envelope_path)]) == 0
    capsys.readouterr()  # drop stderr del sign

    rc = main(["verify", "--envelope", str(envelope_path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "ok" in out


def test_verify_fails_when_envelope_is_tampered(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    unsigned = _unsigned_batch_file(tmp_path)
    envelope_path = tmp_path / "signed.json"
    assert main(["sign", "--batch", str(unsigned), "--out", str(envelope_path)]) == 0
    capsys.readouterr()

    # Tampereamos el polielectrolito del request manteniendo la firma original.
    envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
    envelope["request"]["batch"]["polielectrolito"] = "999999"
    envelope_path.write_text(json.dumps(envelope), encoding="utf-8")

    rc = main(["verify", "--envelope", str(envelope_path)])
    err = capsys.readouterr().err

    assert rc == 1
    assert "NO coincide" in err


def test_sign_with_postman_env_writes_env_file(tmp_path: Path) -> None:
    unsigned = _unsigned_batch_file(tmp_path)
    envelope_path = tmp_path / "signed.json"
    env_path = tmp_path / "local.postman_environment.json"

    rc = main(
        [
            "sign",
            "--batch",
            str(unsigned),
            "--out",
            str(envelope_path),
            "--postman-env",
            str(env_path),
            "--base-url",
            "http://staging.local:3000",
        ]
    )

    assert rc == 0
    env = json.loads(env_path.read_text(encoding="utf-8"))
    values = {v["key"]: v["value"] for v in env["values"]}
    assert values["baseUrl"] == "http://staging.local:3000"
    assert values["signerAddress"].lower() == Account.from_key(_PRIVATE_KEY).address.lower()
    assert values["signature"].startswith("0x")
    # batchBody tiene que ser un JSON válido parseable de nuevo (string en la env).
    body = json.loads(values["batchBody"])
    assert body["batch"]["batchId"] == "batch-cli-1"


def test_missing_private_key_exits_with_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("AGUAS_PRIVATE_KEY", raising=False)
    unsigned = _unsigned_batch_file(tmp_path)
    envelope_path = tmp_path / "signed.json"

    with pytest.raises(SystemExit) as exc:
        main(["sign", "--batch", str(unsigned), "--out", str(envelope_path)])

    assert exc.value.code == 2
    assert "AGUAS_PRIVATE_KEY" in capsys.readouterr().err


def test_types_and_envelope_match_domain_leak(tmp_path: Path) -> None:
    """
    Guarda estructural: el signed envelope contiene `domain` + `request` +
    `signature` + `signerAddress` y nada más. Cualquier key extra delata un
    cambio que romperá a consumidores aguas abajo (Postman, `verify`).
    """
    unsigned = _unsigned_batch_file(tmp_path)
    envelope_path = tmp_path / "signed.json"
    assert main(["sign", "--batch", str(unsigned), "--out", str(envelope_path)]) == 0

    envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
    assert set(envelope.keys()) == {"domain", "request", "signature", "signerAddress"}


def test_types_model_are_frozen() -> None:
    """
    Aserción concreta: el LodoBatch firmado no debe poder mutarse in-place.
    Pydantic v2 con `frozen=True` lanza `ValidationError` en el set-attr,
    no una `Exception` genérica — si cambiase a otro tipo (TypeError, etc.)
    querríamos enterarnos.
    """
    batch = LodoBatch(
        batch_id="x",
        edar="y",
        date_iso="2026-04-16",
        polielectrolito=0,
        materia_organica_bp=0,
        vehicles_root="0x" + "0" * 64,
        submitted_at_iso="2026-04-16T08:00:00+00:00",
    )
    with pytest.raises(ValidationError):
        batch.polielectrolito = 1  # type: ignore[misc]

    vehicle = VehicleEntry(
        vehicle_id="v",
        time_iso="2026-04-16T08:00:00+00:00",
        weight_kg=0,
    )
    with pytest.raises(ValidationError):
        vehicle.weight_kg = 1  # type: ignore[misc]

    # Evita que el cleanup de pytest se queje por monkeypatch sin uso.
    os.environ.get("AGUAS_PRIVATE_KEY", "")
