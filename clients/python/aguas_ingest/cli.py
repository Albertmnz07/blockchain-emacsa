"""
CLI `aguas-ingest`: firma, verifica y envía batches contra la API de Aguas
de Córdoba.

Subcomandos:

- `keygen`:   genera un par de claves EIP-712 nuevo (para desarrollo/test).
              La clave privada NO se persiste automáticamente — el usuario
              decide si la guarda en `.env` bajo `AGUAS_PRIVATE_KEY`.

- `sign`:     lee un batch sin firmar desde JSON, calcula `vehiclesRoot`,
              firma con EIP-712 y emite un "signed envelope" (JSON con
              `request` + `signature` + `signerAddress`). Con `--postman-env`,
              además escribe una environment de Postman lista para importar.

- `verify`:   lee un signed envelope, recupera la dirección del firmante y
              comprueba que coincide con `signerAddress`. Sanity check local,
              útil offline antes de gastar un round-trip a la API.

- `send`:     lee un signed envelope y hace POST contra la API, ya sea al
              endpoint de dry-run (`--dry-run`) o al real.

- `mock-backend`: arranca un servidor stdlib local que mimetiza el endpoint
              `POST /v1/lodos/batches/dry-run`. Sirve para que un integrador
              pruebe el round-trip HTTP (headers, body, respuesta) sin Docker
              ni red. Reusa el mismo pipeline criptográfico del paquete.

Todas las rutas aceptan `-` para stdin/stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast
import time

from dotenv import load_dotenv
from eth_account import Account

from aguas_ingest.client import IngestApiError, post_dry_run, post_ingest
from aguas_ingest.domain import (
    DEFAULT_CHAIN_ID,
    DEFAULT_VERIFYING_CONTRACT,
    build_domain_from_env,
)
from aguas_ingest.eip712 import recover_signer, sign_batch
from aguas_ingest.merkle import compute_vehicles_root
from aguas_ingest.mock_backend import make_server
from aguas_ingest.postman import PostmanEnvValues, write_env
from aguas_ingest.postman_collection import (
    build_matrix_collection,
    write_collection,
)
from aguas_ingest.postman_matrix import build_matrix, write_matrix
from aguas_ingest.types import (
    Eip712Domain,
    IngestRequest,
    LodoBatch,
    VehicleEntry,
)

# --- I/O helpers ------------------------------------------------------------


def _read_json(source: str) -> dict[str, Any]:
    """Lee JSON desde path o desde stdin si `source == '-'`."""
    if source == "-":
        return cast("dict[str, Any]", json.loads(sys.stdin.read()))
    with Path(source).open(encoding="utf-8") as f:
        return cast("dict[str, Any]", json.load(f))


def _write_json(target: str, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if target == "-":
        sys.stdout.write(text)
        return
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    Path(target).write_text(text, encoding="utf-8", newline="\n")


def _require_env(key: str) -> str:
    value = os.environ.get(key)
    if value is None or value == "":
        print(
            f"error: variable requerida no encontrada: {key} "
            "(revisar .env; ver clients/python/.env.example)",
            file=sys.stderr,
        )
        sys.exit(2)
    return value


def _is_local_url(url: str) -> bool:
    return any(host in url for host in ("localhost", "127.0.0.1", "[::1]"))


def _warn_if_frankenstein_config(base_url: str) -> None:
    """
    Detecta el caso "URL real + dominio EIP-712 a defaults dev". Es la
    forma más común de meterse en `signer_mismatch` silencioso: el integrador
    rellena AGUAS_BASE_URL pero olvida AGUAS_CHAIN_ID y/o
    AGUAS_VERIFYING_CONTRACT, y la firma queda firmada bajo un dominio que
    no es el del backend de destino.
    """
    if _is_local_url(base_url):
        return

    chain_id_unset = (os.environ.get("AGUAS_CHAIN_ID") or "") in ("", str(DEFAULT_CHAIN_ID))
    contract_unset = (
        os.environ.get("AGUAS_VERIFYING_CONTRACT") or ""
    ).lower() in ("", DEFAULT_VERIFYING_CONTRACT.lower())

    if chain_id_unset or contract_unset:
        missing = []
        if chain_id_unset:
            missing.append(f"AGUAS_CHAIN_ID (en default {DEFAULT_CHAIN_ID})")
        if contract_unset:
            missing.append(
                f"AGUAS_VERIFYING_CONTRACT (en default {DEFAULT_VERIFYING_CONTRACT})"
            )
        print(
            f"warning: base-url no es local ({base_url}) pero el dominio EIP-712 "
            f"está en defaults dev: {', '.join(missing)}. La firma probablemente "
            "fallará con `signer_mismatch`. Rellenar el bloque entero del .env "
            "para el entorno de destino.",
            file=sys.stderr,
        )


# --- subcomando: keygen -----------------------------------------------------


def _cmd_keygen(_: argparse.Namespace) -> int:
    acct = Account.create()
    pk_hex = acct.key.hex()
    if not pk_hex.startswith("0x"):
        pk_hex = "0x" + pk_hex
    print("# Par de claves nuevo (EIP-712). NO se ha persistido nada.")
    print(f"# Signer address: {acct.address}")
    print("# (derivable del private key; no hace falta configurar como env var)")
    print(f"AGUAS_PRIVATE_KEY={pk_hex}")
    print(
        "#\n# Guardar la privada en un gestor de secretos o en un .env fuera de git.",
        file=sys.stderr,
    )
    return 0


# --- modelo del signed envelope ---------------------------------------------


def _build_signed_envelope(
    domain: Eip712Domain,
    request: IngestRequest,
    signature: str,
    signer_address: str,
) -> dict[str, Any]:
    return {
        "domain": {
            "name": domain.name,
            "version": domain.version,
            "chainId": domain.chain_id,
            "verifyingContract": domain.verifying_contract,
        },
        "request": request.model_dump(by_alias=True, mode="json"),
        "signature": signature,
        "signerAddress": signer_address,
    }


def _parse_unsigned_batch(data: dict[str, Any]) -> tuple[LodoBatch, list[VehicleEntry]]:
    """
    Acepta la forma `{"batch": {...sin vehiclesRoot...}, "vehicles": [...]}`.
    Calcula `vehiclesRoot` y construye el `LodoBatch` completo.
    """
    raw_batch = cast("dict[str, Any]", data["batch"])
    raw_vehicles = cast("list[dict[str, Any]]", data.get("vehicles", []))

    vehicles = [
        VehicleEntry(
            vehicle_id=str(v["vehicleId"]),
            time_iso=str(v["timeIso"]),
            weight_kg=int(v["weightKg"]),
        )
        for v in raw_vehicles
    ]

    vehicles_root = compute_vehicles_root(vehicles)

    batch = LodoBatch(
        batch_id=str(raw_batch["batchId"]),
        edar=str(raw_batch["edar"]),
        date_iso=str(raw_batch["dateIso"]),
        polielectrolito=int(raw_batch["polielectrolito"]),
        materia_organica_bp=int(raw_batch["materiaOrganicaBp"]),
        vehicles_root=vehicles_root,
        submitted_at_iso=str(raw_batch["submittedAtIso"]),
    )
    return batch, vehicles


def _parse_signed_envelope(
    data: dict[str, Any],
) -> tuple[Eip712Domain, IngestRequest, str, str]:
    d = cast("dict[str, Any]", data["domain"])
    req_raw = cast("dict[str, Any]", data["request"])
    batch_raw = cast("dict[str, Any]", req_raw["batch"])
    vehicles_raw = cast("list[dict[str, Any]]", req_raw.get("vehicles", []))

    domain = Eip712Domain(
        name=str(d["name"]),
        version=str(d["version"]),
        chain_id=int(d["chainId"]),
        verifying_contract=str(d["verifyingContract"]),
    )
    batch = LodoBatch(
        batch_id=str(batch_raw["batchId"]),
        edar=str(batch_raw["edar"]),
        date_iso=str(batch_raw["dateIso"]),
        polielectrolito=int(batch_raw["polielectrolito"]),
        materia_organica_bp=int(batch_raw["materiaOrganicaBp"]),
        vehicles_root=str(batch_raw["vehiclesRoot"]),
        submitted_at_iso=str(batch_raw["submittedAtIso"]),
    )
    vehicles = [
        VehicleEntry(
            vehicle_id=str(v["vehicleId"]),
            time_iso=str(v["timeIso"]),
            weight_kg=int(v["weightKg"]),
        )
        for v in vehicles_raw
    ]
    return (
        domain,
        IngestRequest(batch=batch, vehicles=vehicles),
        str(data["signature"]),
        str(data["signerAddress"]),
    )


# --- subcomando: sign -------------------------------------------------------


def _cmd_sign(args: argparse.Namespace) -> int:
    domain = build_domain_from_env()
    private_key = _require_env("AGUAS_PRIVATE_KEY")
    signer_address = Account.from_key(private_key).address

    raw = _read_json(args.batch)
    batch, vehicles = _parse_unsigned_batch(raw)
    request = IngestRequest(batch=batch, vehicles=vehicles)

    signature = sign_batch(private_key, domain, batch)
    envelope = _build_signed_envelope(domain, request, signature, signer_address)

    _write_json(args.out, envelope)

    if args.postman_env is not None:
        write_env(
            args.postman_env,
            PostmanEnvValues(
                base_url=args.base_url,
                signer_address=signer_address,
                signature=signature,
                batch_body=request.model_dump_json(by_alias=True),
            ),
        )
        print(f"postman environment escrito en {args.postman_env}", file=sys.stderr)

    return 0


# --- subcomando: verify -----------------------------------------------------


def _cmd_verify(args: argparse.Namespace) -> int:
    raw = _read_json(args.envelope)
    domain, request, signature, signer_address = _parse_signed_envelope(raw)

    recovered = recover_signer(domain, request.batch, signature)

    if recovered.lower() != signer_address.lower():
        print(
            f"fallo: la dirección recuperada ({recovered}) NO coincide con "
            f"signerAddress ({signer_address}). La firma, el dominio o el batch "
            "no son consistentes.",
            file=sys.stderr,
        )
        return 1

    recomputed = compute_vehicles_root(request.vehicles)
    if recomputed != request.batch.vehicles_root:
        print(
            f"fallo: vehiclesRoot recomputado ({recomputed}) no coincide con "
            f"el firmado ({request.batch.vehicles_root}).",
            file=sys.stderr,
        )
        return 1

    print(f"ok — firmado por {recovered}, vehiclesRoot {recomputed}")
    return 0


# --- subcomando: send -------------------------------------------------------


def _cmd_send(args: argparse.Namespace) -> int:
    raw = _read_json(args.envelope)
    _, request, signature, signer_address = _parse_signed_envelope(raw)
    base_url: str = args.base_url
    auth: tuple[str, str] | None = args.basic_auth

    _warn_if_frankenstein_config(base_url)

    try:
        if args.dry_run:
            out = post_dry_run(base_url, request, signature, signer_address, auth=auth)
            print(json.dumps(asdict(out), indent=2))
        else:
            out = post_ingest(base_url, request, signature, signer_address, auth=auth)
            print(json.dumps(asdict(out), indent=2))
    except IngestApiError as err:
        print(
            json.dumps(
                {"status": err.status_code, "error": err.code, "message": err.api_message},
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1

    return 0


# --- subcomando: mock-backend -----------------------------------------------


def _cmd_mock_backend(args: argparse.Namespace) -> int:
    """
    Arranca un servidor local que mimetiza `POST /v1/lodos/batches/dry-run`.
    Bloquea hasta Ctrl-C. Reutiliza el mismo dominio EIP-712 que el resto
    de subcomandos (lo lee del entorno), de modo que firmar con `sign` y
    apuntar `send --dry-run --base-url http://localhost:<port>` funciona
    end-to-end sin más configuración.
    """
    domain = build_domain_from_env()
    server = make_server(args.host, args.port, domain)
    print(
        f"mock-backend escuchando en http://{args.host}:{args.port}\n"
        "  POST /v1/lodos/batches/dry-run  (Ctrl-C para parar)\n"
        "  fidelidad: misma forma de respuesta que el backend real;\n"
        "  no hay SignerRegistry ni persistencia — solo verificación criptográfica.",
        file=sys.stderr,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("mock-backend parado.", file=sys.stderr)
    finally:
        server.server_close()
    return 0


# --- subcomando: gen-postman -----------------------------------------------


# Path al directorio `clients/postman/fixtures/` versionado en git, relativo
# al package del CLI. Lo necesita el subcomando `gen-postman` para componer
# la sección dry-run de la colección de matriz.
_STATIC_FIXTURES_DIR = (
    Path(__file__).resolve().parent.parent.parent / "postman" / "fixtures"
)


def _cmd_gen_postman(args: argparse.Namespace) -> int:
    """
    Genera el bundle Postman completo en `.out/postman/` (relativo al cwd):

      - `fixtures/{happy_real_post,idempotent_replay,conflict_real_post,
         unauthorized_real_post}.json` — los 4 estados POST real.
      - `AguasDeCordoba.postman_collection.json` — colección extendida con
         basic auth + sección "POST real" añadida a la dry-run baseline.
      - `env.postman.json` — environment con `baseUrl`, `signerAddress`,
         `signature`, `batchBody` (del happy_real_post para que el dry-run
         env-driven exhibite el mismo batch) + `basicAuthUser`/`Password`.

    Necesita `AGUAS_PRIVATE_KEY` en el entorno (la "key buena", registrada en
    SignerRegistry). El resto de variables del dominio EIP-712 caen en
    defaults dev-local si no están — el cliente avisa con la guarda
    Frankenstein cuando intentes mandar contra una URL no-local con el
    dominio mal puesto.
    """
    good_key = _require_env("AGUAS_PRIVATE_KEY")

    bad_account = Account.create()
    bad_key = bad_account.key.hex()
    if not bad_key.startswith("0x"):
        bad_key = "0x" + bad_key

    timestamp = int(time.time())
    fixtures = build_matrix(
        domain=build_domain_from_env(),
        good_private_key=good_key,
        bad_private_key=bad_key,
        timestamp=timestamp,
    )

    out_dir = Path.cwd() / ".out" / "postman"
    fixtures_dir = out_dir / "fixtures"
    write_matrix(fixtures_dir, fixtures)

    collection = build_matrix_collection(_STATIC_FIXTURES_DIR, fixtures_dir)
    write_collection(collection, out_dir / "AguasDeCordoba.postman_collection.json")

    happy = fixtures["happy_real_post"]
    happy_signer = cast("dict[str, str]", happy["headers"])["X-Signer"]
    happy_signature = cast("dict[str, str]", happy["headers"])["X-Signature"]
    happy_body = cast("dict[str, Any]", happy["body"])

    base_url = (
        os.environ.get("AGUAS_BASE_URL") or "http://127.0.0.1:41337"
    )
    env_values = PostmanEnvValues(
        base_url=base_url,
        signer_address=happy_signer,
        signature=happy_signature,
        # `json.dumps` (no indent) preserva los uint256 ya como strings — los
        # bytes del wire que Postman envía pueden diferir en whitespace de los
        # firmados, da igual: la firma EIP-712 cubre el struct numérico, no
        # el JSON serializado.
        batch_body=json.dumps(happy_body, ensure_ascii=False),
        basic_auth_user=os.environ.get("AGUAS_BASIC_AUTH_USER") or "",
        basic_auth_password=os.environ.get("AGUAS_BASIC_AUTH_PASSWORD") or "",
    )
    write_env(
        out_dir / "env.postman.json",
        env_values,
        name=f"AguasDeCordoba — matrix-{timestamp}",
    )

    print(f"matriz Postman escrita en {out_dir}", file=sys.stderr)
    print(f"  • fixtures/  ({len(fixtures)} fixtures POST real)", file=sys.stderr)
    print("  • AguasDeCordoba.postman_collection.json", file=sys.stderr)
    print("  • env.postman.json", file=sys.stderr)
    print("", file=sys.stderr)
    print(f"  signer (key buena):  {Account.from_key(good_key).address}", file=sys.stderr)
    print(f"  signer (key ad-hoc): {bad_account.address}", file=sys.stderr)
    print(f"  batchId base:        batch-postman-matrix-{timestamp}", file=sys.stderr)
    print(f"  base_url:            {base_url}", file=sys.stderr)
    return 0


# --- parser -----------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aguas-ingest",
        description="Cliente EIP-712 + HTTP para la API de ingesta de Aguas de Córdoba.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("keygen", help="Genera un par de claves EIP-712 nuevo.")

    p_sign = sub.add_parser("sign", help="Firma un batch sin firmar y emite un envelope.")
    p_sign.add_argument(
        "--batch",
        required=True,
        help="Ruta al batch sin firmar (JSON) o '-' para stdin.",
    )
    p_sign.add_argument(
        "--out",
        default="-",
        help="Destino del signed envelope. '-' (default) para stdout.",
    )
    p_sign.add_argument(
        "--postman-env",
        default=None,
        help="Si se indica, escribe también un Postman environment file en esa ruta.",
    )
    p_sign.add_argument(
        "--base-url",
        default=None,
        help=(
            "baseUrl que se pone en el Postman environment. Si se omite, "
            "toma el valor de AGUAS_BASE_URL; si tampoco está, cae en "
            "http://localhost:3000."
        ),
    )

    p_verify = sub.add_parser("verify", help="Sanity check local de un signed envelope.")
    p_verify.add_argument(
        "--envelope",
        required=True,
        help="Ruta al signed envelope (JSON) o '-' para stdin.",
    )

    p_send = sub.add_parser("send", help="POSTea un signed envelope contra la API.")
    p_send.add_argument(
        "--envelope",
        required=True,
        help="Ruta al signed envelope (JSON) o '-' para stdin.",
    )
    p_send.add_argument("--base-url", default=None, help="Override de AGUAS_BASE_URL.")
    p_send.add_argument(
        "--dry-run",
        action="store_true",
        help="Usar el endpoint /v1/lodos/batches/dry-run en lugar del POST real.",
    )
    p_send.add_argument(
        "--basic-auth-user",
        default=None,
        help=(
            "Usuario para HTTP Basic Auth (override de AGUAS_BASIC_AUTH_USER). "
            "Necesario si el backend está detrás de un proxy protegido."
        ),
    )
    p_send.add_argument(
        "--basic-auth-password",
        default=None,
        help=(
            "Password para HTTP Basic Auth (override de AGUAS_BASIC_AUTH_PASSWORD). "
            "Visible en la lista de procesos — si te preocupa, usa la env var."
        ),
    )

    sub.add_parser(
        "gen-postman",
        help=(
            "Genera el bundle Postman (matriz POST real + colección + env) en "
            ".out/postman/. Requiere AGUAS_PRIVATE_KEY."
        ),
    )

    p_mock = sub.add_parser(
        "mock-backend",
        help="Arranca un servidor local que mimetiza POST /v1/lodos/batches/dry-run.",
    )
    p_mock.add_argument(
        "--host",
        default="127.0.0.1",
        help="Interface en la que escuchar (default 127.0.0.1; usar 0.0.0.0 para exponer).",
    )
    p_mock.add_argument(
        "--port",
        type=int,
        default=41337,
        help="Puerto (default 41337, casa con deploy/compose.dryrun.yml).",
    )

    return p


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Precedencia uniforme para `base_url`: flag > env > default.
    # Default = `mock-backend` local (puerto fijo 41337). Así `send` y `sign`
    # contra el mock funcionan sin tocar `.env`. El integrador rellena
    # AGUAS_BASE_URL sólo cuando apunta a un entorno real.
    _MOCK_BASE_URL = "http://127.0.0.1:41337"
    if args.command in ("send", "sign") and args.base_url is None:
        args.base_url = os.environ.get("AGUAS_BASE_URL") or _MOCK_BASE_URL

    # HTTP Basic Auth opcional para `send` — sólo si el backend está detrás
    # de un proxy protegido (Caddy/nginx/ngrok). Si ambos faltan, no se manda
    # `Authorization`. Pedir uno solo es siempre un error de configuración —
    # fallamos pronto en lugar de mandar credenciales medio formadas al wire.
    if args.command == "send":
        user = args.basic_auth_user or os.environ.get("AGUAS_BASIC_AUTH_USER") or None
        password = (
            args.basic_auth_password
            or os.environ.get("AGUAS_BASIC_AUTH_PASSWORD")
            or None
        )
        if (user is None) != (password is None):
            print(
                "error: --basic-auth-user y --basic-auth-password (o sus "
                "AGUAS_BASIC_AUTH_USER / AGUAS_BASIC_AUTH_PASSWORD) tienen "
                "que ir juntos. Pasa los dos o ninguno.",
                file=sys.stderr,
            )
            return 2
        args.basic_auth = (user, password) if user is not None else None

    if args.command == "keygen":
        return _cmd_keygen(args)
    if args.command == "sign":
        return _cmd_sign(args)
    if args.command == "verify":
        return _cmd_verify(args)
    if args.command == "send":
        return _cmd_send(args)
    if args.command == "gen-postman":
        return _cmd_gen_postman(args)
    if args.command == "mock-backend":
        return _cmd_mock_backend(args)

    parser.error(f"subcomando desconocido: {args.command}")
    return 2
