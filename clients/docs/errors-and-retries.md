# Errores y reintentos

## Catálogo de errores

| Status | `error` | Retry | Causa típica |
|---|---|---|---|
| 400 | `vehicles_root_mismatch` | No | `vehiclesRoot` firmado no coincide con el recomputado. Probable: vehículos alterados o cálculo Merkle distinto. |
| 400 | *(varios)* | No | Validación Zod: firma con longitud inválida, `dateIso` mal formateado, `uint256` con caracteres no numéricos, etc. |
| 401 | `invalid_signature` | No | Firma no es ECDSA bien formada. |
| 401 | `signer_mismatch` | No | ecrecover devuelve una dirección distinta a `X-Signer`. Sugiere drift del dominio, drift del struct o modificación del body después de firmar. |
| 403 | `signer_not_authorized` | No | El firmante recuperado no está en el `SignerRegistry`. Contactar al backoffice para registrar la dirección. **Solo aplica al POST real** — ni el dry-run ni el mock local consultan el registro. |
| 409 | `batch_id_conflict` | No | Mismo `batchId` ya enviado con un payload distinto. Típicamente: re-firma con `submittedAtIso` nuevo (ver sección de idempotencia). **Solo aplica al POST real** — el mock local no persiste, así que tampoco genera conflict. |
| 503 | `batch_in_flight` | Sí, tras unos segundos | Otro request del mismo `batchId` está siendo procesado en paralelo. |
| 502/5xx | *(varios)* | Sí, backoff exponencial | Error del servidor o del nodo Besu. Reenviar **los mismos bytes**. |

Si el **dry-run real del backend de Aguas** (no el mock local ni `aguas-ingest verify`) responde `200`, los únicos modos de fallo que quedan para el POST real son `403`, `409` y `5xx`. Esa garantía es lo que hace del dry-run real la verificación autoritativa antes de producción — verify y mock comparten algoritmos con el cliente y no detectan drift de schema o de dominio EIP-712 contra el backend. Ver el desglose completo en [los tres niveles de validación](../README.md#tres-niveles-de-validación).

## Idempotencia — la trampa de `submittedAtIso`

**Regla de oro: firmar una sola vez por batch.** Persistir el struct firmado + la firma en tu lado, y en cada reintento reenviar **bit-a-bit los mismos bytes** (mismo body, mismo `X-Signature`). Es la única forma de que el backend reconozca el reintento como idempotente.

Qué pasa si regeneras `submittedAtIso` en cada reintento:

1. El struct firmado cambia (el campo es parte de `LodoBatch`).
2. La firma cambia.
3. El `dataHash` interno del backend cambia.
4. El backend ve "mismo `batchId`, payload distinto" → responde `409 batch_id_conflict`.
5. El batch queda bloqueado: el primer intento está persistido y ya no puedes sobreescribirlo.

## Patrón recomendado

```
por cada batch:
  generar batchId (UUIDv4).
  generar submittedAtIso (now).
  firmar el struct → (signed_envelope).
  persistir signed_envelope en disco/DB.
  loop:
    POST el signed_envelope tal cual.
    si 2xx → listo.
    si 5xx → sleep(backoff), continue.
    si 4xx → leer código del error; no reintentar; escalar.
```
