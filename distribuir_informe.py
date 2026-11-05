# ============================================================================
# ARCHIVO: distribuir_informe.py        (el CARTERO del Observatorio)  · SEMANA 9
# ----------------------------------------------------------------------------
# QUÉ ES:   El programa que hace LLEGAR el informe PDF a quien lo necesita.
# QUÉ HACE: 1. Revisa el informe con un portero (¿existe? ¿es un PDF de verdad?).
#           2. Arma el mensaje: titular + semáforo del robot + enlace al informe.
#           3. Lo envía por los canales que estén configurados:
#                · Slack (webhook)   · Teams (webhook de Workflows)
#                · Correo por SMTP   · Correo por SendGrid
#           4. Si un envío falla por algo pasajero, REINTENTA con espera creciente.
#           5. NO envía dos veces lo mismo el mismo día (idempotencia).
#           6. Anota todo en logs/envios_<equipo>.jsonl (sin guardar secretos ni correos).
# MODOS:    ENSAYO = arma el mensaje y lo guarda en logs/, pero NO envía nada.
#           REAL   = envía de verdad.
# SEGURIDAD: las llaves (webhooks, contraseñas) NUNCA van escritas aquí.
#            Llegan desde los «Secrets» de GitHub, como variables de entorno.
# NO NECESITA INSTALAR NADA: solo usa lo que Python ya trae.
# ESTO PUEDEN CAMBIARLO: los textos del mensaje (función armar_mensaje) y MAX_DIAS_ANTIGUEDAD.
# ============================================================================
import base64
import json
import os
import re
import smtplib
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

# ---------------------------------------------------------------- configuración
REPO = os.environ.get("GITHUB_REPOSITORY", "uide-programacion-inteligencia-mercados/observatorio-g00")
SERVIDOR = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
_m = re.search(r"-(g\d{2})$", REPO)
EQUIPO = os.environ.get("EQUIPO") or (_m.group(1) if _m else "faro")

MODO = (os.environ.get("MODO_ENVIO") or "real").strip().lower()      # "real" o "ensayo"
SIMULAR_FALLA = (os.environ.get("SIMULAR_FALLA") or "").strip().lower() == "true"
FORZAR_REENVIO = (os.environ.get("FORZAR_REENVIO") or "").strip().lower() == "true"
MAX_DIAS_ANTIGUEDAD = 2          # un informe más viejo que esto se envía, pero marcado como «viejo»
INTENTOS = 3                     # cuántas veces se intenta un envío antes de rendirse
ESPERA_BASE = 1                  # segundos; la espera crece: 1, 2, 4...
TIEMPO_LIMITE = 20               # segundos que se espera la respuesta de un servicio

LOGS = Path("logs")
REPORTES = Path("reports")
BITACORA_ENVIOS = LOGS / f"envios_{EQUIPO}.jsonl"
SALUD = LOGS / f"salud_{EQUIPO}.csv"
TEXTOS = Path("config_informe.json")


class ErrorDeEnvio(Exception):
    """No se pudo enviar y reintentar no lo arregla (ejemplo: el webhook no existe)."""


class ErrorPasajero(Exception):
    """Falla que puede pasar sola (servicio ocupado, sin internet un instante)."""


# ---------------------------------------------------------------- el portero del informe
def localizar_informe():
    """Busca el informe del equipo; si no existe, usa reports/ultimo.pdf (el Observatorio de Referencia)."""
    propio = os.environ.get("INFORME")
    for candidato in ([Path(propio)] if propio else []) + [REPORTES / f"informe_{EQUIPO}.pdf", REPORTES / "ultimo.pdf"]:
        if candidato.exists():
            return candidato
    raise ErrorDeEnvio(f"no hay informe que enviar: no existe reports/informe_{EQUIPO}.pdf")


def portero_del_informe(ruta):
    """Un informe vacío o roto NO se envía. Devuelve cuántos días tiene de antigüedad."""
    datos = ruta.read_bytes()
    if len(datos) < 3000:
        raise ErrorDeEnvio(f"el informe pesa solo {len(datos)} bytes: parece vacío; no se envía")
    if not datos.startswith(b"%PDF-"):
        raise ErrorDeEnvio("el archivo no empieza con %PDF-: no es un PDF de verdad; no se envía")
    edad = (datetime.now(timezone.utc) - datetime.fromtimestamp(ruta.stat().st_mtime, timezone.utc)).days
    return max(edad, 0)


# ---------------------------------------------------------------- el mensaje
def _salud_del_robot():
    """Lee el semáforo de la última corrida del robot (lo escribe el robot en logs/salud_<equipo>.csv)."""
    try:
        # Los equipos usan salud_<equipo>.csv; el Observatorio de Referencia usa salud.csv
        archivo = SALUD if SALUD.exists() else LOGS / "salud.csv"
        lineas = archivo.read_text(encoding="utf-8").strip().splitlines()
        cab = lineas[0].split(",")
        ult = lineas[-1].split(",")
        fila = dict(zip(cab, ult))
        return fila.get("estado", "sin dato").upper()
    except Exception:
        return "SIN DATO"


def _titular():
    try:
        return json.loads(TEXTOS.read_text(encoding="utf-8")).get("titular", "").strip() or "Informe del observatorio listo"
    except Exception:
        return "Informe del observatorio listo"


def armar_mensaje(dias_viejo):
    """Devuelve (asunto, texto). El asunto ya dice lo importante sin abrir el correo."""
    hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    semaforo = _salud_del_robot()
    viejo = f" · OJO: informe de hace {dias_viejo} días" if dias_viejo > MAX_DIAS_ANTIGUEDAD else ""
    asunto = f"[Observatorio {EQUIPO.upper()}] Informe del {hoy} · robot {semaforo}{viejo}"
    enlace = f"{SERVIDOR}/{REPO}/blob/main/reports/{localizar_informe().name}"
    texto = (f"{_titular()}\n\n"
             f"Estado del robot: {semaforo}\n"
             f"Informe completo (PDF): {enlace}\n"
             f"Fuente y fecha de los datos: dentro del informe, en la sección «Calidad de los datos».")
    if viejo:
        texto += f"\n\nAtención: este informe tiene {dias_viejo} días. El robot no pudo renovarlo; revise la alerta en Issues."
    return asunto, texto


# ---------------------------------------------------------------- una sola puerta para salir a internet
def _post_json(url, cuerpo, cabeceras=None):
    pedido = urllib.request.Request(url, data=json.dumps(cuerpo).encode("utf-8"), method="POST",
                                    headers={"Content-Type": "application/json", **(cabeceras or {})})
    try:
        with urllib.request.urlopen(pedido, timeout=TIEMPO_LIMITE) as r:
            return r.status
    except urllib.error.HTTPError as e:
        if e.code in (408, 425, 429) or e.code >= 500:
            raise ErrorPasajero(f"el servicio respondió {e.code}")
        raise ErrorDeEnvio(f"el servicio rechazó el envío con código {e.code} (revise el secreto o la dirección)")
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise ErrorPasajero(f"no se pudo conectar: {getattr(e, 'reason', e)}")


# ---------------------------------------------------------------- los canales
def enviar_slack(asunto, texto, ruta):
    url = os.environ["SLACK_WEBHOOK_URL"]
    _post_json(url, {"text": f"*{asunto}*\n{texto}"})


def enviar_teams(asunto, texto, ruta):
    url = os.environ["TEAMS_WEBHOOK_URL"]
    tarjeta = {"type": "message", "attachments": [{
        "contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None,
        "content": {"$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard", "version": "1.4",
                    "body": [{"type": "TextBlock", "text": asunto, "weight": "Bolder", "wrap": True},
                             {"type": "TextBlock", "text": texto, "wrap": True}]}}]}
    _post_json(url, tarjeta)


def _destinatarios():
    return [d.strip() for d in os.environ.get("CORREO_DESTINO", "").split(",") if d.strip()]


def enviar_correo_smtp(asunto, texto, ruta):
    puerto = int(os.environ.get("SMTP_PORT") or "587")   # un secreto sin crear llega como texto vacío
    remitente = os.environ.get("CORREO_REMITENTE") or os.environ["SMTP_USER"]
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = asunto, remitente, ", ".join(_destinatarios())
    msg.set_content(texto)
    msg.add_attachment(ruta.read_bytes(), maintype="application", subtype="pdf", filename=ruta.name)
    try:
        if puerto == 465:
            servidor = smtplib.SMTP_SSL(os.environ["SMTP_HOST"], puerto, timeout=TIEMPO_LIMITE)
        else:
            servidor = smtplib.SMTP(os.environ["SMTP_HOST"], puerto, timeout=TIEMPO_LIMITE)
            servidor.starttls()
        with servidor:
            servidor.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            servidor.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        raise ErrorDeEnvio("el servidor de correo rechazó el usuario o la contraseña (use una contraseña de aplicación)")
    except smtplib.SMTPRecipientsRefused:
        raise ErrorDeEnvio("el servidor rechazó a los destinatarios")
    except (smtplib.SMTPException, OSError) as e:
        raise ErrorPasajero(f"falla pasajera del correo: {type(e).__name__}")


def enviar_sendgrid(asunto, texto, ruta):
    remitente = os.environ["CORREO_REMITENTE"]
    cuerpo = {"personalizations": [{"to": [{"email": d} for d in _destinatarios()]}],
              "from": {"email": remitente}, "subject": asunto,
              "content": [{"type": "text/plain", "value": texto}],
              "attachments": [{"content": base64.b64encode(ruta.read_bytes()).decode("ascii"),
                               "type": "application/pdf", "filename": ruta.name, "disposition": "attachment"}]}
    _post_json("https://api.sendgrid.com/v3/mail/send", cuerpo, {"Authorization": f"Bearer {os.environ['SENDGRID_API_KEY']}"})


def canales_configurados():
    """Un canal existe solo si TODOS sus secretos están puestos. Devuelve {nombre: función}."""
    hay = lambda *claves: all(os.environ.get(c, "").strip() for c in claves)
    canales = {}
    if hay("SLACK_WEBHOOK_URL"):
        canales["slack"] = enviar_slack
    if hay("TEAMS_WEBHOOK_URL"):
        canales["teams"] = enviar_teams
    if hay("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "CORREO_DESTINO"):
        canales["correo_smtp"] = enviar_correo_smtp
    if hay("SENDGRID_API_KEY", "CORREO_REMITENTE", "CORREO_DESTINO"):
        canales["sendgrid"] = enviar_sendgrid
    return canales


# ---------------------------------------------------------------- bitácora e idempotencia
def anotar(canal, estado, detalle="", intentos=0):
    LOGS.mkdir(exist_ok=True)
    linea = {"momento": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "fecha": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
             "equipo": EQUIPO, "canal": canal, "estado": estado, "modo": MODO, "intentos": intentos, "detalle": detalle[:200]}
    with BITACORA_ENVIOS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(linea, ensure_ascii=False) + "\n")


def ya_enviado_hoy(canal):
    if FORZAR_REENVIO or not BITACORA_ENVIOS.exists():
        return False
    hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for linea in BITACORA_ENVIOS.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(linea)
        except ValueError:
            continue
        if d.get("fecha") == hoy and d.get("canal") == canal and d.get("estado") == "enviado":
            return True
    return False


# ---------------------------------------------------------------- reintentos
def con_reintentos(funcion, asunto, texto, ruta):
    """Hasta INTENTOS veces, esperando 1, 2, 4... segundos. Lo permanente no se reintenta."""
    for intento in range(1, INTENTOS + 1):
        try:
            if SIMULAR_FALLA:
                raise ErrorPasajero("simulacro: el servicio no está disponible")
            funcion(asunto, texto, ruta)
            return intento
        except ErrorPasajero as e:
            if intento == INTENTOS:
                raise ErrorDeEnvio(f"se agotaron los {INTENTOS} intentos ({e})")
            espera = ESPERA_BASE * 2 ** (intento - 1)
            print(f"   intento {intento} falló ({e}); espero {espera} s y reintento")
            time.sleep(espera)


# ---------------------------------------------------------------- programa principal
def principal():
    print(f"Equipo {EQUIPO.upper()} · modo {MODO.upper()}" + (" · SIMULACRO" if SIMULAR_FALLA else ""))
    ruta = localizar_informe()
    dias = portero_del_informe(ruta)
    print(f"Portero: {ruta.name} pasa (antigüedad {dias} día(s))")
    asunto, texto = armar_mensaje(dias)

    if MODO == "ensayo":
        LOGS.mkdir(exist_ok=True)
        (LOGS / f"ensayo_mensaje_{EQUIPO}.txt").write_text(f"ASUNTO: {asunto}\n\n{texto}\n", encoding="utf-8")
        canales = canales_configurados()
        nombres = ", ".join(canales) or "ninguno todavía"
        anotar("ensayo", "ensayo", f"canales listos: {nombres}")
        print(f"ENSAYO: mensaje guardado en logs/ensayo_mensaje_{EQUIPO}.txt. Canales con secretos puestos: {nombres}.")
        print("RESULTADO: ensayo correcto (no se envió nada)")
        return 0

    canales = canales_configurados()
    if not canales:
        print("RESULTADO: no hay ningún canal configurado. Cree al menos el secreto SLACK_WEBHOOK_URL o TEAMS_WEBHOOK_URL.")
        anotar("ninguno", "fallido", "sin canales configurados")
        return 1

    fallos = 0
    for nombre, funcion in canales.items():
        # El simulacro no envía nada de verdad, así que ignora el «ya se envió hoy» y puede probarse en cualquier momento.
        if not SIMULAR_FALLA and ya_enviado_hoy(nombre):
            print(f"· {nombre}: ya se envió hoy; no se repite")
            anotar(nombre, "omitido", "ya enviado hoy")
            continue
        try:
            intentos = con_reintentos(funcion, asunto, texto, ruta)
            anotar(nombre, "enviado", "ok", intentos)
            print(f"· {nombre}: ENVIADO (intentos: {intentos})")
        except ErrorDeEnvio as e:
            fallos += 1
            anotar(nombre, "fallido", str(e), INTENTOS if "intentos" in str(e) else 1)
            print(f"· {nombre}: FALLÓ ({e})")
    if fallos:
        print(f"RESULTADO: {fallos} canal(es) fallaron. El informe sigue guardado; se abre una alerta.")
        return 1
    print("RESULTADO: distribución correcta")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(principal())
    except ErrorDeEnvio as e:
        print(f"RESULTADO: no se envió nada: {e}")
        try:
            anotar("ninguno", "fallido", str(e))
        except Exception:
            pass
        sys.exit(1)
