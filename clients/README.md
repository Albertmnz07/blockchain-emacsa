# Aguas de Córdoba — bundle de integración

Cliente Python + colección Postman + ejemplos para integrarse con la API de
ingesta de batches de lodos. Pensado para validar en pocos minutos qué
viaja en cada POST y comprobar que el pipeline del integrador encaja, antes
de empezar a firmar con clave propia.

## Qué viene en este paquete

- `python/` — cliente CLI (`aguas-ingest`) + librería Python instalable.
- `python/.env` — variables del entorno EMACSA pre-rellenadas; **solo falta
  `AGUAS_PRIVATE_KEY`**.
- `python/.out/postman/` — bundle Postman pre-firmado con una clave
  registrada en el backend, listo para importar y lanzar (un único run, ver
  más abajo).
- `postman/` — colección Postman baseline (5 requests dry-run).
- `examples/` — `sample_batch.json` (entrada de `sign`) y
  `signed-example.json` (salida de `sign` ya firmada).
- `docs/` — documentación de referencia (firma, errores, troubleshooting…).
- `shared-vectors/` — vectores Merkle de oráculo cross-language para
  re-implementaciones del firmador en otro lenguaje.

## Requisitos

- **Python 3.11+** con [`uv`](https://docs.astral.sh/uv/) (recomendado) o
  `pip` — para el cliente CLI.
- **Postman desktop** (entorno gráfico) **o** **Node** (incluye `npm`/`npx`,
  para lanzar Newman headless) — cualquiera de los dos sirve para ejecutar
  la colección.

## 1. Instalar el cliente Python

Desde la raíz del bundle, una sola vez:

```sh
cd clients/python
uv sync --extra dev
```

Crea `.venv` con todas las dependencias resueltas. Necesario para los
comandos `aguas-ingest …` (`keygen`, `gen-postman`, `sign`) que aparecen
más abajo.

## 2. Lanzar el bundle pre-firmado

El zip incluye `clients/python/.out/postman/` ya pre-firmado con una clave
registrada en el `SignerRegistry` del backend, así que se puede ver el
flujo completo en verde sin generar nada nuevo. Dos formas, equivalentes:

### Opción A — Newman (CLI, sin entorno gráfico)

Desde `clients/python/`:

```sh
npx newman run \
  .out/postman/AguasDeCordoba.postman_collection.json \
  -e .out/postman/env.postman.json
```

`npx` descarga Newman al cache de `npm` en la primera invocación; no hace
falta instalarlo global. Salida: 9 requests, asserts en verde.

### Opción B — Postman desktop (entorno gráfico)

1. Abrir Postman → **File → Import** y arrastrar estos dos ficheros:
   - `clients/python/.out/postman/AguasDeCordoba.postman_collection.json`
   - `clients/python/.out/postman/env.postman.json`
2. Seleccionar el environment importado (desplegable arriba a la derecha).
3. Botón **Collection Runner → Run**.

Cualquiera de las dos opciones ejecuta los mismos 9 requests: 5 dry-run
criptográficos + 4 POST real (create → replay idempotente → conflict →
unauthorized).

> **Nota — bundle single-shot.** El `batchId` de la matriz lleva un
> timestamp único, así que la primera corrida crea la entrada en el backend
> y las siguientes la encuentran como replay. Al lanzar el runner una
> segunda vez, el request `happy_real_post` cambia de `201 Created` a
> `200 OK` (idempotencia funcionando bien, solo cambia el código). No es
> un fallo del bundle; para una matriz limpia, regenerar con `gen-postman`
> (sección 4) y, si se está usando Postman desktop, **reimportar los dos
> JSON de `.out/postman/`** (la colección y el environment) — Postman fija
> una copia al importar y no observa el disco. Newman no necesita
> re-importar: la siguiente corrida lee los ficheros frescos.

## 3. Cómo es un payload

### Antes de firmar — `examples/sample_batch.json`

Esto es lo que produce el sistema del integrador al consolidar los datos
de un día:

```json
{
  "batch": {
    "batchId": "batch-example-001",
    "edar": "la-golondrina",
    "dateIso": "2026-04-16",
    "polielectrolito": "1234",
    "materiaOrganicaBp": "5678",
    "submittedAtIso": "2026-04-16T08:00:00+00:00"
  },
  "vehicles": [
    {"vehicleId": "truck-01", "timeIso": "2026-04-16T09:00:00+00:00", "weightKg": "1200"},
    {"vehicleId": "truck-02", "timeIso": "2026-04-16T10:00:00+00:00", "weightKg": "950"},
    {"vehicleId": "truck-03", "timeIso": "2026-04-16T11:30:00+00:00", "weightKg": "1500"}
  ]
}
```

### Después de firmar — `examples/signed-example.json`

El proceso `sign` añade dos cosas:

1. **`vehiclesRoot`** dentro de `batch` — raíz Merkle calculada sobre el
   array `vehicles`. El backend la recomputa y la compara para detectar
   cualquier alteración de los vehículos.
2. **Dos cabeceras HTTP** que viajan junto al body en el POST:

```
POST /api/v1/lodos/batches
Content-Type: application/json
X-Signature: 0x<130 hex chars>     ← firma EIP-712 del struct LodoBatch
X-Signer:    0x<40 hex chars>      ← address pública derivada de la clave privada

{ "batch": { ..., "vehiclesRoot": "0x..." }, "vehicles": [...] }
```

El body en sí es JSON convencional. Toda la criptografía está en los
headers y en el `vehiclesRoot`.

## 4. Uso de clave propia

El bundle pre-firmado solo sirve para ver el flujo end-to-end. Para firmar
con la clave del integrador (la que se usará en producción):

### 4.1. Generar el par de claves

```sh
uv run aguas-ingest keygen
```

Imprime dos líneas:

```
AGUAS_PRIVATE_KEY=0x<64 hex>     ← copiar a python/.env (NO compartir)
# Signer: 0x<40 hex>             ← remitir esta dirección a Tritemius
```

### 4.2. Cargar la private key en `python/.env`

Reemplazar la línea vacía `AGUAS_PRIVATE_KEY=` por la que imprime `keygen`.
Las demás variables ya están pre-rellenadas.

### 4.3. Enviar la signer address

Remitir por correo la dirección de la línea `# Signer:`. La **clave
privada nunca sale del equipo del integrador**.

### 4.4. Confirmación de alta y regeneración del bundle

Una vez confirmada el alta de la address en el `SignerRegistry` del
backend (cuestión de minutos), regenerar el bundle Postman:

```sh
uv run aguas-ingest gen-postman
```

Volver a lanzar Newman o Postman como en la sección 2 — ahora los 9
requests pasan firmados con la clave del integrador.

## 5. Para producción — firma de batches reales

Cuando el sistema del integrador produzca un batch real (no el ejemplo),
se firma con:

```sh
uv run aguas-ingest sign --batch tu_batch.json --out signed.json
```

Ejemplo concreto, ejecutado desde `clients/python/` y usando el batch de
muestra que viene en `examples/`:

```sh
uv run aguas-ingest sign --batch ../examples/sample_batch.json --out signed.json
```

Tanto `--batch` como `--out` aceptan rutas relativas al directorio actual,
así que en este caso `signed.json` queda en `clients/python/`. El fichero
contiene el body + headers `X-Signature`/`X-Signer` listos para POSTear
a `/api/v1/lodos/batches`. El cliente CLI también puede ejecutar el POST
(`aguas-ingest send`) — útil para testing; en producción es el sistema
HTTP del integrador quien se encarga.

Detalle del struct firmado, dominio EIP-712 y contrato HTTP completo en
[`docs/signing.md`](./docs/signing.md). Catálogo de errores y patrón de
reintento idempotente en [`docs/errors-and-retries.md`](./docs/errors-and-retries.md).

## Documentación de referencia

- [`docs/quickstart.md`](./docs/quickstart.md) — flujo paso a paso, incluido el mock local para iteración offline.
- [`docs/signing.md`](./docs/signing.md) — contrato de firma: dominio EIP-712, struct `LodoBatch`, algoritmo Merkle, contrato HTTP.
- [`docs/postman.md`](./docs/postman.md) — colecciones Postman/Newman al detalle, matriz de 9 requests, mantenimiento de fixtures.
- [`docs/errors-and-retries.md`](./docs/errors-and-retries.md) — códigos de error, idempotencia, patrón de retry.
- [`docs/troubleshooting.md`](./docs/troubleshooting.md) — checklists para los errores más comunes.
