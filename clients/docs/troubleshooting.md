# Troubleshooting

## `signer_mismatch`

Es el error más incómodo porque no dice *por qué* la firma no coincide. Checklist, en orden de probabilidad:

1. **Dominio drift**: ¿`chainId`, `verifyingContract`, `name`, `version` coinciden exactamente con los del backend? Un carácter diferente en `name` rompe la recuperación. Comparar contra la tabla de [signing.md](./signing.md#dominio-eip-712).
2. **Types drift**: ¿el orden de los campos en `LODO_BATCH_TYPES` coincide con el del backend? EIP-712 los hashea en orden de declaración.
3. **Mutación post-firma**: ¿algún middleware o proxy está reserializando el JSON (espacios, orden de keys, coerción `str`→`int`)? El body tiene que llegar al backend bit-a-bit idéntico. `aguas-ingest sign --out` produce el JSON canónico; cualquier reserialización intermedia lo rompe.
4. **Tipo numérico**: `polielectrolito`, `materiaOrganicaBp`, `weightKg` se firman como `uint256` (numérico) pero se envían como string. El cliente Python ya hace esto bien; verifica que tu propio código no los esté pasando al signer como string o como float.
5. **`vehiclesRoot` local**: ¿calculas el root con el mismo algoritmo que el backend? Los vectores `clients/shared-vectors/merkle.json` son la referencia.

Ante cualquier bloqueo, ejecutar `aguas-ingest verify --envelope .out/signed.json` localmente desde `clients/python/`: si el propio cliente no puede recuperar la firma, el backend tampoco va a poder.

## `vehicles_root_mismatch`

Casi siempre un bug de cálculo local. Pasos:

1. Loguear `vehiclesRoot` antes de firmar y comparar con lo que emite `compute_vehicles_root(vehicles)`.
2. Si divergen, el batch se firmó con un root calculado por otro código (legacy, otra librería). Usar el de `aguas_ingest.merkle`.
3. Si coinciden pero el backend sigue rechazándolo, comparar contra `clients/shared-vectors/merkle.json`: reproducir uno de esos casos debería dar el mismo `expectedRoot`.

## `batch_id_conflict` tras un 5xx

Pista casi segura: re-firma con `submittedAtIso` nuevo en el reintento. Ver [errors-and-retries.md](./errors-and-retries.md#idempotencia--la-trampa-de-submittedatiso). Cómo desbloquearse:

- Generar un **`batchId` nuevo**, firmar y reenviar.
- El batch original queda en la DB con el primer intento; no se puede sobreescribir.

## El dry-run pasa pero el POST real da 403

Causa única: la dirección no está registrada en el `SignerRegistry` on-chain. El dry-run no consulta el registro; el POST real sí. Escalar al equipo backoffice para que ejecuten `addSigner(tu_dirección)`.

## Newman no encuentra la colección

Rutas relativas: el quickstart asume Newman lanzado desde `clients/python/` con `../postman/AguasDeCordoba.postman_collection.json` como colección. Si lo lanzas desde otro directorio, ajusta la ruta. Verificar que el fichero `.out/env.postman.json` generado por `aguas-ingest sign --postman-env` tiene los cuatro valores (`baseUrl`, `signerAddress`, `signature`, `batchBody`) no vacíos — si alguno lo está, el sign no terminó bien y el request se envía sin headers válidos.
