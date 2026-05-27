"""Cliente Python para la API de ingesta de Aguas de Córdoba."""

from aguas_ingest.domain import build_domain, build_domain_from_env
from aguas_ingest.eip712 import recover_signer, sign_batch
from aguas_ingest.merkle import compute_vehicles_root
from aguas_ingest.types import (
    LODO_BATCH_PRIMARY_TYPE,
    LODO_BATCH_TYPES,
    Eip712Domain,
    IngestRequest,
    LodoBatch,
    VehicleEntry,
)

__all__ = [
    "LODO_BATCH_PRIMARY_TYPE",
    "LODO_BATCH_TYPES",
    "Eip712Domain",
    "IngestRequest",
    "LodoBatch",
    "VehicleEntry",
    "build_domain",
    "build_domain_from_env",
    "compute_vehicles_root",
    "recover_signer",
    "sign_batch",
]

__version__ = "0.1.0"
