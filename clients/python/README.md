# aguas-ingest

Cliente Python para la API de ingesta de Aguas de Córdoba. Firma los batches con EIP-712, calcula el `vehiclesRoot` con el mismo algoritmo Merkle del backend, y envía los requests al endpoint real o al de verificación (`dry-run`). Incluye un mock backend stdlib para round-trip HTTP local sin Docker.

La guía de integración completa (contrato EIP-712, catálogo de errores, los tres niveles de validación, Postman, reintentos) vive en [`clients/README.md`](../README.md).

## Instalación

Con `uv`:

```sh
cd clients/python
uv sync
uv run aguas-ingest --help
```

Con `pip`:

```sh
cd clients/python
pip install -e .[dev]
aguas-ingest --help
```

## Mock backend para round-trip HTTP

El subcomando `mock-backend` arranca un servidor stdlib local que mimetiza `POST /v1/lodos/batches/dry-run` con la misma forma de respuesta que el backend real:

```sh
uv run aguas-ingest mock-backend                    # 127.0.0.1:41337 por defecto
uv run aguas-ingest mock-backend --port 8080        # otro puerto
uv run aguas-ingest mock-backend --host 0.0.0.0     # exponer (cuidado en redes compartidas)
```

Reutiliza los algoritmos del propio paquete, así que no hay riesgo de divergencia con el cliente. Pensado para que el integrador pruebe su pipeline HTTP completo sin Docker, sin red y sin esperar a que Aguas publique una URL de dry-run. Detalle del flujo en [`clients/docs/quickstart.md`](../docs/quickstart.md) (tier 2).

## Tests

```sh
uv run pytest     # o: pytest
```
