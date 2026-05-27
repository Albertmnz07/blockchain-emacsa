import socket
import json
from contextlib import closing
from datetime import datetime
from pathlib import Path

INDICATOR_IP   = "192.168.101.150"
INDICATOR_PORT = 1234
TIMEOUT        = 5.0
OUTPUT_DIR     = Path(__file__).parent / "pesadas"

# Mapeos según §2.7.1.2 del manual MATRIX II
UNIDAD_MAP = {"K": "kg", "T": "t", "G": "g", "L": "lb", " ": ""}
MODO_MAP   = {"G": "bruto", "N": "neto"}
ESTADO_MAP = {" ": "valido", "M": "inestable", "O": "sobrecarga", "I": "invalido"}


MAX_FRAME_BYTES = 256  # una trama F1 nunca supera ~20 bytes; límite de seguridad

def query_weight_tcp(host=INDICATOR_IP, port=INDICATOR_PORT, timeout=TIMEOUT) -> dict:
    with closing(socket.create_connection((host, port), timeout)) as s:
        s.settimeout(timeout)

        buf = s.recv(128)
        
    return parse_f1(buf)


def parse_f1(raw: bytes) -> dict:
    s = raw.decode("ascii", errors="replace").strip()

    if not s:
        return {"raw_hex": raw.hex(), "error": "trama vacía", "raw": s}

    import re
    match = re.search(r"(\d+)([a-zA-Z]+)", s)
    
    if not match:
        return {"raw_hex": raw.hex(), "error": f"Formato inesperado: '{s}'", "raw": s}
        
    peso_str, unidad_raw = match.groups()

    try:
        peso = int(peso_str)
    except ValueError as e:
        return {"raw_hex": raw.hex(), "error": f"Peso no numérico: '{peso_str}'", "raw": s}

    unidad = UNIDAD_MAP.get(unidad_raw.upper(), unidad_raw.lower())

    return {
        "raw_hex":   raw.hex(),
        "raw_ascii": s,
        "peso":      peso,
        "unidad":    unidad,
        "modo":      "bruto",
        "estado":    "valido",
        "valida":    True,
    }

def save_record(record: dict, out_dir: Path = OUTPUT_DIR) -> Path:
    """Guarda la pesada en disco. No modifica el dict original."""
    out_dir.mkdir(parents=True, exist_ok=True)
    now   = datetime.now()
    ts_id = now.strftime("%Y%m%dT%H%M%S") + f"_{now.microsecond // 1000:03d}"

    # Copia para no mutar el argumento
    payload = {
        **record,
        "id":        ts_id,
        "timestamp": now.isoformat(timespec="milliseconds"),
        "indicador": {"ip": INDICATOR_IP, "puerto": INDICATOR_PORT},
    }

    path = out_dir / f"pesada_{ts_id}.json"
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


if __name__ == "__main__":
    record = query_weight_tcp()
    saved  = save_record(record)
    print(f"✓ Pesada guardada en: {saved}")
    print(json.dumps(record, indent=2, ensure_ascii=False))