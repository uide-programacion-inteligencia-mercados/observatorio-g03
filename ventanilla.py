# ─────────────────────────────────────────────────────────────
#  LA VENTANILLA · cliente resiliente de 2 APIs (requests + tenacity)
#  API 1: Banco Mundial (lo que pasó)   ·   API 2: FMI (lo que se proyecta)
#  Observatorio 0 · Clase 4 · UIDE · Juan Carlos Correa
#  Pregunta del cliente: ¿hay más o menos crédito en la economía para comprar vivienda,
#  y cómo viene la economía para el año del lanzamiento?
# ─────────────────────────────────────────────────────────────
import sys, os, json, datetime, time, requests, pandas as pd
from zoneinfo import ZoneInfo
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

BM  = os.environ.get("BM_BASE",  "https://api.worldbank.org/v2")
FMI = os.environ.get("FMI_BASE", "https://www.imf.org/external/datamapper/api/v1")
PREGUNTAS_BM  = {"FS.AST.PRVT.GD.ZS": "Crédito al sector privado (% del PIB)", "FP.CPI.TOTL.ZG": "Inflación anual (%)"}
PREGUNTAS_FMI = {"NGDP_RPCH": "Crecimiento del PIB proyectado (%)"}
ARCHIVO = "data/indicadores.csv"

if "--grupo" in sys.argv:                          # el mismo robot, con las preguntas de su sector
    PREGUNTAS_BM, PREGUNTAS_FMI = json.load(open("indicadores_grupo.json")), {}
    ARCHIVO = "data/indicadores_grupo.csv"
if "--codigo-malo" in sys.argv:                    # una letra mal escrita en la pregunta
    PREGUNTAS_BM, PREGUNTAS_FMI = {"FS.AST.PRVT.GD.ZX": "Crédito al sector privado (% del PIB)"}, {}
SIMULAR_CAIDA = "--simular-caida" in sys.argv      # las 3 de la mañana, a propósito
if SIMULAR_CAIDA:
    BM = FMI = "http://10.255.255.1"               # una dirección que nunca contesta
ESPERA_MAXIMA = 2 if SIMULAR_CAIDA else 20         # REGLA 1 · no espera para siempre (segundos)
AHORA = datetime.datetime.now(ZoneInfo("America/Guayaquil")).strftime("%Y-%m-%d %H:%M")
os.makedirs("data", exist_ok=True)

def bitacora(mensaje):                             # REGLA 5 · deja constancia
    with open("data/bitacora.log", "a", encoding="utf-8") as f:
        f.write(f"{AHORA} | ventanilla | {mensaje}\n")

SIGNIFICADO = {200: "todo bien", 401: "falta la llave (token)", 403: "prohibido", 404: "no existe",
               429: "demasiadas preguntas, vuelva luego", 500: "la ventanilla está dañada"}

class VuelvaLuego(Exception):                      # 429 o 5xx: vale la pena reintentar
    pass

def avisar(estado):
    print(f"    ↻ reintento {estado.attempt_number} en {estado.next_action.sleep:.0f} s…")

@retry(stop=stop_after_attempt(3),                               # REGLA 2 · insiste…
       wait=wait_exponential(multiplier=1, min=1, max=8),        # …con educación: 1 s, 2 s, 4 s (backoff exponencial)
       retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout, VuelvaLuego)),
       before_sleep=avisar, reraise=True)
def pedir(url):
    r = requests.get(url, timeout=ESPERA_MAXIMA,
                     headers={"User-Agent": "ObservatorioUIDE/1.0 (proyecto academico)"})
    print(f"    ← código {r.status_code}: {SIGNIFICADO.get(r.status_code, 'respuesta rara')}")
    if r.status_code == 429 or r.status_code >= 500:
        raise VuelvaLuego(r.status_code)
    r.raise_for_status()
    return r.json()

def banco_mundial(codigo):                         # con PAGINACIÓN: la respuesta llega por páginas
    filas, pagina, total_paginas = [], 1, 1
    while pagina <= total_paginas:
        datos = pedir(f"{BM}/country/ECU/indicator/{codigo}?format=json&date=2000:2025&per_page=10&page={pagina}")
        if not (isinstance(datos, list) and len(datos) == 2 and datos[1]):   # REGLA 3 · desconfía del 200
            print("    ⚠ Dijo 200… pero no trajo datos:", str(datos)[:100])
            return []
        total_paginas = datos[0]["pages"]
        print(f"    📄 página {pagina} de {total_paginas}")
        filas += [{"anio": int(d["date"]), "valor": d["value"]} for d in datos[1] if d["value"] is not None]
        pagina += 1
        time.sleep(1)                              # cortesía: una pregunta por segundo (rate limit)
    return filas

def fmi(codigo):
    datos = pedir(f"{FMI}/{codigo}/ECU")
    serie = datos.get("values", {}).get(codigo, {}).get("ECU", {})
    if not serie:                                  # REGLA 3 · desconfía del 200
        print("    ⚠ Dijo 200… pero no trajo datos de Ecuador")
    return [{"anio": int(a), "valor": v} for a, v in serie.items() if 2015 <= int(a) <= 2030]

filas, fallos_seguidos = [], 0
consultas = [("Banco Mundial", banco_mundial, c, n) for c, n in PREGUNTAS_BM.items()] + \
            [("FMI", fmi, c, n) for c, n in PREGUNTAS_FMI.items()]
for fuente, funcion, codigo, nombre in consultas:
    if fallos_seguidos >= 2:                       # INTERRUPTOR (circuit breaker): dejamos de insistir
        print(f"⚡ Interruptor abierto: 2 fallos seguidos. No se pregunta «{nombre}» hasta la próxima ejecución.")
        continue
    print(f"• {fuente}: «{nombre}» de Ecuador")
    try:
        resultado = funcion(codigo)
        fallos_seguidos = 0 if resultado else fallos_seguidos
        filas += [dict(r, indicador=nombre, codigo=codigo, fuente=fuente, fecha_captura=AHORA) for r in resultado]
    except Exception as e:
        fallos_seguidos += 1
        print(f"  ✖ La ventanilla no contestó tras 3 intentos ({type(e).__name__})")

RESPALDO_BM = os.environ.get("BM_RESPALDO", "https://raw.githubusercontent.com/uide-programacion-inteligencia-mercados/recursos-curso/main/respaldo_bm_grupos.csv")
if not filas and "--grupo" in sys.argv and not SIMULAR_CAIDA and not os.path.exists(ARCHIVO):   # PLAN B
    print("\n• Plan B: traigo el RESPALDO del profesor (Banco Mundial, capturado el 30-sep-2026)")
    try:
        r = pd.read_csv(RESPALDO_BM, sep="|")
        r = r[r["codigo"].isin(list(PREGUNTAS_BM))]
        filas = [{"anio": int(x.anio), "valor": x.valor, "indicador": PREGUNTAS_BM[x.codigo], "codigo": x.codigo,
                  "fuente": "Banco Mundial (respaldo del profesor, 30-sep-2026)", "fecha_captura": AHORA} for x in r.itertuples()]
        print(f"⚠ La ventanilla no contestó: uso el RESPALDO ({len(filas)} datos). En el PDF anótenlo.")
    except Exception as e:
        print(f"  ✖ Tampoco llegó el respaldo ({type(e).__name__})")

tabla = pd.DataFrame(filas)
if len(tabla) > 0:
    tabla.sort_values(["codigo", "anio"]).to_csv(ARCHIVO, index=False)
    bitacora(f"OK · {len(tabla)} filas de {tabla['fuente'].nunique()} API(s)")
    print(f"\n✔ LISTO: {len(tabla)} datos de {tabla['fuente'].nunique()} API(s) guardados en {ARCHIVO}  [{AHORA}]")
elif os.path.exists(ARCHIVO):                      # REGLA 4 · nunca pisa el dato bueno
    bitacora("FALLÓ · sin respuesta · se conserva el archivo anterior")
    print("\n⚠ Las ventanillas fallaron. NO se borró nada: se conserva el dato anterior [RESPALDO].")
else:
    bitacora("FALLÓ · sin respuesta · sin respaldo")
    print("\n✖ Las ventanillas fallaron y no hay dato anterior. Se intentará en la próxima ejecución.")
