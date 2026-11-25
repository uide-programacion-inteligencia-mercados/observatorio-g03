# ============================================================================
# ARCHIVO: dashboard_generico/app.py        (el TABLERO PARA CUALQUIER OBSERVATORIO)  · SEMANA 11
# QUÉ HACE:  Lee los CSV que tu robot guarda en la carpeta data/ y arma solo los filtros, los
#            números clave y los gráficos. No importa cómo se llamen tus columnas.
# RECIBE:    Cualquier archivo .csv dentro de data/ (el que tú elijas en la columna izquierda).
# ENTREGA:   Una página web con un enlace público (Streamlit Community Cloud).
# ESTO PUEDEN CAMBIARLO: los textos del archivo textos.txt (TITULO, FUENTE, PREGUNTA, LECTURA). No hace falta tocar este archivo.
# NO NECESITAN CAMBIAR: este archivo. Si tus datos cambian de nombre o de columnas, el tablero se adapta.
# ============================================================================
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

# --- TU PROYECTO: textos que puedes cambiar ---
TITULO = "Observatorio de mi grupo"
SUBTITULO = "El robot busca, limpia y analiza los datos. Esta página los muestra con filtros."
FUENTE = "Fuente: escribe aquí de dónde vienen tus datos"
PREGUNTA = ""   # La pregunta de negocio que responde tu tablero. Ejemplo: "¿En qué sector conviene comprar?"
LECTURA = ""    # Tu lectura en 2 o 3 frases: qué dicen los números y qué decisión sugieren.

# --- Los textos también se pueden escribir en el archivo textos.txt (carpeta dashboard): es más fácil que tocar el código ---
def leer_textos():
    ruta = Path(__file__).resolve().parent / "textos.txt"
    if not ruta.is_file():
        return {}
    encontrados = {}
    for linea in ruta.read_text(encoding="utf-8-sig").splitlines():
        if linea.strip().startswith("#") or ":" not in linea:
            continue
        clave, valor = linea.split(":", 1)
        clave = clave.strip().upper()
        if clave in ("TITULO", "SUBTITULO", "FUENTE", "PREGUNTA", "LECTURA") and valor.strip():
            encontrados[clave] = valor.strip()
    return encontrados


_t = leer_textos()
TITULO = _t.get("TITULO", TITULO)
SUBTITULO = _t.get("SUBTITULO", SUBTITULO)
FUENTE = _t.get("FUENTE", FUENTE)
PREGUNTA = _t.get("PREGUNTA", PREGUNTA)
LECTURA = _t.get("LECTURA", LECTURA)

st.set_page_config(page_title=TITULO, page_icon="📊", layout="wide")


def buscar_raiz():
    """Sube de carpeta hasta encontrar la que contiene la carpeta data/ (la raíz de tu repositorio)."""
    aqui = Path(__file__).resolve().parent
    for carpeta in [aqui, *aqui.parents]:
        if (carpeta / "data").is_dir():
            return carpeta
    return aqui


RAIZ = buscar_raiz()


@st.cache_data(ttl=600)
def leer(ruta):
    """Lee un CSV (separador coma o punto y coma). Se guarda en memoria 10 minutos para ir rápido."""
    return pd.read_csv(ruta, sep=None, engine="python")


@st.cache_data(ttl=600)
def listar_csv(raiz):
    return sorted(str(p.relative_to(raiz)).replace("\\", "/") for p in Path(raiz).glob("data/**/*.csv"))


st.title(TITULO)
st.caption(SUBTITULO)
if PREGUNTA.strip():
    st.info(f"**Pregunta que responde este tablero:** {PREGUNTA}" + (f"\n\n**Lectura del equipo:** {LECTURA}" if LECTURA.strip() else ""))

archivos = listar_csv(str(RAIZ))
if not archivos:
    st.error("No encuentro archivos .csv dentro de la carpeta data/. Corre el robot (pestaña Actions) y recarga esta página.")
    st.stop()

# --- ELEGIR EL ARCHIVO (se prefiere uno «limpio») ---
preferido = next((i for i, a in enumerate(archivos) if "limpi" in a.lower()), 0)
st.sidebar.header("Datos")
archivo = st.sidebar.selectbox("Archivo", archivos, index=preferido)
df = leer(str(RAIZ / archivo))
if df.empty:
    st.warning("Ese archivo está vacío.")
    st.stop()

# --- DETECTAR EL TIPO DE CADA COLUMNA ---
def es_id(nombre, serie):
    n = nombre.lower()
    if n == "id" or n.endswith("_id") or n.startswith("id_"):
        return True
    # un número entero distinto en cada fila (1, 2, 3...) es un código, no una medida
    return pd.api.types.is_integer_dtype(serie) and serie.nunique() == len(serie) and len(serie) > 20


def es_anio(nombre, serie):
    """Columnas como anio / año / mes / year: sirven para ordenar en el tiempo, no para medir."""
    n = nombre.lower()
    return n in ("anio", "año", "ano", "year", "anyo", "mes", "month", "periodo_num") and pd.api.types.is_numeric_dtype(serie)


fechas = []
for c in df.columns:
    if "fecha" in c.lower() or "date" in c.lower():
        convertida = pd.to_datetime(df[c], errors="coerce")
        if convertida.notna().mean() > 0.8:
            df[c] = convertida
            fechas.append(c)
anios = [c for c in df.columns if es_anio(c, df[c])]
numericas = [c for c in df.select_dtypes("number").columns if not es_id(c, df[c]) and c not in anios]
textos = [c for c in df.columns if c not in fechas and c not in numericas and c not in anios and pd.api.types.is_string_dtype(df[c])]
categoricas = [c for c in textos if 2 <= df[c].nunique() <= 40]      # sirven para filtrar
agrupables = [c for c in textos if 2 <= df[c].nunique() <= 300]      # sirven para comparar grupos

# --- FILTROS (columna izquierda): cada filtro recorta la tabla ANTES de calcular ---
st.sidebar.header("Filtros")
filtrado = df.copy()
for c in categoricas[:3]:
    opciones = sorted(df[c].dropna().astype(str).unique())
    elegidas = st.sidebar.multiselect(c, opciones, default=opciones)
    filtrado = filtrado[filtrado[c].astype(str).isin(elegidas) | filtrado[c].isna()]
for c in numericas[:2]:
    mn, mx = float(df[c].min()), float(df[c].max())
    if mn < mx:
        rango = st.sidebar.slider(c, mn, mx, (mn, mx))
        filtrado = filtrado[filtrado[c].between(rango[0], rango[1])]
st.sidebar.write(f"**{len(filtrado):,}** de {len(df):,} filas con estos filtros")

# --- NÚMERO CLAVE: la columna que quieres medir ---
metrica = None
if numericas:
    metrica = st.sidebar.selectbox("¿Qué quieres medir?", numericas)

# --- TARJETAS (KPI) ---
k1, k2, k3, k4 = st.columns(4)
k1.metric("Filas", f"{len(filtrado):,}")
if metrica and len(filtrado):
    k2.metric(f"Mediana de {metrica}", f"{filtrado[metrica].median():,.2f}")
    k3.metric(f"Promedio de {metrica}", f"{filtrado[metrica].mean():,.2f}")
    k4.metric(f"Máximo de {metrica}", f"{filtrado[metrica].max():,.2f}")
else:
    k2.metric("Mediana", "sin datos")
    k3.metric("Promedio", "sin datos")
    k4.metric("Máximo", "sin datos")

if categoricas and metrica:
    st.caption("Si tu archivo mezcla cosas con unidades distintas (por ejemplo dos indicadores), "
               "deja marcado un solo valor en los filtros de la izquierda para que las tarjetas tengan sentido.")

if filtrado.empty:
    st.warning("Con estos filtros no queda ninguna fila. Amplía los filtros en la columna izquierda.")

t1, t2, t3, t4, t5 = st.tabs(["📋 Resumen", "📍 Comparar", "📈 Tendencia", "📊 Distribución", "🩺 Calidad"])

with t1:
    st.subheader("Así se ven tus datos")
    st.dataframe(filtrado.head(200), hide_index=True, width="stretch")
    st.download_button("⬇️ Descargar lo filtrado (CSV)", filtrado.to_csv(index=False).encode("utf-8"), "datos_filtrados.csv", "text/csv")

with t2:
    st.subheader("¿Qué grupos destacan?")
    if not agrupables:
        st.info("Este archivo no tiene columnas de categorías (texto con pocos valores distintos) para comparar.")
    else:
        por = st.selectbox("Agrupar por", agrupables)
        mayor = int(filtrado[por].value_counts().max()) if len(filtrado) else 1
        minimo = st.slider("Mínimo de filas por grupo", 1, 30, 3 if mayor >= 3 else 1,
                           help="Un grupo con pocas filas no da una mediana confiable.")
        if metrica:
            g = (filtrado.groupby(por).agg(filas=(metrica, "size"), mediana=(metrica, "median"), promedio=(metrica, "mean"))
                 .round(2).reset_index())
            g = g[g["filas"] >= minimo].sort_values("mediana", ascending=False)
            if g.empty:
                st.info("Ningún grupo llega al mínimo. Bájalo con el deslizador.")
            else:
                st.bar_chart(g.head(15).set_index(por)["mediana"], color="#002A54", horizontal=True)
                st.dataframe(g, hide_index=True, width="stretch")
        else:
            g = filtrado[por].value_counts().rename_axis(por).reset_index(name="filas")
            st.bar_chart(g.head(15).set_index(por)["filas"], color="#002A54", horizontal=True)

with t3:
    st.subheader("¿Cambia con el tiempo?")
    ejes = fechas + anios
    if not ejes or not metrica:
        st.info("Para ver tendencia hace falta una columna de fecha (o de año) y una columna numérica.")
    else:
        eje = st.selectbox("Eje del tiempo", ejes)
        separar = ["(una sola línea)"] + [c for c in categoricas if df[c].nunique() <= 12]
        por_linea = st.selectbox("Una línea por", separar, index=1 if len(separar) > 1 and df[separar[1]].nunique() <= 8 else 0)
        base = filtrado.dropna(subset=[eje]).copy()
        base["_x"] = base[eje].dt.date if eje in fechas else base[eje]
        if por_linea == "(una sola línea)":
            serie = base.groupby("_x")[metrica].median()
        else:
            serie = base.groupby(["_x", por_linea])[metrica].median().unstack(por_linea)
        if len(serie) < 2:
            st.info("Todavía hay un solo punto en el tiempo. La tendencia aparece cuando el robot acumula días.")
        else:
            st.line_chart(serie)
            st.caption(f"Cada punto es la mediana de {metrica} por {'día' if eje in fechas else 'año'}.")

with t4:
    st.subheader("¿Cómo se reparten los valores?")
    if not metrica or filtrado.empty:
        st.info("Elige una columna numérica y deja al menos una fila.")
    else:
        valores = filtrado[metrica].dropna()
        cuentas, bordes = np.histogram(valores, bins=15)
        etiquetas = [f"{bordes[i]:,.0f}–{bordes[i + 1]:,.0f}" for i in range(len(cuentas))]
        st.bar_chart(pd.Series(cuentas, index=etiquetas, name="filas"), color="#FFC72C")
        st.caption("Cada barra cuenta cuántas filas caen en ese rango de valores.")

with t5:
    st.subheader("¿Qué tan completos están los datos?")
    calidad = pd.DataFrame({"columna": df.columns, "tipo": [str(t) for t in df.dtypes],
                            "vacíos (%)": (df.isna().mean() * 100).round(1).values,
                            "valores distintos": [df[c].nunique() for c in df.columns]})
    st.dataframe(calidad, hide_index=True, width="stretch")
    st.metric("Filas duplicadas", int(df.duplicated().sum()))

st.divider()
st.caption(FUENTE + " · Hecho con Streamlit · UIDE")
