# Robot del Banco Mundial · equipo g03
# Trae los dos indicadores del equipo y los guarda en data/.
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

EQUIPO = "g03"
INDICADORES = {'NY.GDP.MKTP.KD.ZG': 'Crecimiento del PIB (%)', 'NV.SRV.TOTL.KD.ZG': 'Crecimiento de los servicios (%)'}
DESDE, HASTA = 2015, 2025

Path("data").mkdir(exist_ok=True)
Path("logs").mkdir(exist_ok=True)


def traer(codigo):
    url = (f"https://api.worldbank.org/v2/country/ECU/indicator/{codigo}"
           f"?format=json&date={DESDE}:{HASTA}&per_page=100")
    for intento in range(1, 4):                      # hasta 3 intentos
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            return r.json()[1]
        except Exception as e:
            print(f"   {codigo}: intento {intento} falló ({e})")
            time.sleep(3)
    raise RuntimeError(f"El Banco Mundial no contestó para {codigo}")


filas = []
for codigo, nombre in INDICADORES.items():
    print(f"Trayendo {nombre}")
    for d in traer(codigo):
        if d["value"] is not None:
            filas.append({"anio": int(d["date"]), "codigo": codigo, "indicador": nombre, "valor": d["value"]})

tabla = pd.DataFrame(filas).sort_values(["codigo", "anio"])
if tabla.empty:
    raise RuntimeError("No llegó ningún dato.")
tabla.to_csv(f"data/indicadores_{EQUIPO}.csv", index=False)

resumen = {
    "equipo": EQUIPO,
    "corrida_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "filas": int(len(tabla)),
    "ultimo_anio_por_indicador": {n: int(tabla[tabla.codigo == c].anio.max()) for c, n in INDICADORES.items()},
}
Path(f"logs/ultima_corrida_{EQUIPO}.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")
print("Listo:", resumen)
