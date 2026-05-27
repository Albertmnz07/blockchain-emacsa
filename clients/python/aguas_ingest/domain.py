"""
Constructor del dominio EIP-712. Mirror de `backend/src/eip712/domain.ts`.

Los valores concretos por entorno (name, version, chainId, verifyingContract)
se leen del `.env`. Si la variable falta o está vacía, cae en el default
dev-local — el mismo dominio que el `aguas-ingest mock-backend` espera, así
que `send` contra el mock funciona sin tocar `.env`.

Para apuntar a un entorno real (Azure dev-1n, staging) hay que rellenar las
cuatro variables — si cualquiera diverge del backend, el firmante recuperado
es distinto y el backend responde `401 signer_mismatch`.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

from aguas_ingest.types import Eip712Domain

# Defaults dev-local del dominio EIP-712. Casan bit-a-bit con
# `backend/src/eip712/domain.ts` cuando NODE_ENV=development y con el
# mock-backend de este paquete (`mock_backend.py`).
DEFAULT_NAME: str = "AguasDeCordoba"
DEFAULT_VERSION: str = "1"
DEFAULT_CHAIN_ID: int = 1337
DEFAULT_VERIFYING_CONTRACT: str = "0x000000000000000000000000000000000000dead"


def build_domain_from_env(dotenv_path: str | os.PathLike[str] | None = None) -> Eip712Domain:
    """
    Construye el dominio leyendo del entorno. Acepta un `dotenv_path` opcional
    para tests; por defecto lee las variables ya exportadas (el CLI se
    encarga de cargar `.env` al arrancar).
    """
    if dotenv_path is not None:
        load_dotenv(dotenv_path, override=True)

    return Eip712Domain(
        name=_with_default("AGUAS_EIP712_NAME", DEFAULT_NAME),
        version=_with_default("AGUAS_EIP712_VERSION", DEFAULT_VERSION),
        chain_id=int(_with_default("AGUAS_CHAIN_ID", str(DEFAULT_CHAIN_ID))),
        verifying_contract=_with_default(
            "AGUAS_VERIFYING_CONTRACT", DEFAULT_VERIFYING_CONTRACT
        ),
    )


def build_domain(
    name: str,
    version: str,
    chain_id: int,
    verifying_contract: str,
) -> Eip712Domain:
    """Constructor explícito (usado por tests y por callers programáticos)."""
    return Eip712Domain(
        name=name,
        version=version,
        chain_id=chain_id,
        verifying_contract=verifying_contract,
    )


def _with_default(key: str, default: str) -> str:
    value = os.environ.get(key)
    if value is None or value == "":
        return default
    return value
