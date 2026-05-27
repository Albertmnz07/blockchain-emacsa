"""
Wrapper standalone de `aguas_ingest.postman_matrix.build_matrix`. Lee el
entorno (`AGUAS_PRIVATE_KEY` + dominio EIP-712), genera una key ad-hoc para
el caso `unauthorized_real_post`, escribe los 4 fixtures en `.out/postman/
fixtures/`. Pensado para devs que quieran regenerar la matriz fuera del
flujo del subcomando `aguas-ingest gen-postman`.

Ejecutar desde `clients/python`:
    AGUAS_PRIVATE_KEY=0x... uv run python scripts/gen_postman_matrix.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from eth_account import Account

from aguas_ingest.domain import build_domain_from_env
from aguas_ingest.postman_matrix import build_matrix, write_matrix


def main() -> None:
    load_dotenv()

    good_key = os.environ.get("AGUAS_PRIVATE_KEY") or ""
    if good_key == "":
        print(
            "error: AGUAS_PRIVATE_KEY no está en el entorno. Revisa "
            "clients/python/.env o exporta la variable.",
            file=sys.stderr,
        )
        sys.exit(2)

    bad_account = Account.create()
    bad_key = bad_account.key.hex()
    if not bad_key.startswith("0x"):
        bad_key = "0x" + bad_key

    fixtures = build_matrix(
        domain=build_domain_from_env(),
        good_private_key=good_key,
        bad_private_key=bad_key,
        timestamp=int(time.time()),
    )

    out_dir = Path(__file__).resolve().parent.parent / ".out" / "postman" / "fixtures"
    write_matrix(out_dir, fixtures)

    print(f"matriz POST real escrita en {out_dir}", file=sys.stderr)
    print(f"  signer (key buena):    {Account.from_key(good_key).address}", file=sys.stderr)
    print(f"  signer (key ad-hoc):   {bad_account.address}", file=sys.stderr)


if __name__ == "__main__":
    main()
