"""
Modelos de datos del cliente. Espejo tipado de los schemas Zod del backend
(`backend/src/modules/ingest/schemas.ts` y `backend/src/eip712/types.ts`).

Importante — simetría con el backend:
- `uint256` se modela como `int` con `ge=0`, pero se serializa al wire como
  string base-10. Esto refleja cómo el backend acepta strings y los
  transforma a BigInt.
- Los nombres de atributo Python son snake_case; el alias JSON es camelCase
  para coincidir con el contrato HTTP sin obligar a renombrar en Python.
- `LodoBatch` + `IngestRequest` son `BaseModel` inmutables: el batch se firma
  una vez y no se muta entre reintentos (ver la trampa de `submittedAtIso`
  documentada en docs/stack/backend/api-ingest.md).
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, ConfigDict, Field, field_serializer
from pydantic.alias_generators import to_camel


class _CamelModel(BaseModel):
    """Base común: snake_case en Python, camelCase en JSON, extras prohibidos."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
    )


class VehicleEntry(_CamelModel):
    vehicle_id: str = Field(min_length=1)
    time_iso: str
    weight_kg: int = Field(ge=0)

    @field_serializer("weight_kg", when_used="json")
    def _ser_weight(self, value: int) -> str:
        return str(value)


class LodoBatch(_CamelModel):
    batch_id: str = Field(min_length=1)
    edar: str = Field(min_length=1)
    date_iso: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    polielectrolito: int = Field(ge=0)
    materia_organica_bp: int = Field(ge=0)
    vehicles_root: str = Field(pattern=r"^0x[0-9a-fA-F]{64}$")
    submitted_at_iso: str

    @field_serializer("polielectrolito", "materia_organica_bp", when_used="json")
    def _ser_uint(self, value: int) -> str:
        return str(value)


class IngestRequest(_CamelModel):
    batch: LodoBatch
    vehicles: list[VehicleEntry]


class Eip712Domain(_CamelModel):
    name: str
    version: str
    chain_id: int = Field(ge=0)
    verifying_contract: str = Field(pattern=r"^0x[0-9a-fA-F]{40}$")


# Definiciones EIP-712. Tienen que coincidir bit-a-bit con
# `backend/src/eip712/types.ts::LodoBatchTypes`. Cualquier desvío rompe la
# verificación de firma del backend sin mensaje de error útil (recovers a
# different address → signer_mismatch).
LODO_BATCH_TYPES: Final[dict[str, list[dict[str, str]]]] = {
    "LodoBatch": [
        {"name": "batchId", "type": "string"},
        {"name": "edar", "type": "string"},
        {"name": "dateIso", "type": "string"},
        {"name": "polielectrolito", "type": "uint256"},
        {"name": "materiaOrganicaBp", "type": "uint256"},
        {"name": "vehiclesRoot", "type": "bytes32"},
        {"name": "submittedAtIso", "type": "string"},
    ],
}

LODO_BATCH_PRIMARY_TYPE: Final[str] = "LodoBatch"
