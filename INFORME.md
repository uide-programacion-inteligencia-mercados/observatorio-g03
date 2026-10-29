# Informe automático · G03 · Quién crece y quién se muere

![Estado del robot](https://github.com/uide-programacion-inteligencia-mercados/observatorio-g03/actions/workflows/orquestador_diario.yml/badge.svg)

El robot escribe todos los días su propio informe en PDF: **`reports/informe_g03.pdf`**.
La insignia de arriba dice si la última corrida terminó bien (verde) o mal (rojo).

## Para quién es y qué decisión ayuda a tomar
**Lector:** Gerente de Planificación Estratégica

Ayuda a decidir si se deben frenar o expandir las inversiones comerciales y operativas en función de si el sector servicios crece por encima o por debajo del PIB general.

## Qué dejamos fuera y por qué
Dejamos fuera desgloses subsectoriales detallados y series históricas muy extensas, porque saturaban la lectura ejecutiva y desviaban la atención de la tendencia macroeconómica principal.

## Cuándo se lee
Se lee de forma automatizada cada inicio de semana antes de las reuniones de comité de gerencia general y planificación.

## Cómo sabemos que es confiable
Porque cuenta con reglas de resiliencia que validan rangos lógicos y un portero de PDF que rechaza archivos vacíos o corruptos, conservando siempre la última versión íntegra.

## Cómo se arma el informe
1. `robot_banco_mundial.py` trae los datos, los revisa con las reglas del equipo y los guarda.
2. `config_informe.json` tiene los textos del equipo (titular, lectura de negocio y recomendación).
3. `plantillas/informe.html.j2` es el molde con huecos que rellena Jinja2.
4. WeasyPrint imprime el PDF. Si el PDF sale roto, el portero lo rechaza y queda el informe anterior.
5. Reloj del robot: `15 11 * * *`
