"""
Genera los fixtures estáticos de `clients/postman/fixtures/`. Cada fixture
produce un error concreto contra el endpoint `/v1/lodos/batches/dry-run` (y
por la invariante del backend, el mismo error contra el POST real).

Ejecutar desde `clients/python`:
    AGUAS_FIXTURE_PRIVATE_KEY=0x... uv run python scripts/gen_postman_fixtures.py

La key se lee siempre del entorno — nunca se hard-codea para evitar que un
patrón "es solo para fixtures" derive en commits de keys reales. Cualquier
valor arbitrario sirve (los fixtures que dependen de la firma siguen
disparando su error esperado independientemente de quién haya firmado).
Para reproducir bit-a-bit los fixtures versionados, usar la misma key que
quien generó la versión actual; en cualquier otro caso se produce un diff
intencionado.

El batch y el dominio EIP-712 sí están fijos en el script (dev-local) — son
placeholders documentados, no secretos.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from eth_account import Account

from aguas_ingest.domain import build_domain
from aguas_ingest.eip712 import sign_batch
from aguas_ingest.merkle import compute_vehicles_root
from aguas_ingest.types import IngestRequest, LodoBatch, VehicleEntry


def _load_fixture_key() -> str:
    key = os.environ.get("AGUAS_FIXTURE_PRIVATE_KEY")
    if key is None or key == "":
        print(
            "error: AGUAS_FIXTURE_PRIVATE_KEY no está en el entorno.\n"
            "  Para regenerar fixtures, exporta una privada arbitraria; "
            "no se persiste en disco ni en git. Ejemplo:\n"
            "    export AGUAS_FIXTURE_PRIVATE_KEY=$(uv run aguas-ingest keygen "
            "| awk -F= '/AGUAS_PRIVATE_KEY/{print $2}')",
            file=sys.stderr,
        )
        sys.exit(2)
    return key


_PRIVATE_KEY = _load_fixture_key()
_ADDRESS = Account.from_key(_PRIVATE_KEY).address

_DOMAIN = build_domain(
    name="AguasDeCordoba",
    version="1",
    chain_id=1337,
    verifying_contract="0x000000000000000000000000000000000000dead",
)


def _baseline() -> tuple[IngestRequest, str]:
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
        batch_id="batch-postman-fixture-001",
        edar="la-golondrina",
        date_iso="2026-04-16",
        polielectrolito=1_234,
        materia_organica_bp=5_678,
        vehicles_root=compute_vehicles_root(vehicles),
        submitted_at_iso="2026-04-16T08:00:00+00:00",
    )
    request = IngestRequest(batch=batch, vehicles=vehicles)
    signature = sign_batch(_PRIVATE_KEY, _DOMAIN, batch)
    return request, signature


def _wrap(
    body: dict[str, object],
    signature: str,
    signer: str,
    expected: dict[str, object],
) -> dict[str, object]:
    return {
        "$description": (
            "Fixture para la colección Postman. `expectation` documenta el status y "
            "el `error` code que el endpoint debería devolver."
        ),
        "headers": {
            "Content-Type": "application/json",
            "X-Signature": signature,
            "X-Signer": signer,
        },
        "body": body,
        "expectation": expected,
    }


def main() -> None:
    request, signature = _baseline()
    body = json.loads(request.model_dump_json(by_alias=True))

    out_dir = Path(__file__).resolve().parent.parent.parent / "postman" / "fixtures"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) `wrong_vehicles_root`: firma válida sobre el struct original, pero en
    #    el body al vuelo machacamos `vehiclesRoot`. El backend recomputa y
    #    detecta divergencia → 400 vehicles_root_mismatch.
    tampered_root = json.loads(json.dumps(body))
    tampered_root["batch"]["vehiclesRoot"] = (
        "0x1111111111111111111111111111111111111111111111111111111111111111"
    )
    (out_dir / "wrong_vehicles_root.json").write_text(
        json.dumps(
            _wrap(
                tampered_root,
                signature,
                _ADDRESS,
                {"status": 400, "error": "vehicles_root_mismatch"},
            ),
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    # 2) `tampered_after_signing`: se modifica polielectrolito tras firmar. El
    #    Merkle sigue coincidiendo (vehicles intactos) pero el struct no → la
    #    firma recupera OTRA dirección distinta a X-Signer → 401 signer_mismatch.
    tampered_field = json.loads(json.dumps(body))
    tampered_field["batch"]["polielectrolito"] = "999999"
    (out_dir / "tampered_after_signing.json").write_text(
        json.dumps(
            _wrap(
                tampered_field,
                signature,
                _ADDRESS,
                {"status": 401, "error": "signer_mismatch"},
            ),
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    # 3) `malformed_signature`: signature con longitud inválida → Zod 400.
    (out_dir / "malformed_signature.json").write_text(
        json.dumps(
            _wrap(
                body,
                "0xdeadbeef",
                _ADDRESS,
                {"status": 400, "error": "*any Zod error"},
            ),
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    # 4) `bad_date_iso`: dateIso no cumple el patrón YYYY-MM-DD → Zod 400.
    bad_date = json.loads(json.dumps(body))
    bad_date["batch"]["dateIso"] = "16/04/2026"
    (out_dir / "bad_date_iso.json").write_text(
        json.dumps(
            _wrap(bad_date, signature, _ADDRESS, {"status": 400, "error": "*any Zod error"}),
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    # 5) `happy_baseline`: fixture del caso correcto. Útil como referencia
    #    del body que espera el endpoint y para validar la environment.
    (out_dir / "happy_baseline.json").write_text(
        json.dumps(
            _wrap(body, signature, _ADDRESS, {"status": 200}),
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print(f"fixtures escritos en {out_dir}")


if __name__ == "__main__":
    main()
