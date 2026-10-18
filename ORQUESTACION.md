# Orquestación · G03 · Quién crece y quién se muere

## Qué puede ir a la vez
Las tareas de extracción de datos de las fuentes pueden ejecutarse en paralelo porque son independientes entre sí y no se esperan.

## Nuestro plan B
Si una fuente no responde tras los reintentos, el orquestador usará el último archivo de respaldo guardado para evitar detener todo el flujo.

## Nuestra hora y por qué
Reloj: `0 11 * * *` (todos los días a las 11:00 UTC (06:00 en Quito))

A las 11:00 UTC (06:00 de Quito), para tener la información actualizada y lista antes de que inicie la jornada laboral diaria.

## Qué guardamos cada día para comparar
Los indicadores diarios consolidados en formato CSV dentro de la carpeta data, para mantener un histórico y comparar tendencias a lo largo del tiempo.
