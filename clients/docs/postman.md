# Postman y Newman

Dos flujos según contra qué pruebes y qué quieras cubrir:

| Flujo | Colección | Cobertura |
|---|---|---|
| **Baseline dry-run** | `clients/postman/AguasDeCordoba.postman_collection.json` (versionada) | 5 requests dry-run, sin Basic Auth, contra cualquier backend |
| **Matriz completa** | `clients/python/.out/postman/AguasDeCordoba.postman_collection.json` (generada al vuelo) | 9 requests = 5 dry-run + 4 POST real (201 + 200 replay + 409 + 403), Basic Auth a nivel colección |

El primero te vale para iterar el cliente contra el `aguas-ingest mock-backend` local. El segundo cubre la matriz de respuestas del POST real y requiere un backend con `SignerRegistry` poblado + Caddy con Basic Auth (ej. el entorno protegido de Aguas).

## Flujo 1 — Baseline dry-run

### Importar

1. Postman → File → Import → arrastra `clients/postman/AguasDeCordoba.postman_collection.json`.
2. Genera la environment (siguiente sección).
3. Importa `clients/python/.out/env.postman.json` y selecciónalo arriba a la derecha.

### Regenerar la environment

Cada vez que cambie el batch o la clave:

```sh
cd clients/python
uv run aguas-ingest sign \
  --batch ../examples/sample_batch.json \
  --out .out/signed.json \
  --postman-env .out/env.postman.json
```

Sin `--base-url` el environment apunta al mock local (`http://127.0.0.1:41337`). Reimporta el fichero en Postman tras cada regeneración — Postman toma una copia al importar y no observa el disco.

### Ejecutar en headless con Newman

Desde `clients/python/`:

```sh
npx newman run \
  ../postman/AguasDeCordoba.postman_collection.json \
  -e .out/env.postman.json
```

Exit code `0` = todos los asserts pasan. Distinto de cero = al menos un request falló; Newman imprime el summary con los asserts fallados.

## Flujo 2 — Matriz completa con `aguas-ingest gen-postman`

Un único comando produce el bundle entero (colección + environment + 4 fixtures POST real) en `.out/postman/`:

```sh
cd clients/python
# .env rellenado con valores del entorno protegido (Caddy URL, chainId,
# verifyingContract, basic auth user+pass, AGUAS_PRIVATE_KEY = la "key buena"
# registrada en SignerRegistry).
uv run aguas-ingest gen-postman
```

Output:

```
.out/postman/
├── AguasDeCordoba.postman_collection.json   ← matriz completa
├── env.postman.json                         ← env con basic auth + signature
└── fixtures/
    ├── happy_real_post.json                 ← 201 Created
    ├── idempotent_replay.json               ← 200 OK (post PR #143)
    ├── conflict_real_post.json              ← 409 batch_id_conflict
    └── unauthorized_real_post.json          ← 403 signer_not_authorized
```

Importa los dos JSONs (collection + env) en Postman desktop y dale al *Collection Runner*. Newman:

```sh
npx newman run \
  .out/postman/AguasDeCordoba.postman_collection.json \
  -e .out/postman/env.postman.json
```

### Estados que cubre la matriz

| # | Request | Status | Por qué |
|---|---|---|---|
| 1 | dry-run env-driven | 200 | sanity check criptográfico contra `/dry-run` |
| 2-5 | dry-run errores estáticos | 400/401 | `wrong_vehicles_root`, `tampered_after_signing`, `malformed_signature`, `bad_date_iso` |
| 6 | `happy_real_post` | 201 | primer POST con `batchId` único, key buena |
| 7 | `idempotent_replay` | 200 | mismos bytes que el #6 → eco del `txHash` original (RFC 9110 §15.3.2) |
| 8 | `conflict_real_post` | 409 | mismo `batchId` que #6 con `polielectrolito` mutado y refirmado |
| 9 | `unauthorized_real_post` | 403 | firma con `Account.create()` ad-hoc — no está en `SignerRegistry` |

El test del #7 captura el `txHash` del #6 en `pm.environment` y verifica que el #7 devuelve **el mismo `txHash`**. Eso es lo que demuestra que el replay reusa la fila on-chain en lugar de doble-submitear.

### Orden load-bearing

El runner de Postman respeta el orden de la colección. La matriz necesita correr happy → replay → conflict en ese orden — si los lanzas individualmente fuera de orden, los asserts fallan (replay sin happy = 404 fila inexistente; conflict sin happy = idempotent 200/201 en lugar de 409).

`unauthorized_real_post` es independiente (su `batchId` es distinto y el 403 fires antes de la idempotencia).

### Re-ejecuciones

Cada `aguas-ingest gen-postman` inyecta un nuevo timestamp en el `batchId`, así que cada bundle generado es **single-shot**: una corrida del runner, una matriz pasada. Para volver a correr → regenerar bundle.

Si quieres replays masivos del happy path (load testing), Postman estático no sirve — necesitas el CLI en bucle (`aguas-ingest sign + send` con `batchId` distintos).

## Mantenimiento de fixtures estáticos

Si cambia el algoritmo de firma o el dominio EIP-712, los fixtures estáticos del baseline dejan de ser válidos. Regenerar:

```sh
cd clients/python
AGUAS_FIXTURE_PRIVATE_KEY=0x... uv run python scripts/gen_postman_fixtures.py
uv run python scripts/gen_postman_collection.py
```

`AGUAS_FIXTURE_PRIVATE_KEY` puede ser cualquier valor — los 4 fixtures del baseline disparan errores que fires antes/independientemente de la verificación de firma, así que el signer no importa funcionalmente. Para reproducir bit-a-bit los fixtures versionados, usa la misma key que generó la versión actual.

> **Por qué no se hardcodea**: para no establecer el patrón de "es solo para fixtures, no pasa nada por commitearla". Si mañana alguien añade una key real con esa misma justificación, ya estamos perdidos. La key vive en tu shell durante el regenerado y se olvida al cerrar.

El backend ejecuta un test (`src/modules/ingest/handler.test.ts`) que inyecta los fixtures Python contra el handler real. Si la regeneración se olvida tras un cambio de algoritmo, ese test falla antes de merge — sirve como gate de CI.

## Ojo a la idempotencia

El backend tiene idempotencia content-addressed sobre `batchId`:

- **Mismo `batchId` + mismo payload** → 200 OK (post PR #143; antes 201) con el `txHash` original. Pensado para que EMACSA reintente bytes idénticos sin riesgo de doble-submit.
- **Mismo `batchId` + payload distinto** → 409 `batch_id_conflict`. Cualquier cambio en el body bajo el mismo `batchId` se rechaza.
- **Mismo `batchId`, payload pendiente** (txHash todavía null) → 503 `BatchInFlightError`. Otro caller está procesando.

Para reintentos en producción: **reenviar los mismos bytes con la misma firma**. Regenerar `submittedAtIso` o re-firmar produce un `dataHash` distinto → 409. Si tu wrapper de retry firma fresh cada intento, vas a ver 409 espurios.
