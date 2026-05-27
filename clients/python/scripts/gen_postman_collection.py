"""
Wrapper standalone para regenerar `clients/postman/AguasDeCordoba.postman_collection.json`
(versión versionada en git, sin matriz). Útil cuando alguien añade/modifica
un fixture estático y quiere reflejarlo en la colección.

La lógica de composición vive en `aguas_ingest.postman_collection`. Para la
versión con matriz POST real, el subcomando `aguas-ingest gen-postman` la
genera al vuelo en `.out/postman/`.

Ejecutar desde `clients/python`:
    uv run python scripts/gen_postman_collection.py

Requisito: `gen_postman_fixtures.py` ejecutado previamente.
"""

from __future__ import annotations

from pathlib import Path

from aguas_ingest.postman_collection import (
    build_dry_run_only_collection,
    write_collection,
)

_POSTMAN_DIR = Path(__file__).resolve().parent.parent.parent / "postman"
_FIXTURES_DIR = _POSTMAN_DIR / "fixtures"
_COLLECTION_PATH = _POSTMAN_DIR / "AguasDeCordoba.postman_collection.json"


def main() -> None:
    collection = build_dry_run_only_collection(_FIXTURES_DIR)
    write_collection(collection, _COLLECTION_PATH)
    print(f"colección escrita en {_COLLECTION_PATH}")


if __name__ == "__main__":
    main()
