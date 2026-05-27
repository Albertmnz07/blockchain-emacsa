"""
Firma EIP-712 del struct `LodoBatch`.

Wrapper delgado sobre `eth_account.Account.sign_typed_data`. El único matiz
interesante es cómo construimos el `full_message`:

- `types` incluye *también* el bloque `EIP712Domain` además de `LodoBatch`,
  porque eth_account lo exige para calcular el domain separator.
- `domain` lleva los cuatro campos (name, version, chainId, verifyingContract)
  que deben coincidir bit-a-bit con los del backend.
- `message` es el batch con claves en camelCase (no snake_case), ya que el
  `type` EIP-712 los nombra así. Usamos `model_dump(by_alias=True)` de
  Pydantic para conseguirlo.
- Los `uint256` se pasan como `int` (no string): EIP-712 los hashea
  numéricamente. La conversión a string es solo para el wire JSON.
"""

from __future__ import annotations

from typing import Any

from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_account.signers.local import LocalAccount
from hexbytes import HexBytes

from aguas_ingest.types import (
    LODO_BATCH_PRIMARY_TYPE,
    LODO_BATCH_TYPES,
    Eip712Domain,
    LodoBatch,
)

_EIP712_DOMAIN_TYPE = [
    {"name": "name", "type": "string"},
    {"name": "version", "type": "string"},
    {"name": "chainId", "type": "uint256"},
    {"name": "verifyingContract", "type": "address"},
]


def _batch_message(batch: LodoBatch) -> dict[str, Any]:
    """
    Convierte el `LodoBatch` a dict camelCase con ints para EIP-712.

    OJO — el `model_dump(by_alias=True)` aquí va *sin* `mode="json"` a
    propósito: los `field_serializer(..., when_used="json")` de `types.py`
    convierten los `uint256` a string base-10 cuando se serializa al wire
    HTTP, pero EIP-712 necesita los enteros numéricos porque los hashea
    como `uint256`. Si alguien "uniformiza" esto con `mode="json"`, la
    firma pasa a calcularse sobre strings y el backend recupera siempre
    otra dirección → `signer_mismatch` silencioso.
    """
    msg = batch.model_dump(by_alias=True)
    # `vehiclesRoot` tiene que ser bytes (bytes32) para encode_typed_data.
    msg["vehiclesRoot"] = HexBytes(msg["vehiclesRoot"])
    return msg


def build_full_message(domain: Eip712Domain, batch: LodoBatch) -> dict[str, Any]:
    """
    Construye el objeto `full_message` que espera
    `eth_account.messages.encode_typed_data`. Exportado para que los tests
    puedan inspeccionarlo y para que `verify_signature` use exactamente el
    mismo dict que `sign_batch`.
    """
    return {
        "types": {
            "EIP712Domain": _EIP712_DOMAIN_TYPE,
            **LODO_BATCH_TYPES,
        },
        "domain": {
            "name": domain.name,
            "version": domain.version,
            "chainId": domain.chain_id,
            "verifyingContract": domain.verifying_contract,
        },
        "primaryType": LODO_BATCH_PRIMARY_TYPE,
        "message": _batch_message(batch),
    }


def sign_batch(private_key: str, domain: Eip712Domain, batch: LodoBatch) -> str:
    """
    Firma el `batch` bajo `domain` con `private_key`.

    Devuelve la firma en hex (0x + 130 chars, 65 bytes) — el formato que el
    header `X-Signature` exige.
    """
    account: LocalAccount = Account.from_key(private_key)
    signable = encode_typed_data(full_message=build_full_message(domain, batch))
    signed = account.sign_message(signable)
    sig_hex = HexBytes(signed.signature).hex()
    return sig_hex if sig_hex.startswith("0x") else "0x" + sig_hex


def recover_signer(domain: Eip712Domain, batch: LodoBatch, signature: str) -> str:
    """
    Recupera la dirección que firmó `batch` bajo `domain`. Devuelve EIP-55
    checksum address (`0x...`). Útil para round-trip local en `aguas-ingest verify`.
    """
    signable = encode_typed_data(full_message=build_full_message(domain, batch))
    return Account.recover_message(signable, signature=signature)
