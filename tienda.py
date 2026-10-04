# ─────────────────────────────────────────────────────────────
#  GRUPO 1 · El bolsillo del ecuatoriano · FUENTE 1: la canasta de Tía
#  La canasta la decide el grupo (paso G2): 20 fichas de producto de tia.com.ec.
#  Cumple la evidencia de la semana 3: un robot que MONITOREA precios de un e-commerce ecuatoriano.
# ─────────────────────────────────────────────────────────────
import os, re, sys, time, random, datetime, urllib.robotparser, requests, pandas as pd
from zoneinfo import ZoneInfo
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

TIENDA = os.environ.get("TIA_BASE", "https://www.tia.com.ec")
if "--simular-caida" in sys.argv:
    TIENDA = "http://10.255.255.1"                      # las 3 de la mañana: la tienda no contesta
CANASTA = [tuple(x.split("|", 1)) for x in open("canasta.txt", encoding="utf-8").read().splitlines() if "|" in x]   # la eligió el grupo
AHORA = datetime.datetime.now(ZoneInfo("America/Guayaquil")).strftime("%Y-%m-%d %H:%M")
FOTO, HISTORIA = "data/canasta_tia.csv", "data/historico_canasta_tia.csv"
AGENTE = "ObservatorioUIDE/1.0 (proyecto academico)"
os.makedirs("data", exist_ok=True)

def bitacora(m):                                        # REGLA 5
    open("data/bitacora.log", "a", encoding="utf-8").write(f"{AHORA} | tienda | {m}\n")

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8),        # REGLA 2
       retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)), reraise=True)
def pedir(url):
    return requests.get(url, timeout=2 if "10.255" in url else 20, headers={"User-Agent": AGENTE})  # REGLA 1

# Antes de entrar, leemos el cartel de la tienda (robots.txt)
cartel = urllib.robotparser.RobotFileParser()
try:
    cartel.parse(pedir(TIENDA + "/robots.txt").text.splitlines())
    print("🪧 robots.txt leído: la tienda dice qué se puede y qué no.")
except Exception as e:
    print(f"✖ No se pudo leer el robots.txt ({type(e).__name__}).")

filas, fallos = [], 0
for nombre, ruta in CANASTA:
    url = TIENDA + ruta if ruta.startswith("/") else ruta.replace("https://www.tia.com.ec", TIENDA)
    if cartel.default_entry and not cartel.can_fetch(AGENTE, url):
        print(f"  ⛔ {nombre}: el robots.txt no lo permite. Se salta."); continue
    if fallos >= 3:                                      # INTERRUPTOR
        print("⚡ Interruptor abierto: 3 fallos seguidos. Se detiene hasta la próxima ejecución."); break
    try:
        r = pedir(url)
        precio = re.search(r'product:price:amount" content="([\d.]+)"', r.text)
        if r.status_code == 200 and precio:              # REGLA 3 · desconfía del 200
            filas.append({"producto": nombre, "precio_usd": round(float(precio.group(1)), 2),
                          "url": url, "fecha_captura": AHORA, "fuente": "Tía · ficha de producto"})
            print(f"  ✔ {nombre:<26} USD {float(precio.group(1)):.2f}"); fallos = 0
        else:
            print(f"  ⚠ {nombre}: código {r.status_code}, sin precio en la ficha"); fallos += 1
    except Exception as e:
        print(f"  ✖ {nombre}: no contestó ({type(e).__name__})"); fallos += 1
    time.sleep(random.uniform(1.5, 3))                   # pausa humana

tabla = pd.DataFrame(filas)
if len(tabla) >= max(1, int(0.75 * len(CANASTA))):     # al menos 3 de cada 4 productos para que la canasta valga
    tabla.to_csv(FOTO, index=False)
    tabla.to_csv(HISTORIA, mode="a", index=False, header=not os.path.exists(HISTORIA))
    bitacora(f"OK · {len(tabla)} de {len(CANASTA)} productos · canasta USD {tabla.precio_usd.sum():.2f}")
    print(f"\n✔ LISTO: {len(tabla)} de {len(CANASTA)} productos · la canasta cuesta hoy USD {tabla.precio_usd.sum():.2f}")
elif os.path.exists(FOTO):                               # REGLA 4
    bitacora(f"FALLÓ · solo {len(tabla)} productos · se conserva la canasta anterior")
    print(f"\n⚠ Solo llegaron {len(tabla)} productos. NO se pisa la canasta anterior [RESPALDO].")
else:
    bitacora(f"FALLÓ · solo {len(tabla)} productos · sin respaldo")
    print(f"\n✖ Solo llegaron {len(tabla)} productos y no hay canasta anterior.")
