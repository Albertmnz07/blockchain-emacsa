# Postman fixtures

Fixtures estáticos que cubren los modos de error del endpoint `/v1/lodos/batches/dry-run` (y, por la invariante del backend, del POST real).

Generados por `clients/python/scripts/gen_postman_fixtures.py` con una clave privada determinista. Para regenerar (p. ej. si cambia el algoritmo de firma o el dominio EIP-712):

```sh
cd clients/python
uv run python scripts/gen_postman_fixtures.py
```

Cada fichero tiene la forma:

```json
{
  "headers": { "X-Signature": "...", "X-Signer": "...", "Content-Type": "..." },
  "body":    { "batch": { ... }, "vehicles": [ ... ] },
  "expectation": { "status": 400, "error": "vehicles_root_mismatch" }
}
```

`expectation` documenta el status HTTP y el `error` code que el endpoint debería devolver. La colección Postman los repite como assertions.

## Catálogo

| Fixture | Status | `error` | Disparador |
|---|---|---|---|
| `happy_baseline.json` | 200 | — | firma válida; el backend recupera el mismo `X-Signer`. |
| `wrong_vehicles_root.json` | 400 | `vehicles_root_mismatch` | `vehiclesRoot` manipulado tras firmar; el backend recomputa y detecta divergencia. |
| `tampered_after_signing.json` | 401 | `signer_mismatch` | campo del struct modificado tras firmar; ecrecover devuelve otra dirección. |
| `malformed_signature.json` | 400 | *(validación Zod)* | firma con longitud inválida. |
| `bad_date_iso.json` | 400 | *(validación Zod)* | `dateIso` no cumple `YYYY-MM-DD`. |

## Contrato cross-language

`backend/src/modules/ingest/handler.test.ts` carga cada fixture y lo inyecta contra el handler real. Si el cliente Python firma de forma incompatible con la recuperación TypeScript, `happy_baseline` falla antes de merge. No borrar ese bloque de tests sin sustituirlo por uno equivalente.
