import os
import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


# El controlador de la báscula es obligatorio.
# Si no se puede importar, la API arranca pero /weights/read devolverá error 503.
try:
    from .controlador_bascula import query_weight_tcp, parse_f1
    BASCULA_DISPONIBLE = True
except ImportError:
    BASCULA_DISPONIBLE = False

# --- Configuración de la App ---
app = FastAPI(
    title="API de Pesaje de Camiones",
    description="Backend para el sistema de pesaje de la EDAR.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permite cualquier origen
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Constantes para el formato de batch ---
EDAR_DEFAULT = "la-golondrina"
POLIELECTROLITO_DEFAULT = "indefinido" # Valor por defecto
MATERIA_ORGANICA_DEFAULT = "indefinido" # Valor por defecto


# --- "Base de datos" en un fichero JSON ---
DB_FILE = Path(__file__).parent / "database.json"

def load_db():
    if not DB_FILE.exists():
        return {
            "trucks": [
                {"id": 1, "matricula": "1234-ABC", "tara": 8500.0},
                {"id": 2, "matricula": "5678-DEF", "tara": 12000.0},
                {"id": 3, "matricula": "9012-GHI", "tara": 7850.0},
            ],
            "weights": [],
            "next_truck_id": 4,
            "next_weight_id": 1,
        }
    return json.loads(DB_FILE.read_text(encoding="utf-8"))

def save_db(db_data):
    DB_FILE.write_text(json.dumps(db_data, indent=2, ensure_ascii=False), encoding="utf-8")

db = load_db()

# --- Modelos de datos (Pydantic) ---

class Truck(BaseModel):
    id: int
    matricula: str
    tara: float

class TruckCreate(BaseModel):
    matricula: str
    tara: float

class TareUpdate(BaseModel):
    tara: float

class Weight(BaseModel):
    id: int
    truck_id: int
    matricula: str
    peso_bruto: float
    tara: float
    peso_neto: float
    tipo_entrada: str
    timestamp: str

class WeightCreate(BaseModel):
    truck_id: int
    peso_bruto: float
    tara: float # El frontend envía la tara, la usamos para consistencia
    tipo_entrada: str = Field(..., pattern="^(bascula|manual|bascula_repeticion|manual_repeticion)$")

class WeightReadContext(BaseModel):
    contexto: str = Field(..., pattern="^(tara|peso)$")

class LastWeightResponse(BaseModel):
    ultima_pesada: Weight
    camion: Truck

# --- Endpoints: Salud y Estado ---

@app.get("/health", tags=["Estado"])
def health_check():
    """Comprueba el estado de la API y la conexión con la báscula."""
    return {
        "status": "ok",
        "bascula_disponible": BASCULA_DISPONIBLE,
        "timestamp": datetime.now().isoformat(),
    }

# --- Endpoints: Camiones (/trucks) ---

@app.get("/trucks", response_model=List[Truck], tags=["Camiones"])
def list_trucks():
    """Devuelve la lista de todos los camiones registrados."""
    return sorted(db["trucks"], key=lambda t: t["matricula"])

@app.post("/trucks", response_model=Truck, status_code=201, tags=["Camiones"])
def create_truck(truck_data: TruckCreate):
    """Registra un nuevo camión."""
    matricula = truck_data.matricula.strip().upper()
    if any(t["matricula"] == matricula for t in db["trucks"]):
        raise HTTPException(
            status_code=409,
            detail=f"Ya existe un camión con la matrícula {matricula}"
        )

    new_truck = {
        "id": db["next_truck_id"],
        "matricula": matricula,
        "tara": truck_data.tara,
    }
    db["trucks"].append(new_truck)
    db["next_truck_id"] += 1
    save_db(db)
    return new_truck

@app.put("/trucks/{truck_id}/tare", response_model=Truck, tags=["Camiones"])
def update_truck_tare(truck_id: int, tare_data: TareUpdate):
    """Actualiza la tara de un camión existente."""
    truck = next((t for t in db["trucks"] if t["id"] == truck_id), None)
    if not truck:
        raise HTTPException(status_code=404, detail=f"Camión con id {truck_id} no encontrado.")

    truck["tara"] = tare_data.tara
    save_db(db)
    return truck

# --- Endpoints: Pesadas (/weights) ---

@app.post("/weights/read", tags=["Báscula"])
def read_weight_from_scale(body: WeightReadContext = Body(...)):
    """
    Lee el peso desde la báscula real (MATRIX II vía TCP).
    Nunca simula datos. Si la báscula no responde o da un peso no válido,
    devuelve un error descriptivo para que el frontend ofrezca reintentar
    o introducir el peso manualmente.
    """
    if not BASCULA_DISPONIBLE:
        return {
            "ok": False,
            "error": True,
            "tipo_error": "no_disponible",
            "mensaje": "El módulo de báscula no está instalado en este servidor."
        }

    try:
        lectura = query_weight_tcp()
    except OSError as e:
        return {
            "ok": False,
            "error": True,
            "tipo_error": "timeout",
            "mensaje": f"No se pudo conectar con la báscula: {e}"
        }
    except Exception as e:
        return {
            "ok": False,
            "error": True,
            "tipo_error": "desconocido",
            "mensaje": f"Error inesperado al leer la báscula: {e}"
        }

    # Trama recibida pero con error de parseo
    if lectura.get("error"):
        return {
            "ok": False,
            "error": True,
            "tipo_error": "trama_invalida",
            "mensaje": f"Trama inválida recibida de la báscula: {lectura['error']}"
        }

    # Trama válida pero peso no estable
    if not lectura.get("valida"):
        estado = lectura.get("estado", "desconocido")
        mensajes = {
            "inestable":  "La báscula está inestable. Asegúrese de que el camión esté completamente detenido.",
            "sobrecarga": "Sobrecarga en la báscula. Verifique el peso.",
            "invalido":   "Lectura inválida recibida de la báscula.",
        }
        return {
            "ok": False,
            "error": True,
            "tipo_error": estado,
            "mensaje": mensajes.get(estado, f"Estado no válido: {estado}")
        }

    # Lectura correcta
    return {
        "ok": True,
        "error": False,
        "peso": lectura["peso"],
        "unidad": lectura.get("unidad", "kg"),
        "modo": lectura.get("modo", "bruto"),
        "estado": lectura.get("estado"),
        "timestamp": datetime.now().isoformat()
    }


@app.post("/weights/manual", response_model=Weight, status_code=201, tags=["Pesadas"])
def register_weight(weight_data: WeightCreate):
    """Registra una nueva pesada (desde báscula o manual)."""
    truck = next((t for t in db["trucks"] if t["id"] == weight_data.truck_id), None)
    if not truck:
        raise HTTPException(status_code=404, detail=f"Camión con id {weight_data.truck_id} no encontrado.")

    # Usar la tara de la BD como fuente de verdad, no la que envía el cliente
    tara = truck["tara"]
    peso_bruto = weight_data.peso_bruto
    peso_neto = peso_bruto - tara

    if peso_neto < 0:
        raise HTTPException(
            status_code=400,
            detail=f"El peso bruto ({peso_bruto} kg) debe ser mayor que la tara ({tara} kg)."
        )

    now = datetime.now()

    # 1. Construir el documento JSON con el formato solicitado para imprimir
    documento_batch = {
        "batch": {
            "batchId": f"batch-example-{db['next_weight_id']:03d}",
            "edar": EDAR_DEFAULT,
            "dateIso": now.strftime("%Y-%m-%d"),
            "polielectrolito": POLIELECTROLITO_DEFAULT,
            "materiaOrganicaBp": MATERIA_ORGANICA_DEFAULT,
            "submittedAtIso": now.isoformat(),
            "vehicle": {
                "vehicleId": truck["matricula"],
                "timeIso": now.strftime("%Y-%m-%d"),
                "weightKg": peso_neto,
            }
        }
    }

    # 2. Imprimir en consola el documento generado antes de guardarlo
    print("\n--- DOCUMENTO DE PESADA GENERADO ---")
    print(json.dumps(documento_batch, indent=2, ensure_ascii=False))
    print("------------------------------------\n")

    # La lógica para guardar en la BD interna y responder al frontend se mantiene
    # igual para no romper la aplicación existente.
    print("impresion")
    new_weight = {
        "id": db["next_weight_id"],
        "truck_id": truck["id"],
        "matricula": truck["matricula"],
        "peso_bruto": peso_bruto,
        "tara": tara,
        "peso_neto": peso_neto,
        "tipo_entrada": weight_data.tipo_entrada,
        "timestamp": now.isoformat(),
    }
    db["weights"].append(new_weight)
    db["next_weight_id"] += 1
    save_db(db)
    return new_weight

@app.post("/weights/repeat", response_model=LastWeightResponse, tags=["Pesadas"])
def get_last_weight_data():
    """Devuelve los datos de la última pesada para repetirla."""
    if not db["weights"]:
        raise HTTPException(
            status_code=404,
            detail="No hay ninguna pesada anterior registrada en esta sesión"
        )

    last_weight = db["weights"][-1]
    truck = next((t for t in db["trucks"] if t["id"] == last_weight["truck_id"]), None)

    if not truck:
        # Esto sería un estado inconsistente de la BD, pero lo manejamos por si acaso
        raise HTTPException(
            status_code=404,
            detail=f"No se encontró el camión (id: {last_weight['truck_id']}) de la última pesada."
        )

    return {
        "ultima_pesada": last_weight,
        "camion": truck,
    }

# --- Ejecución para desarrollo ---

if __name__ == "__main__":
    import uvicorn
    print("--- API de Pesaje ---")
    print(f"Báscula disponible: {BASCULA_DISPONIBLE}")
    if not BASCULA_DISPONIBLE:
        print("ADVERTENCIA: controlador_bascula.py no encontrado. /weights/read devolverá error.")
    print("-----------------------")
    uvicorn.run(app, host="0.0.0.0", port=8080)