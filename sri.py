# ─────────────────────────────────────────────────────────────
#  GRUPOS 2 y 3 · FUENTE 1: recaudación mensual del SRI
#  Grupo 2 • por PROVINCIA  ·  Grupo 3 • por ACTIVIDAD ECONÓMICA (sección CIIU)
#  Plan A: pedir el dato EN VIVO al portal de datos abiertos (API CKAN) y al SRI.
#  Plan B: si el portal no deja entrar (pasa desde Colab: el portal de Ecuador
#          bloquea a los servidores de fuera del país), se usa el RESPALDO del
#          profesor, sacado del mismo archivo oficial del SRI el 30-sep-2026.
# ─────────────────────────────────────────────────────────────
import os, sys, io, json, datetime, unicodedata, requests, pandas as pd
from zoneinfo import ZoneInfo
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

CKAN = os.environ.get("CKAN_BASE", "https://www.datosabiertos.gob.ec/api/3/action")
RESPALDO = os.environ.get("SRI_RESPALDO", "https://raw.githubusercontent.com/uide-programacion-inteligencia-mercados/recursos-curso/main/respaldo_sri.csv")
SIMULAR_CAIDA = "--simular-caida" in sys.argv
if SIMULAR_CAIDA:
    CKAN = "http://10.255.255.1"
ESPERA = 2 if SIMULAR_CAIDA else 20
NAVEGADOR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"}
GRUPO = json.load(open("grupo.json"))["grupo"]
CORTE = "PROVINCIA" if GRUPO == 2 else "ACTIVIDAD"
ANIO = datetime.date.today().year                        # este año contra el anterior
AHORA = datetime.datetime.now(ZoneInfo("America/Guayaquil")).strftime("%Y-%m-%d %H:%M")
ARCHIVO, MENSUAL = "data/sri_resumen.csv", "data/sri_total_mensual.csv"
os.makedirs("data/crudo", exist_ok=True)
CIIU = {"A": "Agricultura y pesca", "B": "Minas y petróleo", "C": "Manufactura", "D": "Electricidad y gas",
        "E": "Agua y residuos", "F": "Construcción", "G": "Comercio", "H": "Transporte", "I": "Alojamiento y comidas",
        "J": "Información y comunicación", "K": "Finanzas y seguros", "L": "Inmobiliarias", "M": "Actividades profesionales",
        "N": "Servicios administrativos", "O": "Administración pública", "P": "Enseñanza", "Q": "Salud",
        "R": "Artes y recreación", "S": "Otros servicios", "T": "Hogares", "U": "Organismos extraterritoriales"}
SIGNIFICADO = {200: "todo bien", 403: "prohibido: el portal no deja entrar desde aquí", 404: "no existe",
               429: "demasiadas preguntas", 500: "el portal está dañado"}

def bitacora(m):
    open("data/bitacora.log", "a", encoding="utf-8").write(f"{AHORA} | sri | {m}\n")

class SinPermiso(Exception):
    pass

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8),
       retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)), reraise=True)
def preguntar_ckan(anio):
    """Le pregunta a la API del portal: ¿dónde está el CSV de recaudación de ese año?"""
    r = requests.get(f"{CKAN}/package_search", params={"q": f"recaudacion impuestos {anio}", "rows": 30},
                     timeout=ESPERA, headers=NAVEGADOR)
    print(f"  ← el portal respondió {r.status_code}: {SIGNIFICADO.get(r.status_code, 'respuesta rara')}")
    if r.status_code != 200:                             # REGLA 3 · sin 200 no hay JSON: no seguimos a ciegas
        raise SinPermiso(f"código {r.status_code}")
    for p in r.json()["result"]["results"]:
        if p["name"].endswith(str(anio)) and "sri" in (p.get("organization") or {}).get("title", "").lower():
            return next(x["url"] for x in p["resources"] if x["format"].upper() == "CSV")
    return None

def descargar(url, destino):
    if os.path.exists(destino):                          # caché: no se pide dos veces lo mismo
        print(f"  📦 Ya estaba descargado: {destino}"); return
    print(f"  ⬇ Descargando {url.split('/')[-1]} (cerca de 100 MB, 1–2 minutos)…")
    with requests.get(url, stream=True, timeout=60, headers=NAVEGADOR) as r:
        if r.status_code != 200:
            raise SinPermiso(f"descarga con código {r.status_code}")
        with open(destino + ".parcial", "wb") as f:
            for trozo in r.iter_content(1 << 20):
                f.write(trozo)
    os.replace(destino + ".parcial", destino)

def en_vivo():
    """PLAN A. Devuelve una tabla ANIO | MES | CLAVE | VALOR_RECAUDADO."""
    partes = []
    for anio in (ANIO - 1, ANIO):
        print(f"• Año {anio}: buscando el archivo en datosabiertos.gob.ec")
        url = preguntar_ckan(anio)
        if not url:
            raise SinPermiso(f"el portal no tiene el archivo de {anio}")
        destino = f"data/crudo/sri_recaudacion_{anio}.csv"
        descargar(url, destino)
        col = "PROVINCIA" if CORTE == "PROVINCIA" else "CODIGO_OPERA_FAMILIA"
        d = pd.read_csv(destino, sep="|", decimal=",", encoding="latin-1", usecols=["ANIO", "MES", col, "VALOR_RECAUDADO"])
        d["MES"] = d["MES"].astype(str).str[:2].astype(int)
        partes.append(d.rename(columns={col: "CLAVE"}))
    return pd.concat(partes), "SRI · Recaudación mensual (en vivo, vía API CKAN)"

def respaldo():
    """PLAN B. El mismo dato oficial del SRI, ya resumido por el profesor."""
    print("\n• Plan B: traigo el RESPALDO del profesor (archivo oficial del SRI, capturado el 30-sep-2026)")
    r = requests.get(RESPALDO, timeout=30) if RESPALDO.startswith("http") else None
    texto = r.text if r is not None else open(RESPALDO, encoding="utf-8").read()
    if r is not None and r.status_code != 200:
        raise SinPermiso(f"respaldo con código {r.status_code}")
    d = pd.read_csv(io.StringIO(texto), sep="|", dtype={"CLAVE": str})
    d = d[d["CORTE"] == CORTE].drop(columns="CORTE")
    return d, "SRI · Recaudación mensual (respaldo del profesor, 30-sep-2026)"

try:
    try:
        df, fuente = en_vivo()
        de_respaldo = False
    except Exception as e:
        print(f"  ✖ En vivo no se pudo: {e}")
        if SIMULAR_CAIDA:                                # en la prueba del apagón no hay plan B: queremos ver el fallo
            raise
        df, fuente = respaldo()
        de_respaldo = True
    df = df[df["ANIO"].isin([ANIO - 1, ANIO])]
    ultimo_mes = int(df.loc[df["ANIO"] == ANIO, "MES"].max())
    df = df[df["MES"] <= ultimo_mes]                      # comparamos los mismos meses en ambos años
    (df[df["ANIO"] == ANIO].groupby("MES")["VALOR_RECAUDADO"].sum() / 1e6).round(1) \
        .rename("millones_usd").to_csv(MENSUAL)          # para verificar a mano en el paso G8
    t = df.pivot_table(index="CLAVE", columns="ANIO", values="VALOR_RECAUDADO", aggfunc="sum").fillna(0)
    t = t[t.iloc[:, 0] > 0]
    t.columns = [f"recaudado_{c}" for c in t.columns]
    t["variacion_pct"] = ((t.iloc[:, 1] / t.iloc[:, 0] - 1) * 100).round(1)
    if CORTE == "ACTIVIDAD":
        t = t[t.index.isin(list(CIIU))]
        t.index = [f"{i} · {CIIU[i]}" for i in t.index]
    else:
        t = t[t.index != "NO TIENE"]
    t.index.name = "provincia" if GRUPO == 2 else "actividad"
    elegidas = json.load(open("eleccion.json"))          # las 5 que decidió vigilar el grupo
    sin_tilde = lambda x: unicodedata.normalize("NFKD", str(x)).encode("ascii", "ignore").decode().upper().strip()
    t["vigilada"] = [any(sin_tilde(i).startswith(sin_tilde(e)) for e in elegidas) for i in t.index]
    t = t.sort_values("variacion_pct", ascending=False).reset_index()
    t["periodo"] = f"enero–mes {ultimo_mes} · {ANIO} vs {ANIO - 1}"
    t["fecha_captura"], t["fuente"] = AHORA, fuente
    if len(t) < 5 or t["vigilada"].sum() < 5:             # REGLA 3 · desconfía
        raise RuntimeError(f"algo no cuadra: {len(t)} filas y {t['vigilada'].sum()} de 5 vigiladas")
    t.to_csv(ARCHIVO, index=False)
    if de_respaldo:
        bitacora(f"FALLÓ en vivo · se usó el RESPALDO del profesor · {len(t)} filas · meses 1-{ultimo_mes}")
        print(f"\n⚠ En vivo no se pudo, uso el RESPALDO: {len(t)} filas (enero a mes {ultimo_mes}, {ANIO} contra {ANIO - 1}).")
        print("  Es el mismo archivo oficial del SRI. En el PDF anótenlo: fuente = respaldo del profesor.")
    else:
        bitacora(f"OK · {len(t)} filas · meses 1-{ultimo_mes}")
    print(f"\n✔ LISTO: {len(t)} filas en {ARCHIVO}")
except Exception as e:
    print(f"  ✖ Falló: {e}")
    if os.path.exists(ARCHIVO):                           # REGLA 4
        bitacora("FALLÓ · se conserva el resumen anterior")
        print("\n⚠ NO se pisa el resumen anterior [RESPALDO].")
    else:
        bitacora("FALLÓ · sin respaldo")
        print("\n✖ No hay resumen anterior. Avisen al profesor con una captura de esta pantalla.")
