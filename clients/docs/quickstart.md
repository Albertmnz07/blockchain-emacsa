# Quickstart

De cero a un signed envelope verificado y a un round-trip HTTP completo, sin Docker. El flujo cubre los dos primeros [niveles de validación](../README.md#tres-niveles-de-validación) que se pueden ejecutar íntegramente en el entorno del integrador: tier 1 (`verify`, offline) para iterar y tier 2 (`mock-backend`) para probar el wire HTTP. El tier 3 (dry-run real de Aguas) entra en juego cuando Aguas publique la URL — su uso es trivial: misma invocación de `send --dry-run` con otro `--base-url`.

## Requisitos

- **Python** 3.11 o superior.
- **Postman** desktop o **Newman** (`npx newman`) para correr la colección sin UI. Opcional — el flujo principal no lo necesita.
- **Linux** o **WSL2**. El repo normaliza line endings a LF (`clients/postman/.gitattributes`) para que `core.autocrlf=true` en WSL no meta CRLF en fixtures firmados.

No hace falta Docker ni acceso a una URL de staging para empezar: el mock incluido (`aguas-ingest mock-backend`) levanta un servidor local que mimetiza el endpoint dry-run del backend.

## Convención de directorios

El bundle se descomprime en una carpeta (por ejemplo `aguas-pruebas/`) cuyo único hijo es `clients/`. La estructura relevante:

```
aguas-pruebas/                ← raíz del bundle, donde abres una terminal
└── clients/
    ├── README.md             ← navegación general (índice)
    ├── docs/                 ← este documento vive aquí
    ├── examples/sample_batch.json
    ├── postman/AguasDeCordoba.postman_collection.json
    ├── shared-vectors/merkle.json
    └── python/               ← paquete instalable + CLI
        ├── pyproject.toml
        ├── .env.example      ← plantilla; tu .env real se crea aquí
        ├── .out/             ← outputs efímeros (signed envelope, postman env)
        └── aguas_ingest/...
```

**Regla por defecto**: salvo que un bloque diga lo contrario, todos los comandos `uv run ...` y los outputs `.out/...` asumen que estás dentro de **`clients/python/`**. El `.env` que carga la CLI también vive ahí — si ejecutas desde otro sitio, no encuentra las variables y el comando falla.

Cuando un comando se ejecuta desde la raíz del bundle (Postman GUI navegando, Newman invocado a otro nivel, etc.), lo digo de forma explícita.

## Instalación

Desde la raíz del bundle:

```sh
cd clients/python                     # entras al directorio del paquete
uv sync --extra dev                   # crea .venv y descarga deps
cp .env.example .env                  # crea TU .env (gitignored) en clients/python/

uv run aguas-ingest keygen
# → imprime un AGUAS_PRIVATE_KEY=0x... que copias a .env (clients/python/.env)
#   La signer address aparece como comentario y se deriva en runtime — no hace
#   falta configurarla aparte.
```

A partir de aquí el `.venv` y el `.env` están en `clients/python/`. **Lanza siempre los comandos desde ese directorio**: la CLI llama a `load_dotenv()` sin argumentos, así que lee `.env` del directorio de trabajo actual.

### Alternativa con `pip` (sin `uv`)

Mismo cwd:

```sh
cd clients/python
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

aguas-ingest keygen
# → mismo output: copia AGUAS_PRIVATE_KEY=0x... al .env
cp .env.example .env   # si no lo habías hecho ya
```

**Equivalencia con el resto del documento**: todos los bloques de abajo usan `uv run aguas-ingest <subcomando>`. Si vas con pip, **activa el `.venv` en cada terminal nueva** (`source .venv/bin/activate` desde `clients/python/`) y elimina el prefijo `uv run`. El resto se lee idéntico:

| Con `uv`                                       | Con `pip` (con `.venv` activado)        |
|------------------------------------------------|-----------------------------------------|
| `uv run aguas-ingest sign --batch ... --out ...`   | `aguas-ingest sign --batch ... --out ...`   |
| `uv run aguas-ingest verify --envelope ...`        | `aguas-ingest verify --envelope ...`        |
| `uv run aguas-ingest mock-backend`                 | `aguas-ingest mock-backend`                 |
| `uv run aguas-ingest send --envelope ... --dry-run`| `aguas-ingest send --envelope ... --dry-run`|

Aviso para el flujo de **dos terminales** (tier 2): con `pip` tienes que recordar `source .venv/bin/activate` en la terminal del mock **y** en la del `send`. Con `uv run` te lo ahorras — `uv` resuelve el venv automáticamente desde `pyproject.toml`.

## Tier 1 — Firmar y verificar localmente (offline)

El bucle de desarrollo por defecto. Ningún proceso de fondo, ningún round-trip a red. **Una terminal en `clients/python/`**:

```sh
# Firmar el batch de ejemplo y emitir el signed envelope.
# --batch lee de ../examples/ (subiendo a clients/), --out escribe en .out/ del paquete.
uv run aguas-ingest sign \
  --batch ../examples/sample_batch.json \
  --out .out/signed.json

# Verificar offline: recupera la firma y recomputa el vehiclesRoot.
uv run aguas-ingest verify --envelope .out/signed.json
# → ok — firmado por 0x..., vehiclesRoot 0x...
```

Si `verify` da OK, el envelope ya pasaría las validaciones criptográficas del backend real (Merkle + ecrecover). Lo que aún no se ha probado es el camino HTTP: cómo se serializan los bytes en el wire, qué headers viajan, cómo se parsea la respuesta. Para eso, tier 2.

## Tier 2 — Round-trip HTTP contra el mock local

Necesitas **dos terminales**, las dos en `clients/python/` (las dos comparten el mismo `.env`).

**Terminal 1 — arranca el mock (bloquea hasta Ctrl-C):**

```sh
cd clients/python
uv run aguas-ingest mock-backend
# → mock-backend escuchando en http://127.0.0.1:41337
#     POST /v1/lodos/batches/dry-run  (Ctrl-C para parar)
```

**Terminal 2 — envía el envelope firmado contra el mock:**

```sh
cd clients/python
uv run aguas-ingest send \
  --envelope .out/signed.json \
  --base-url http://localhost:41337 \
  --dry-run
# → { "recovered_signer": "0x...", "vehicles_root": "0x..." }
```

El mock reutiliza los mismos algoritmos del paquete (`compute_vehicles_root`, `recover_signer`) y devuelve la **misma forma de respuesta** que el backend real: `{recoveredSigner, vehiclesRoot}` en 200 y `{error, message}` con los códigos canónicos (`vehicles_root_mismatch`, `signer_mismatch`, `invalid_signature`) en 4xx. Todo lo que pase aquí pasará bit-a-bit contra un backend real con mismo dominio y vehículos. Lo que el mock **no** simula: `SignerRegistry`, idempotencia y la ventana temporal de `dateIso`/`submittedAtIso` — esas reglas se descubren contra el dry-run real (tier 3).

### Postman / Newman contra el mock

Para usar la colección Postman necesitas un fichero de environment con la firma ya calculada. Lo genera el propio `sign` con `--postman-env`. **Desde `clients/python/`** (con el mock corriendo en la otra terminal):

```sh
uv run aguas-ingest sign \
  --batch ../examples/sample_batch.json \
  --out .out/signed.json \
  --postman-env .out/env.postman.json \
  --base-url http://localhost:41337
```

#### Opción A — Postman desktop (GUI)

En Postman: **File → Import**, y selecciona estos dos ficheros (la GUI navega desde la raíz del bundle):

- `clients/postman/AguasDeCordoba.postman_collection.json` (la colección)
- `clients/python/.out/env.postman.json` (el environment recién generado)

Selecciona el environment importado arriba a la derecha y dale al *Collection Runner*.

#### Opción B — Newman (headless)

**Desde `clients/python/`**:

```sh
npx newman run \
  ../postman/AguasDeCordoba.postman_collection.json \
  -e .out/env.postman.json
```

Con el mock arrancado en la terminal 1, todos los asserts pasan (5 requests, 9 assertions). `npx` cachea Newman por ti, no hace falta instalarlo global.
