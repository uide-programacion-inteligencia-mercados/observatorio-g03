# Decisiones de Distribución del Informe · Equipo G03

### 1. ¿A quién llega el informe?
El informe está dirigido a la Gerencia General, al Director de Planificación Estratégica y a los coordinadores de operaciones comerciales.

### 2. ¿Por qué ese canal?
Se seleccionó el canal `#informes-g03` en Slack porque centraliza la comunicación ejecutiva del observatorio, reduce la saturación de los correos electrónicos y permite revisar el resumen y las alertas antes del inicio de la jornada laboral.

### 3. ¿Cuándo se envía (cron y conversión a UTC)?
- **Hora local de Quito**: Todos los días a las 06:45 AM (UTC-5).
- **Conversión a UTC**: 06:45 + 5 horas = 11:45 UTC.
- **Expresión cron**: `45 11 * * *`
Se programó 30 minutos después del robot de recolección para garantizar que el archivo PDF ya esté compilado y validado en la carpeta `reports/`.

### 4. ¿Qué pasa si falla el envío?
Si el envío falla por corte de red o error de API, el script no sobreescribe ni daña el informe PDF. El evento se registra como `fallido` en `logs/envios_g03.jsonl` y se genera una alerta automática en GitHub Issues (`🚨 No se pudo hacer llegar el informe`) para que el equipo intervenga. El último informe válido permanece intacto en `reports/`.

### 5. Privacidad y protección de secretos
La URL del webhook otorga permisos de publicación en Slack, por lo que se resguarda exclusivamente en GitHub Secrets bajo la variable `SLACK_WEBHOOK_URL`. No se expone en código fuente ni en commits públicos. Además, el informe contiene indicadores agregados, sin datos personales sensibles.
