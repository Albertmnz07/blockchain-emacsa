"""
Merkle root binario sobre el array de vehículos, preservando el orden de entrada.

Este módulo es el port directo de `backend/src/modules/ingest/merkle.ts`. Cualquier
divergencia en el algoritmo entre cliente y backend produce `vehicles_root_mismatch`
silencioso en el endpoint real. No cambiar sin coordinar con ambos lados.

Semántica (ver docs/stack/backend/eip712.md §4):

- Hoja:      keccak256(abi_encode(string, string, uint256))
- Par:       keccak256(concat(a, b))   — sin ordenación; preserva orden de entrada
- Impar:     la hoja sin pareja se promueve al siguiente nivel sin modificar
- Vacío:     bytes32(0)

No se separan dominios entre hojas y nodos internos; coherente con el backend.
"""

from __future__ import annotations

from collections.abc import Sequence

from eth_abi.abi import encode as abi_encode
from eth_utils.crypto import keccak

from aguas_ingest.types import VehicleEntry

_EMPTY_ROOT: bytes = b"\x00" * 32


def _hash_leaf(vehicle: VehicleEntry) -> bytes:
    return keccak(
        abi_encode(
            ["string", "string", "uint256"],
            [vehicle.vehicle_id, vehicle.time_iso, vehicle.weight_kg],
        )
    )


def _hash_pair(a: bytes, b: bytes) -> bytes:
    return keccak(a + b)


def compute_vehicles_root(vehicles: Sequence[VehicleEntry]) -> str:
    """
    Devuelve el `vehiclesRoot` como hex con prefijo `0x`, 64 chars.

    El resultado es byte-a-byte el mismo que el que produce el backend, de modo
    que el campo `vehiclesRoot` firmado con EIP-712 se puede verificar contra
    el recomputado sin coincidencias parciales ni normalización.
    """
    if len(vehicles) == 0:
        return "0x" + _EMPTY_ROOT.hex()

    level: list[bytes] = [_hash_leaf(v) for v in vehicles]

    while len(level) > 1:
        next_level: list[bytes] = []
        for i in range(0, len(level), 2):
            left = level[i]
            right = level[i + 1] if i + 1 < len(level) else None
            next_level.append(left if right is None else _hash_pair(left, right))
        level = next_level

    return "0x" + level[0].hex()
