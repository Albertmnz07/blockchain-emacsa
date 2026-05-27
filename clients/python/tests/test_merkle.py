"""
Tests del Merkle del cliente.

Dos capas:
  1. Vectores hand-rolled locales (como en el backend) que ejercitan casos
     semánticos con asserts explícitos sobre la construcción.
  2. Vectores compartidos `clients/shared-vectors/merkle.json` generados por
     el backend (fuente de la verdad). Si los dos lados divergen en el
     algoritmo, estos tests fallan antes de que el cliente salga a producción
     con firmas incompatibles.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

import pytest
from eth_abi.abi import encode as abi_encode
from eth_utils.crypto import keccak

from aguas_ingest.merkle import compute_vehicles_root
from aguas_ingest.types import VehicleEntry

_SHARED_VECTORS_PATH = (
    Path(__file__).resolve().parent.parent.parent / "shared-vectors" / "merkle.json"
)


class _WireVehicle(TypedDict):
    vehicleId: str
    timeIso: str
    weightKg: str


class _SharedCase(TypedDict):
    name: str
    vehicles: list[_WireVehicle]
    expectedRoot: str


class _SharedVectors(TypedDict):
    cases: list[_SharedCase]

EMPTY_ROOT = "0x" + ("00" * 32)


def _leaf(v: VehicleEntry) -> bytes:
    return keccak(
        abi_encode(
            ["string", "string", "uint256"],
            [v.vehicle_id, v.time_iso, v.weight_kg],
        )
    )


def _pair(a: bytes, b: bytes) -> bytes:
    return keccak(a + b)


def _v(id_: str, weight: int) -> VehicleEntry:
    return VehicleEntry(
        vehicle_id=id_, time_iso="2026-04-15T08:00:00Z", weight_kg=weight
    )


def test_empty_array_returns_bytes32_zero() -> None:
    assert compute_vehicles_root([]) == EMPTY_ROOT


def test_single_vehicle_equals_leaf_hash() -> None:
    entry = _v("truck-01", 1_200)
    assert compute_vehicles_root([entry]) == "0x" + _leaf(entry).hex()


def test_two_vehicles_pair_hashed_in_order() -> None:
    a = _v("truck-01", 1_200)
    b = _v("truck-02", 900)
    expected = "0x" + _pair(_leaf(a), _leaf(b)).hex()
    assert compute_vehicles_root([a, b]) == expected


def test_deterministic_across_runs() -> None:
    entries = [
        _v("truck-01", 1_200),
        _v("truck-02", 900),
        _v("truck-03", 1_500),
        _v("truck-04", 800),
    ]
    assert compute_vehicles_root(entries) == compute_vehicles_root(entries)


def test_tampering_any_field_changes_root() -> None:
    base = [_v("truck-01", 1_200), _v("truck-02", 900)]
    tampered_weight = [_v("truck-01", 1_201), _v("truck-02", 900)]
    tampered_id = [_v("truck-01", 1_200), _v("truck-02-X", 900)]
    tampered_time = [
        base[0].model_copy(update={"time_iso": "2026-04-15T08:00:01Z"}),
        base[1],
    ]

    root = compute_vehicles_root(base)
    assert compute_vehicles_root(tampered_weight) != root
    assert compute_vehicles_root(tampered_id) != root
    assert compute_vehicles_root(tampered_time) != root


def test_order_matters() -> None:
    a = _v("truck-01", 1_200)
    b = _v("truck-02", 900)
    assert compute_vehicles_root([a, b]) != compute_vehicles_root([b, a])


def test_promotes_odd_leaf_three_elements() -> None:
    a = _v("truck-01", 1_200)
    b = _v("truck-02", 900)
    c = _v("truck-03", 1_500)

    # Nivel 0: [leaf(a), leaf(b), leaf(c)]
    # Nivel 1: [pair(leaf(a), leaf(b)), leaf(c)]  — c se promueve
    # Nivel 2: [pair(pair(leaf(a), leaf(b)), leaf(c))]  — raíz
    l1_left = _pair(_leaf(a), _leaf(b))
    expected = "0x" + _pair(l1_left, _leaf(c)).hex()
    assert compute_vehicles_root([a, b, c]) == expected


def test_promotes_at_multiple_levels_five_elements() -> None:
    a = _v("truck-01", 1_200)
    b = _v("truck-02", 900)
    c = _v("truck-03", 1_500)
    d = _v("truck-04", 800)
    e = _v("truck-05", 1_100)

    l1_left = _pair(_leaf(a), _leaf(b))
    l1_mid = _pair(_leaf(c), _leaf(d))
    l2_left = _pair(l1_left, l1_mid)
    expected = "0x" + _pair(l2_left, _leaf(e)).hex()
    assert compute_vehicles_root([a, b, c, d, e]) == expected


def test_distinguishes_promote_from_duplicate_on_odd() -> None:
    """Guarda contra drift al estilo CVE-2012-2459 (Bitcoin duplica la última hoja)."""
    a = _v("truck-01", 1_200)
    b = _v("truck-02", 900)
    c = _v("truck-03", 1_500)
    assert compute_vehicles_root([a, b, c]) != compute_vehicles_root([a, b, c, c])


def _load_shared_vectors() -> _SharedVectors:
    with _SHARED_VECTORS_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _shared_cases() -> list[_SharedCase]:
    return _load_shared_vectors()["cases"]


def test_shared_vectors_file_is_non_empty() -> None:
    assert len(_shared_cases()) > 0, (
        "clients/shared-vectors/merkle.json está vacío — regenerar con "
        "`pnpm --filter backend run gen:vectors`"
    )


@pytest.mark.parametrize(
    "case",
    _shared_cases(),
    ids=lambda c: c["name"],
)
def test_shared_vector_matches(case: _SharedCase) -> None:
    """
    Garantía cross-language: si backend y cliente divergen en el algoritmo,
    este test falla. Para regenerar tras un cambio intencional del algoritmo:
    `pnpm --filter backend run gen:vectors`.
    """
    vehicles = [
        VehicleEntry(
            vehicle_id=v["vehicleId"],
            time_iso=v["timeIso"],
            weight_kg=int(v["weightKg"]),
        )
        for v in case["vehicles"]
    ]
    assert compute_vehicles_root(vehicles) == case["expectedRoot"]
