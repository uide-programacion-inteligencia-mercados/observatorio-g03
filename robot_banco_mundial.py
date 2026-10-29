# ============================================================================
# ARCHIVO: robot_banco_mundial.py   (el robot del equipo g03)   · VERSIÓN 3 · SEMANA 8
# QUÉ HACE:  Trae los dos indicadores del equipo desde el Banco Mundial, los revisa
#            con las reglas de calidad del equipo, SOLO si pasan los guarda, y después
#            ESCRIBE SU PROPIO INFORME EN PDF: reports/informe_g03.pdf
# NOVEDADES DE LA SEMANA 8 («Reporte PDF»):
#   1. El informe se arma con un MOLDE (plantillas/informe.html.j2) y los textos del
#      equipo (config_informe.json). Jinja2 rellena los huecos y WeasyPrint lo imprime.
#   2. El gráfico se dibuja con matplotlib y se incrusta dentro del PDF.
#   3. El PORTERO DEL PDF: un PDF vacío, roto o larguísimo se rechaza (ErrorDeInforme).
#   4. Si la fuente falla, el informe anterior NO se pisa: sigue siendo el último bueno.
#   5. Escritura atómica del PDF (borrador y cambio en un solo movimiento).
# (De la semana 7 se conservan: reintentos con espera creciente, control de calidad,
#  bitácora, salud, simulacro y escritura atómica de los datos.)
# ESTO PUEDEN CAMBIARLO: la sección «REGLAS DEL EQUIPO», el molde y config_informe.json.
# ============================================================================
import base64
import io
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

EQUIPO = "g03"
INDICADORES = {"NY.GDP.MKTP.KD.ZG": "Crecimiento del PIB (%)", "NV.SRV.TOTL.KD.ZG": "Crecimiento de los servicios (%)"}

# --- REGLAS DEL EQUIPO (decididas en la semana 7) ---
RANGOS = {"NY.GDP.MKTP.KD.ZG": (-15.0, 15.0), "NV.SRV.TOTL.KD.ZG": (-15.0, 15.0)}              # valor mínimo y máximo CREÍBLE de cada indicador
MIN_FILAS = 10                  # menos filas que esto = llegó incompleto
MAX_ANIOS_SIN_DATO = 4         # si el último año tiene más antigüedad, el dato está viejo
REINTENTOS = 3                # cuántas veces más intenta si la fuente no contesta
ESPERA_INICIAL = 2                # segundos de la primera espera; luego se duplica

# --- REGLAS DEL INFORME (nuevas en la semana 8) ---
PDF_MIN_BYTES = 5000             # menos que esto = PDF vacío o roto
PDF_MAX_PAGINAS = 3              # más páginas que esto = algo se desbordó

DESDE, HASTA = 2015, 2025
SIMULAR_FALLA = os.environ.get("SIMULAR_FALLA", "false").lower() == "true"
CORRIDA = os.environ.get("GITHUB_RUN_ID") or datetime.now(timezone.utc).strftime("local-%Y%m%dT%H%M%S")
EN_GITHUB = os.environ.get("GITHUB_ACTIONS") == "true"

DATA, LOGS, REPORTES, PLANTILLAS = Path("data"), Path("logs"), Path("reports"), Path("plantillas")
ARCHIVO_DATOS = DATA / f"indicadores_{EQUIPO}.csv"
BITACORA = LOGS / f"bitacora_{EQUIPO}.jsonl"
SALUD = LOGS / f"salud_{EQUIPO}.csv"
ARCHIVO_INFORME = REPORTES / f"informe_{EQUIPO}.pdf"
TEXTOS = Path("config_informe.json")
REINTENTOS_USADOS = []


class ErrorDeDatos(Exception):
    """Los datos llegaron, pero no son creíbles. Reintentar no lo arregla."""


class ErrorDeInforme(Exception):
    """El PDF no salió bien. Reintentar con los mismos datos daría lo mismo."""


def anotar(nivel, evento, **detalles):
    # Bitácora: una línea JSON por evento, siempre con los mismos campos.
    LOGS.mkdir(exist_ok=True)
    fila = {"momento_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "corrida": CORRIDA,
            "equipo": EQUIPO, "nivel": nivel, "evento": evento, **detalles}
    with open(BITACORA, "a", encoding="utf-8") as f:
        f.write(json.dumps(fila, ensure_ascii=False, default=str) + "\n")
    print(f"[{nivel:<7}] {evento}" + (" · " + ", ".join(f"{k}={v}" for k, v in detalles.items()) if detalles else ""))
    if EN_GITHUB and nivel in ("WARNING", "ERROR"):
        print(f"::{'warning' if nivel == 'WARNING' else 'error'} title=Robot {EQUIPO}::{evento}")


def traer(codigo):
    # Pide UN indicador. Si la fuente no contesta, espera cada vez más y reintenta.
    url = (f"https://api.worldbank.org/v2/country/ECU/indicator/{codigo}"
           f"?format=json&date={DESDE}:{HASTA}&per_page=100")
    for intento in range(1, REINTENTOS + 2):
        try:
            if SIMULAR_FALLA:
                raise ConnectionError("SIMULACRO: el Banco Mundial no contesta (falla provocada a propósito)")
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            datos = r.json()
            if len(datos) < 2 or not datos[1]:
                raise ErrorDeDatos(f"{codigo}: el Banco Mundial respondió, pero sin datos")
            return datos[1]
        except ErrorDeDatos:
            raise                                    # datos malos: no se reintenta
        except Exception as e:
            if intento > REINTENTOS:
                raise ConnectionError(f"{codigo}: no contestó después de {intento} intentos ({e})")
            pausa = ESPERA_INICIAL * 2 ** (intento - 1)
            REINTENTOS_USADOS.append(codigo)
            anotar("WARNING", f"{codigo}: intento {intento} falló; espero {pausa} s y reintento", error=str(e)[:150])
            time.sleep(pausa)


def revisar(tabla):
    # El control de calidad del equipo. Devuelve la lista de problemas (vacía = todo bien).
    problemas = []
    if tabla.empty:
        return ["no llegó ninguna fila"]
    if len(tabla) < MIN_FILAS:
        problemas.append(f"solo {len(tabla)} filas (mínimo {MIN_FILAS})")
    for codigo, nombre in INDICADORES.items():
        parte = tabla[tabla["codigo"] == codigo]
        if parte.empty:
            problemas.append(f"falta el indicador {nombre}")
            continue
        lo, hi = RANGOS[codigo]
        raros = parte[(parte["valor"] < lo) | (parte["valor"] > hi)]
        if len(raros):
            problemas.append(f"{nombre}: {len(raros)} valor(es) fuera de lo creíble ({lo} a {hi})")
        ultimo = int(parte["anio"].max())
        if ultimo < datetime.now(timezone.utc).year - MAX_ANIOS_SIN_DATO:
            problemas.append(f"{nombre}: el último dato es de {ultimo} (dato viejo)")
    return problemas


def guardar_atomico(tabla):
    # Escribe un borrador y lo cambia por el archivo de verdad en un solo movimiento.
    DATA.mkdir(exist_ok=True)
    borrador = ARCHIVO_DATOS.with_suffix(".tmp")
    tabla.to_csv(borrador, index=False)
    borrador.replace(ARCHIVO_DATOS)


# ===================== SEMANA 8 · EL INFORME EN PDF =====================
def _numero(v):
    # Convierte 3.14159 en «3,14» (coma decimal, como en Ecuador).
    return f"{v:,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")


def _grafico_en_texto(tabla):
    # Dibuja una línea por indicador y devuelve la imagen como texto (base64) para incrustarla en el HTML.
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ejes = plt.subplots(len(INDICADORES), 1, figsize=(8, 2.3 * len(INDICADORES)), sharex=True)
    ejes = [ejes] if len(INDICADORES) == 1 else list(ejes)
    for ax, (codigo, nombre), color in zip(ejes, INDICADORES.items(), ("#002C71", "#910048")):
        p = tabla[tabla["codigo"] == codigo].sort_values("anio")
        ax.plot(p["anio"], p["valor"], marker="o", color=color, linewidth=2)
        ax.axhline(0, color="#BDBDBD", linewidth=.8)
        ax.set_title(nombre, fontsize=9, loc="left", color=color)
        ax.grid(axis="y", color="#E7E6E6")
        for lado in ("top", "right"):
            ax.spines[lado].set_visible(False)
    ejes[-1].set_xlabel("Año")
    fig.tight_layout()
    memoria = io.BytesIO()
    fig.savefig(memoria, format="png", dpi=130)
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(memoria.getvalue()).decode("ascii")


def _salud_reciente():
    # El semáforo de la última corrida registrada ANTES de esta (la de hoy se anota al final).
    if not SALUD.exists():
        return "SIN DATOS", "gris", "primera corrida"
    s = pd.read_csv(SALUD)
    if s.empty:
        return "SIN DATOS", "gris", "primera corrida"
    u = s.iloc[-1]
    return str(u["estado"]).upper(), str(u["estado"]), str(u["motivo"])[:70]


def construir_contexto(tabla):
    """PASO 1 del informe: arma el diccionario con TODOS los valores que el molde necesita."""
    textos = json.loads(TEXTOS.read_text(encoding="utf-8"))
    faltan = [k for k in ("titulo", "para_quien", "titular", "lectura_negocio", "recomendacion") if not str(textos.get(k, "")).strip()]
    if faltan:
        raise ErrorDeInforme(f"config_informe.json: faltan los textos {', '.join(faltan)}")
    kpis, anios_ultimos = [], []
    for codigo, nombre in INDICADORES.items():
        p = tabla[tabla["codigo"] == codigo].sort_values("anio")
        ult = p.iloc[-1]
        anterior = p.iloc[-2]["valor"] if len(p) > 1 else None
        cambio = "sin año anterior" if anterior is None else f"{ult['valor'] - anterior:+.2f} puntos vs año anterior".replace(".", ",")
        kpis.append({"nombre": nombre, "ultimo": _numero(ult["valor"]), "anio": int(ult["anio"]), "cambio": cambio})
        anios_ultimos.append(int(ult["anio"]))
    anios = sorted(tabla["anio"].unique())[-6:][::-1]
    cuerpo = []
    for a in anios:
        fila = {"anio": int(a), "valores": []}
        for codigo in INDICADORES:
            v = tabla[(tabla["codigo"] == codigo) & (tabla["anio"] == a)]["valor"]
            fila["valores"].append("sin dato" if v.empty else _numero(v.iloc[0]))
        cuerpo.append(fila)
    antiguedad = datetime.now(timezone.utc).year - max(anios_ultimos)
    estado, color, motivo = _salud_reciente()
    return {"titulo": textos["titulo"], "para_quien": textos["para_quien"], "titular": textos["titular"],
            "lectura_negocio": textos["lectura_negocio"], "recomendacion": textos["recomendacion"],
            "equipo": EQUIPO.upper(), "fecha": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "pie": f"Observatorio {EQUIPO.upper()} · corrida {CORRIDA}", "corrida": CORRIDA,
            "indicadores": kpis, "tabla": cuerpo, "grafico_uri": _grafico_en_texto(tabla),
            "es_viejo": antiguedad > MAX_ANIOS_SIN_DATO, "antiguedad": antiguedad,
            "salud_estado": estado, "salud_color": color, "salud_motivo": motivo, "desde": DESDE, "hasta": HASTA}


def renderizar_html(contexto):
    """PASO 2 del informe: Jinja2 rellena los huecos del molde. autoescape evita que un texto raro rompa el HTML."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    entorno = Environment(loader=FileSystemLoader(str(PLANTILLAS)), autoescape=select_autoescape(["html", "j2"]))
    return entorno.get_template("informe.html.j2").render(**contexto)


def imprimir_pdf(html):
    """PASO 3 del informe: WeasyPrint convierte el HTML en PDF. Devuelve cuántas páginas salieron."""
    from weasyprint import HTML
    documento = HTML(string=html, base_url=str(Path.cwd())).render()
    REPORTES.mkdir(exist_ok=True)
    borrador = ARCHIVO_INFORME.with_suffix(".tmp")
    documento.write_pdf(str(borrador))
    paginas = len(documento.pages)
    validar_pdf(borrador, paginas)                       # el portero revisa ANTES de reemplazar el informe bueno
    borrador.replace(ARCHIVO_INFORME)
    return paginas


def validar_pdf(archivo, paginas):
    """El portero del PDF: lo que no es un PDF sano NO reemplaza al informe anterior."""
    p = Path(archivo)
    if not p.exists() or p.stat().st_size < PDF_MIN_BYTES:
        raise ErrorDeInforme(f"el PDF salió vacío o roto (menos de {PDF_MIN_BYTES} bytes)")
    if p.read_bytes()[:5] != b"%PDF-":
        raise ErrorDeInforme("el archivo generado no es un PDF")
    if not 1 <= paginas <= PDF_MAX_PAGINAS:
        raise ErrorDeInforme(f"el PDF tiene {paginas} páginas (esperado: 1 a {PDF_MAX_PAGINAS})")


def generar_informe(tabla):
    contexto = construir_contexto(tabla)
    paginas = imprimir_pdf(renderizar_html(contexto))
    anotar("INFO", "informe PDF generado", archivo=str(ARCHIVO_INFORME), paginas=paginas,
           kb=round(ARCHIVO_INFORME.stat().st_size / 1024))
    return paginas


# ===================== SALUD Y RESUMEN =====================
def registrar_salud(estado, motivo, filas, segundos):
    # Una fila por corrida. Si GitHub repite la MISMA corrida, se reemplaza (idempotencia).
    LOGS.mkdir(exist_ok=True)
    fila = {"fecha_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "corrida": CORRIDA,
            "estado": estado, "motivo": motivo, "filas": filas, "segundos": round(segundos, 1)}
    salud = pd.read_csv(SALUD) if SALUD.exists() else pd.DataFrame(columns=list(fila))
    salud = salud[salud["corrida"].astype(str) != str(CORRIDA)]
    pd.concat([salud, pd.DataFrame([fila])], ignore_index=True).to_csv(SALUD, index=False)
    return salud


def resumen_en_github():
    # Escribe el tablero de salud en la pantalla de la corrida de GitHub.
    destino = os.environ.get("GITHUB_STEP_SUMMARY")
    if not destino or not SALUD.exists():
        return
    s = pd.read_csv(SALUD).tail(7).iloc[::-1]
    icono = {"verde": "🟢", "amarillo": "🟡", "rojo": "🔴"}
    filas = "\n".join(f"| {r.fecha_utc[:16].replace('T', ' ')} | {icono.get(r.estado, '')} {r.estado} | {r.motivo} |"
                      for r in s.itertuples())
    with open(destino, "a", encoding="utf-8") as f:
        f.write(f"## Salud del robot {EQUIPO}\n\n| Fecha (UTC) | Estado | Motivo |\n|---|---|---|\n{filas}\n")


def main():
    inicio = time.time()
    anotar("INFO", "inicio de la corrida", simulacro=SIMULAR_FALLA)
    filas_guardadas = 0
    try:
        filas = []
        for codigo, nombre in INDICADORES.items():
            for d in traer(codigo):
                if d.get("value") is not None:
                    filas.append({"anio": int(d["date"]), "codigo": codigo, "indicador": nombre, "valor": d["value"]})
            anotar("INFO", f"{codigo}: recibido")
        tabla = pd.DataFrame(filas, columns=["anio", "codigo", "indicador", "valor"]).sort_values(["codigo", "anio"])
        problemas = revisar(tabla)
        if problemas:
            raise ErrorDeDatos("; ".join(problemas))
        guardar_atomico(tabla)
        filas_guardadas = len(tabla)
        anotar("INFO", "datos aprobados y guardados", filas=filas_guardadas, archivo=str(ARCHIVO_DATOS))
        generar_informe(tabla)                                   # S08 · INFORMAR
        estado, motivo = ("amarillo", "funcionó, pero tuvo que reintentar") if REINTENTOS_USADOS else ("verde", "todo bien")
    except ErrorDeDatos as e:
        estado, motivo = "rojo", f"datos no confiables: {e}"
        anotar("ERROR", motivo)
    except ErrorDeInforme as e:
        estado, motivo = "rojo", f"el informe PDF falló: {e}"
        anotar("ERROR", motivo)
    except Exception as e:
        estado, motivo = "rojo", f"la fuente falló: {e}"
        anotar("ERROR", motivo)
    if estado == "rojo" and ARCHIVO_INFORME.exists():
        anotar("INFO", "plan B: se conservan intactos los datos y el informe de la última corrida buena")
    registrar_salud(estado, motivo, filas_guardadas, time.time() - inicio)
    resumen_en_github()
    print(f"RESULTADO: {estado.upper()} · {motivo}")
    sys.exit(1 if estado == "rojo" else 0)


if __name__ == "__main__":
    main()
