/* ═══════════════════════════════════════════════════════════
   app.js — Lógica principal del sistema de pesaje
   EDAR EMACSA · Vanilla JS · sin frameworks
   ═══════════════════════════════════════════════════════════

   Para conectar con la API real, cambia únicamente:
       const API_BASE = "http://localhost:8080";
   por la URL de la API real.
   ═══════════════════════════════════════════════════════════ */

"use strict";

// ── Configuración ────────────────────────────────────────
const API_BASE = "http://localhost:8080";

// ── Estado global de la aplicación ──────────────────────
const estado = {
  // Camión seleccionado actualmente
  camionSeleccionado: null,   // { id, matricula, tara }

  // Flujo de báscula reutilizable
  basculaContexto: null,      // "tara" | "peso"
  basculaMatriculaNueva: null,// matrícula pendiente de crear
  basculaEsRepeticion: false, // true si viene de "Repetir pesada anterior"
  basculaEsTara: false,       // true si viene de "Volver a tarar"

  // Peso confirmado desde báscula o manual
  pesoBrutoConfirmado: null,

  // Datos de la última pesada (para "Repetir")
  ultimaPesadaData: null,
};

// ── Navegación entre pantallas ───────────────────────────

/**
 * Muestra una pantalla y oculta el resto.
 * @param {string} idPantalla — id del elemento <section>
 */
function mostrarPantalla(idPantalla) {
  document.querySelectorAll(".pantalla").forEach((p) => {
    p.classList.remove("activa");
  });
  const pantalla = document.getElementById(idPantalla);
  if (pantalla) {
    pantalla.classList.add("activa");
    // Scroll al inicio al cambiar de pantalla
    window.scrollTo(0, 0);
  }
}

// ── Utilidades DOM ───────────────────────────────────────

function mostrar(el) {
  if (typeof el === "string") el = document.getElementById(el);
  el?.classList.remove("oculto");
}

function ocultar(el) {
  if (typeof el === "string") el = document.getElementById(el);
  el?.classList.add("oculto");
}

function setText(idOrEl, texto) {
  const el = typeof idOrEl === "string" ? document.getElementById(idOrEl) : idOrEl;
  if (el) el.textContent = texto;
}

function setHTML(idOrEl, html) {
  const el = typeof idOrEl === "string" ? document.getElementById(idOrEl) : idOrEl;
  if (el) el.innerHTML = html;
}

function mostrarError(idEl, texto) {
  const el = document.getElementById(idEl);
  if (!el) return;
  el.textContent = texto;
  mostrar(el);
}

function ocultarError(idEl) {
  ocultar(idEl);
}

function habilitarBtn(id, habilitar = true) {
  const btn = document.getElementById(id);
  if (btn) btn.disabled = !habilitar;
}

// ── API — Llamadas al backend ────────────────────────────

async function apiGet(ruta) {
  const res = await fetch(`${API_BASE}${ruta}`);
  const json = await res.json();
  if (!res.ok) throw new Error(json.error || `Error ${res.status}`);
  return json;
}

async function apiPost(ruta, cuerpo) {
  const res = await fetch(`${API_BASE}${ruta}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cuerpo),
  });
  const json = await res.json();
  if (!res.ok) throw new Error(json.error || `Error ${res.status}`);
  return json;
}

async function apiPut(ruta, cuerpo) {
  const res = await fetch(`${API_BASE}${ruta}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cuerpo),
  });
  const json = await res.json();
  if (!res.ok) throw new Error(json.error || `Error ${res.status}`);
  return json;
}

// ══════════════════════════════════════════════════════════
// PANTALLA 1 — INICIO
// ══════════════════════════════════════════════════════════

document.getElementById("btn-nueva-pesada").addEventListener("click", () => {
  // Resetear estado
  estado.camionSeleccionado = null;
  estado.basculaEsRepeticion = false;
  estado.basculaEsTara = false;
  estado.pesoBrutoConfirmado = null;
  estado.basculaMatriculaNueva = null;

  cargarListaCamiones();
  mostrarPantalla("pantalla-camion");
});

document.getElementById("btn-repetir-pesada").addEventListener("click", async () => {
  const msgEl = document.getElementById("msg-inicio");
  msgEl.className = "mensaje";
  ocultar(msgEl);

  try {
    const data = await apiPost("/weights/repeat", {});
    estado.ultimaPesadaData = data.ultima_pesada;
    estado.camionSeleccionado = data.camion;
    estado.basculaEsRepeticion = true;
    estado.basculaEsTara = false;

    // Ir directamente a báscula para peso bruto
    iniciarPantallaBascula("peso");
  } catch (err) {
    msgEl.className = "mensaje error";
    msgEl.textContent = err.message;
    mostrar(msgEl);
  }
});

// ══════════════════════════════════════════════════════════
// PANTALLA 2 — SELECCIÓN DE CAMIÓN
// ══════════════════════════════════════════════════════════

async function cargarListaCamiones() {
  const listaEl = document.getElementById("lista-camiones");
  const loaderEl = document.getElementById("loader-camiones");
  const errorEl = document.getElementById("error-camiones");

  listaEl.innerHTML = "";
  ocultar(errorEl);
  mostrar(loaderEl);
  habilitarBtn("btn-continuar-camion", false);
  habilitarBtn("btn-volver-tarar", false);
  estado.camionSeleccionado = null;

  try {
    const camiones = await apiGet("/trucks");
    ocultar(loaderEl);

    if (camiones.length === 0) {
      listaEl.innerHTML = '<p style="color:var(--c-texto-dim);padding:1rem;text-align:center">No hay camiones registrados.</p>';
      return;
    }

    camiones.forEach((c) => {
      const tarjeta = document.createElement("div");
      tarjeta.className = "tarjeta-camion";
      tarjeta.dataset.id = c.id;
      tarjeta.innerHTML = `
        <div>
          <div class="tarjeta-matricula">${c.matricula}</div>
          <div class="tarjeta-tara">Tara: ${c.tara.toLocaleString("es-ES")} kg</div>
        </div>
        <div class="tarjeta-check" aria-label="Seleccionado">✓</div>
      `;
      tarjeta.addEventListener("click", () => seleccionarCamion(c, tarjeta));
      listaEl.appendChild(tarjeta);
    });
  } catch (err) {
    ocultar(loaderEl);
    errorEl.textContent = "No se pudo cargar la lista de camiones. " + err.message;
    mostrar(errorEl);
  }
}

function seleccionarCamion(camion, tarjetaEl) {
  // Desmarcar todas
  document.querySelectorAll(".tarjeta-camion").forEach((t) => {
    t.classList.remove("seleccionado");
  });
  // Marcar la seleccionada
  tarjetaEl.classList.add("seleccionado");
  estado.camionSeleccionado = camion;

  habilitarBtn("btn-continuar-camion", true);
  habilitarBtn("btn-volver-tarar", true);
}

document.getElementById("btn-continuar-camion").addEventListener("click", () => {
  if (!estado.camionSeleccionado) return;
  estado.basculaEsTara = false;
  // Intentar leer báscula para peso bruto
  iniciarPantallaBascula("peso");
});

document.getElementById("btn-volver-tarar").addEventListener("click", () => {
  if (!estado.camionSeleccionado) return;
  estado.basculaEsTara = true;
  // Ir a báscula para recalcular tara
  iniciarPantallaBascula("tara");
});

document.getElementById("btn-nuevo-camion").addEventListener("click", () => {
  document.getElementById("input-matricula").value = "";
  ocultarError("error-matricula");
  mostrarPantalla("pantalla-nuevo-camion");
});

// Botón "Volver" de pantalla selección
document.querySelector('[data-volver="pantalla-inicio"]').addEventListener("click", () => {
  mostrarPantalla("pantalla-inicio");
});

// ══════════════════════════════════════════════════════════
// PANTALLA 3 — NUEVO CAMIÓN
// ══════════════════════════════════════════════════════════

document.getElementById("btn-tara-bascula").addEventListener("click", () => {
  const matricula = document.getElementById("input-matricula").value.trim().toUpperCase();
  if (!validarMatricula(matricula)) return;

  estado.basculaMatriculaNueva = matricula;
  estado.basculaEsTara = true;
  iniciarPantallaBascula("tara");
});

document.getElementById("btn-tara-manual").addEventListener("click", () => {
  const matricula = document.getElementById("input-matricula").value.trim().toUpperCase();
  if (!validarMatricula(matricula)) return;

  estado.basculaMatriculaNueva = matricula;
  estado.basculaEsTara = true;

  // Configurar pantalla tara manual para "nuevo camión"
  document.getElementById("btn-volver-tara").dataset.volver = "pantalla-nuevo-camion";
  document.getElementById("input-tara").value = "";
  ocultarError("error-tara");
  mostrarPantalla("pantalla-tara-manual");
});

// Botón volver de nuevo camión
document.querySelector('#pantalla-nuevo-camion .btn-volver').addEventListener("click", () => {
  mostrarPantalla("pantalla-camion");
});

function validarMatricula(matricula) {
  if (!matricula) {
    mostrarError("error-matricula", "La matrícula es obligatoria.");
    return false;
  }
  ocultarError("error-matricula");
  return true;
}

// ══════════════════════════════════════════════════════════
// PANTALLA 4 — TARA MANUAL
// ══════════════════════════════════════════════════════════

document.getElementById("btn-confirmar-tara").addEventListener("click", async () => {
  const inputTara = document.getElementById("input-tara");
  const tara = parseFloat(inputTara.value);

  if (!tara || tara <= 0) {
    mostrarError("error-tara", "La tara debe ser un número mayor que 0.");
    return;
  }
  ocultarError("error-tara");

  if (estado.basculaMatriculaNueva) {
    // Crear camión nuevo con tara manual
    await crearCamionYContinuar(estado.basculaMatriculaNueva, tara);
  } else if (estado.camionSeleccionado && estado.basculaEsTara) {
    // Actualizar tara de camión existente
    await actualizarTaraYContinuar(estado.camionSeleccionado.id, tara);
  }
});

document.getElementById("btn-volver-tara").addEventListener("click", () => {
  const destino = document.getElementById("btn-volver-tara").dataset.volver || "pantalla-nuevo-camion";
  mostrarPantalla(destino);
});

async function crearCamionYContinuar(matricula, tara) {
  try {
    const camion = await apiPost("/trucks", { matricula, tara });
    estado.camionSeleccionado = camion;
    estado.basculaMatriculaNueva = null;
    estado.basculaEsTara = false;
    // Continuar al pesaje
    iniciarPantallaBascula("peso");
  } catch (err) {
    mostrarError("error-tara", err.message);
  }
}

async function actualizarTaraYContinuar(truckId, tara) {
  try {
    const camion = await apiPut(`/trucks/${truckId}/tare`, { tara });
    estado.camionSeleccionado = camion;
    estado.basculaEsTara = false;
    // Continuar al pesaje
    iniciarPantallaBascula("peso");
  } catch (err) {
    mostrarError("error-tara", err.message);
  }
}

// ══════════════════════════════════════════════════════════
// PANTALLA 5 — BÁSCULA (REUTILIZABLE)
// ══════════════════════════════════════════════════════════

/**
 * Inicializa y muestra la pantalla de báscula.
 * @param {"tara"|"peso"} contexto
 */
function iniciarPantallaBascula(contexto) {
  estado.basculaContexto = contexto;

  // Ajustar título y paso según contexto
  const esTara = contexto === "tara";
  setText("bascula-titulo", esTara ? "Lectura de tara" : "Lectura de peso");
  setText("bascula-paso", esTara ? "Tara" : "2 / 3");
  setText(
    "bascula-instruccion",
    esTara
      ? "Asegúrese de que el camión está vacío y completamente detenido."
      : "Asegúrese de que el camión está cargado y completamente detenido."
  );

  // Configurar botón volver báscula
  const btnVolver = document.getElementById("btn-volver-bascula");
  if (esTara && estado.basculaMatriculaNueva) {
    btnVolver.dataset.volver = "pantalla-nuevo-camion";
  } else if (esTara) {
    btnVolver.dataset.volver = "pantalla-camion";
  } else {
    btnVolver.dataset.volver = "pantalla-camion";
  }

  // Reset visual
  resetearPantallaBascula();
  mostrarPantalla("pantalla-bascula");

  // Lanzar lectura automática
  leerBascula();
}

function resetearPantallaBascula() {
  setText("bascula-estado-texto", "Conectando con la báscula…");
  ocultar("bascula-peso-display");
  mostrar("bascula-loader");
  ocultar("bascula-error-detalle");
  ocultar("btn-reintentar-bascula");
  ocultar("btn-peso-manual-switch");
  ocultar("btn-volver-desde-error");
  mostrar("btn-confirmar-bascula");
  habilitarBtn("btn-confirmar-bascula", false);
  setText("bascula-peso-valor", "—");
}

async function leerBascula() {
  resetearPantallaBascula();

  try {
    const resultado = await apiPost("/weights/read", {
      contexto: estado.basculaContexto,
    });

    ocultar("bascula-loader");

    if (resultado.ok && !resultado.error) {
      // Lectura correcta
      setText("bascula-estado-texto", "Peso detectado correctamente");
      setText("bascula-peso-valor", resultado.peso.toLocaleString("es-ES"));
      mostrar("bascula-peso-display");
      habilitarBtn("btn-confirmar-bascula", true);

      // Si es peso bruto, mostrar opción manual también
      if (estado.basculaContexto === "peso") {
        mostrar("btn-peso-manual-switch");
      }

      // Guardar peso para confirmación
      estado.pesoBrutoConfirmado = resultado.peso;
    } else {
      // Error de báscula
      manejarErrorBascula(resultado.mensaje || "Error desconocido en la báscula.");
    }
  } catch (err) {
    ocultar("bascula-loader");
    manejarErrorBascula("No se pudo conectar con la báscula: " + err.message);
  }
}

function manejarErrorBascula(mensaje) {
  setText("bascula-estado-texto", "Error en la báscula");
  setHTML("bascula-error-detalle", `⚠ ${mensaje}`);
  mostrar("bascula-error-detalle");
  ocultar("btn-confirmar-bascula");
 
  // Mostrar opciones de reintento y volver
  mostrar("btn-reintentar-bascula");
  mostrar("btn-volver-desde-error");
 
  // Si el error fue al leer el peso bruto, dar también la opción de
  // introducirlo manualmente, que es un flujo común.
  if (estado.basculaContexto === "peso") {
    mostrar("btn-peso-manual-switch");
    setText("bascula-estado-texto", "Error en la báscula. Puede reintentar o introducir el peso manualmente.");
  }
}
 
// Confirmar peso leído por báscula
document.getElementById("btn-confirmar-bascula").addEventListener("click", async () => {
  const peso = estado.pesoBrutoConfirmado;
  if (!peso) return;

  if (estado.basculaContexto === "tara") {
    // Confirmar tara
    if (estado.basculaMatriculaNueva) {
      await crearCamionYContinuar(estado.basculaMatriculaNueva, peso);
    } else if (estado.camionSeleccionado) {
      await actualizarTaraYContinuar(estado.camionSeleccionado.id, peso);
    }
  } else {
    // Confirmar peso bruto → registrar pesada
    await registrarPesada(peso, "bascula");
  }
});

// Reintentar lectura de báscula
document.getElementById("btn-reintentar-bascula").addEventListener("click", () => {
  leerBascula();
});

// Cambiar a peso manual desde báscula
document.getElementById("btn-peso-manual-switch").addEventListener("click", () => {
  irAPesoManual();
});

// Volver desde error de báscula
document.getElementById("btn-volver-desde-error").addEventListener("click", () => {
  const destino = document.getElementById("btn-volver-bascula").dataset.volver || "pantalla-camion";
  mostrarPantalla(destino);
});

// Volver desde báscula (botón nav)
document.getElementById("btn-volver-bascula").addEventListener("click", () => {
  const destino = document.getElementById("btn-volver-bascula").dataset.volver || "pantalla-camion";
  mostrarPantalla(destino);
});

// ══════════════════════════════════════════════════════════
// PANTALLA 6 — PESO MANUAL (peso bruto)
// ══════════════════════════════════════════════════════════

function irAPesoManual() {
  const tara = estado.camionSeleccionado?.tara ?? 0;
  const inputPeso = document.getElementById("input-peso-manual");
  inputPeso.value = "";
  inputPeso.min = tara + 1;

  // Mostrar referencia de tara
  setText(
    "info-tara-referencia",
    `Tara del camión: ${tara.toLocaleString("es-ES")} kg · El peso debe ser mayor.`
  );
  ocultarError("error-peso-manual");
  mostrarPantalla("pantalla-peso-manual");
}

document.getElementById("btn-confirmar-peso-manual").addEventListener("click", async () => {
  const inputPeso = document.getElementById("input-peso-manual");
  const peso = parseFloat(inputPeso.value);
  const tara = estado.camionSeleccionado?.tara ?? 0;

  if (!peso || peso <= 0) {
    mostrarError("error-peso-manual", "Introduzca un peso válido mayor que 0.");
    return;
  }

  if (peso <= tara) {
    mostrarError(
      "error-peso-manual",
      `El peso bruto (${peso.toLocaleString("es-ES")} kg) debe ser mayor que la tara (${tara.toLocaleString("es-ES")} kg).`
    );
    return;
  }

  ocultarError("error-peso-manual");
  await registrarPesada(peso, "manual");
});

document.getElementById("btn-volver-peso-manual").addEventListener("click", () => {
  // Volver a báscula (por si quieren reintentar)
  mostrarPantalla("pantalla-bascula");
});

// ══════════════════════════════════════════════════════════
// REGISTRAR PESADA — Lógica compartida
// ══════════════════════════════════════════════════════════

async function registrarPesada(pesoBruto, tipoEntrada) {
  const camion = estado.camionSeleccionado;
  if (!camion) return;

  try {
    let pesada;

    if (estado.basculaEsRepeticion) {
      // Repetir: actualizar pesada anterior (reutilizamos el endpoint manual)
      pesada = await apiPost("/weights/manual", {
        truck_id:    camion.id,
        peso_bruto:  pesoBruto,
        tara:        camion.tara,
        tipo_entrada: tipoEntrada + "_repeticion",
      });
    } else {
      pesada = await apiPost("/weights/manual", {
        truck_id:    camion.id,
        peso_bruto:  pesoBruto,
        tara:        camion.tara,
        tipo_entrada: tipoEntrada,
      });
    }

    mostrarConfirmacion(pesada);
  } catch (err) {
    // Mostrar error en la pantalla actual
    const pantalla = document.querySelector(".pantalla.activa");
    let errorEl = pantalla?.querySelector(".bloque-error");
    if (!errorEl) {
      errorEl = document.getElementById("bascula-error-detalle");
    }
    if (errorEl) {
      errorEl.textContent = "Error al registrar la pesada: " + err.message;
      mostrar(errorEl);
    }
  }
}

// ══════════════════════════════════════════════════════════
// PANTALLA 7 — CONFIRMACIÓN FINAL
// ══════════════════════════════════════════════════════════

function mostrarConfirmacion(pesada) {
  const resumen = document.getElementById("resumen-pesada");
  resumen.innerHTML = `
    <div class="resumen-fila">
      <span class="resumen-etiqueta">Matrícula</span>
      <span class="resumen-valor">${pesada.matricula}</span>
    </div>
    <div class="resumen-fila">
      <span class="resumen-etiqueta">Peso bruto</span>
      <span class="resumen-valor">${pesada.peso_bruto.toLocaleString("es-ES")} kg</span>
    </div>
    <div class="resumen-fila">
      <span class="resumen-etiqueta">Tara</span>
      <span class="resumen-valor">${pesada.tara.toLocaleString("es-ES")} kg</span>
    </div>
    <div class="resumen-fila">
      <span class="resumen-etiqueta">Peso neto</span>
      <span class="resumen-valor neto">${pesada.peso_neto.toLocaleString("es-ES")} kg</span>
    </div>
    <div class="resumen-fila">
      <span class="resumen-etiqueta">Registro</span>
      <span class="resumen-valor" style="font-size:0.9rem">${formatearFecha(pesada.timestamp)}</span>
    </div>
  `;

  mostrarPantalla("pantalla-confirmacion");
}

document.getElementById("btn-finalizar-pesada").addEventListener("click", () => {
  // Resetear estado y volver al inicio
  estado.camionSeleccionado = null;
  estado.basculaEsRepeticion = false;
  estado.basculaEsTara = false;
  estado.pesoBrutoConfirmado = null;
  estado.basculaMatriculaNueva = null;
  mostrarPantalla("pantalla-inicio");
});

// ── Utilidad de fecha ────────────────────────────────────

function formatearFecha(isoString) {
  if (!isoString) return "—";
  try {
    const d = new Date(isoString);
    return d.toLocaleString("es-ES", {
      day:    "2-digit",
      month:  "2-digit",
      year:   "numeric",
      hour:   "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return isoString;
  }
}

// ── Botones "Volver" genéricos (data-volver) ─────────────

document.querySelectorAll("[data-volver]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const destino = btn.dataset.volver;
    if (destino) mostrarPantalla(destino);
  });
});
