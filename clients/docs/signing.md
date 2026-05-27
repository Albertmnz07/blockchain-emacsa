# El contrato de firma

## Qué viaja en cada POST y por qué

Cada batch que envías a nuestro endpoint lleva dos cabeceras HTTP custom — `X-Signature` y `X-Signer` — generadas por tu cliente con tu clave privada. Es la única forma que tenemos de verificar que el batch viene de ti y no ha sido modificado en tránsito.

**El flujo en tu lado** (el cliente Python lo hace en una sola llamada con `aguas-ingest sign`; si reimplementas en otro lenguaje, tienes que reproducirlo paso a paso):

1. Construyes el batch (objeto JSON con `batchId`, `edar`, `dateIso`, `polielectrolito`, `materiaOrganicaBp`, `vehiclesRoot`, `submittedAtIso`).
2. Lo serializas según EIP-712 — un estándar de Ethereum para firmar datos estructurados sin ambigüedad sobre "qué bytes exactos firmé". El struct concreto es `LodoBatch`, definido más abajo.
3. Aplicas keccak256 al resultado y firmas el hash con tu clave privada (algoritmo ECDSA sobre la curva secp256k1, el estándar de Ethereum). El output es una firma de 65 bytes.
4. Codificas la firma como hex (`0x` + 130 caracteres) y la mandas en `X-Signature`.
5. Mandas en paralelo `X-Signer`: la dirección Ethereum (`0x` + 40 hex chars) que corresponde a tu clave privada — derivada del public key.

**Lo que hace nuestro backend al recibir el POST:**

1. Aplica el mismo proceso EIP-712 al body del request (recompute del hash que tú firmaste).
2. Llama a `ecrecover` — operación estándar de Ethereum que toma el hash + la firma y devuelve la dirección que firmó.
3. Compara esa dirección con la del header `X-Signer`. Si no coinciden, responde `401 signer_mismatch`.
4. Si coinciden, en el endpoint real consulta el `SignerRegistry` on-chain para ver si esa dirección está autorizada (en el dry-run y en el mock-backend este paso se salta — solo verifica la criptografía).

A partir de aquí el resto del documento entra al detalle: dominio EIP-712, struct `LodoBatch`, algoritmo Merkle, código Python de referencia y contrato HTTP completo.

## Dominio EIP-712

Los cuatro campos del dominio tienen que coincidir bit-a-bit con los del backend. Cualquier divergencia produce un `signer_mismatch` silencioso — la firma es válida pero recupera una dirección que no coincide con `X-Signer`.

| Entorno | `name` | `version` | `chainId` | `verifyingContract` |
|---|---|---|---|---|
| local | `AguasDeCordoba` | `1` | `1337` | `0x000000000000000000000000000000000000dead` |
| staging | *(pendiente)* | *(pendiente)* | *(pendiente)* | *(pendiente)* |
| prod | *(pendiente)* | *(pendiente)* | *(pendiente)* | *(pendiente)* |

## Struct `LodoBatch`

```solidity
struct LodoBatch {
  string  batchId;          // identificador estable por batch (UUIDv4, etc.)
  string  edar;             // "la-golondrina"
  string  dateIso;          // "YYYY-MM-DD"
  uint256 polielectrolito;  // total diario
  uint256 materiaOrganicaBp;// basis points del total de materia orgánica
  bytes32 vehiclesRoot;     // raíz Merkle del array vehicles
  string  submittedAtIso;   // timestamp ISO-8601 con offset
}
```

Notas clave:

- `uint256` viaja en el JSON como **string** base-10 (`"1234"`) porque los enteros de 256 bits no caben en un `Number` IEEE-754. El backend acepta string y transforma internamente a `BigInt`.
- `vehiclesRoot` es **hex con prefijo `0x` + 64 chars** (32 bytes).
- `dateIso` cumple `YYYY-MM-DD` exacto; cualquier otro formato produce un 400 de Zod.
- Los `vehicles` **no** son parte del struct firmado — su integridad la garantiza `vehiclesRoot` (cambiar un vehículo cambia la raíz y rompe la firma).

## Algoritmo Merkle

Binario, preservando orden de entrada:

- **Hoja:** `keccak256(abiEncode(string, string, uint256))` sobre `(vehicleId, timeIso, weightKg)`.
- **Par:** `keccak256(concat(a, b))` — no hay ordenación; cambiar el orden del array cambia la raíz.
- **Impar:** la hoja sin pareja se **promueve** al siguiente nivel sin modificar. No se duplica (evita CVE-2012-2459).
- **Vacío:** `bytes32(0)` — permite firmar batches sin vehículos manteniendo la forma del struct.

### Ejemplo con 3 vehículos

```
vehicles = [v1, v2, v3]

Nivel 0: [ leaf(v1), leaf(v2), leaf(v3) ]
Nivel 1: [ keccak(leaf(v1) ‖ leaf(v2)), leaf(v3) ]    ← v3 se promueve
Nivel 2: [ keccak(nivel1[0] ‖ leaf(v3)) ]             ← raíz
```

Los **vectores compartidos** `clients/shared-vectors/merkle.json` son el oráculo cross-language, generados desde el backend (TS). El cliente Python los consume en `tests/test_merkle.py`; si backend y cliente divergen en el algoritmo, esos tests fallan antes de merge.

## Firmar en Python

```python
from eth_account import Account
from aguas_ingest import build_domain, compute_vehicles_root, sign_batch
from aguas_ingest.types import LodoBatch, VehicleEntry

domain = build_domain(
    name="AguasDeCordoba",
    version="1",
    chain_id=1337,
    verifying_contract="0x000000000000000000000000000000000000dead",
)

vehicles = [
    VehicleEntry(vehicle_id="truck-01", time_iso="2026-04-16T09:00:00+00:00", weight_kg=1_200),
]
batch = LodoBatch(
    batch_id="batch-example-001",
    edar="la-golondrina",
    date_iso="2026-04-16",
    polielectrolito=1_234,
    materia_organica_bp=5_678,
    vehicles_root=compute_vehicles_root(vehicles),
    submitted_at_iso="2026-04-16T08:00:00+00:00",
)

signature = sign_batch(private_key=Account.create().key.hex(), domain=domain, batch=batch)
```

Internamente `sign_batch` llama a `eth_account.messages.encode_typed_data` + `Account.sign_message`. El resultado es una firma hex de 65 bytes (`0x` + 130 chars), el formato exacto que espera el header `X-Signature`.

## Contrato HTTP

### POST real

```
POST /v1/lodos/batches
Content-Type: application/json
X-Signature: 0x<130 hex chars>
X-Signer:    0x<40 hex chars>

{ "batch": { ... }, "vehicles": [ ... ] }
```

### POST dry-run

```
POST /v1/lodos/batches/dry-run
(mismo body y headers)
```

Respuesta `200`:

```json
{ "recoveredSigner": "0x...", "vehiclesRoot": "0x..." }
```

### OpenAPI

El backend sirve la spec completa en `GET /docs` (UI Swagger) y `GET /docs/json` (JSON). En caso de duda, esa spec es la fuente de la verdad: cualquier cosa documentada aquí y no reflejada en `/docs` es un bug de documentación.

## Por qué el dry-run real sigue siendo la verificación autoritativa

`aguas-ingest verify` y `aguas-ingest mock-backend` (los dos primeros niveles del flujo descrito en el [README de clientes](../README.md#tres-niveles-de-validación)) ejecutan los algoritmos del paquete Python: el cliente firma con sus reglas y el cliente valida con esas mismas reglas. Eso prueba consistencia interna, no compatibilidad con el backend real.

El backend ejecuta el contrato en TypeScript con validadores Zod — los `shared-vectors` cubren divergencias en Merkle entre lenguajes, pero no las reglas de schema (un nuevo `.refine()`, una ventana temporal más estricta, un campo opcional que pasa a obligatorio). Los valores del dominio EIP-712 por entorno (la tabla de arriba) también pueden cambiar antes de que staging y prod se publiquen: si en staging `verifyingContract` no es `0x...dead`, verify y mock pasan en local pero el dry-run real responde `signer_mismatch`.

Por eso el flujo recomendado para el integrador es: iterar contra `verify` y `mock-backend` (rápido, offline, sin red), y dejar el dry-run real para el pre-flight final antes del primer POST a producción y como smoke test en CI. Si el dry-run real responde `200`, los únicos modos de fallo que quedan en el POST real son `403 signer_not_authorized`, `409 batch_id_conflict` y `5xx` (ver [errors-and-retries.md](./errors-and-retries.md)).
