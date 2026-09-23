# MS5 — Analytics Gateway

MS5 es la interfaz HTTP entre el frontend y Amazon Athena. No consulta las bases
operativas: consulta las tablas de Glue sobre los archivos que los tres procesos de
ingesta cargan en S3. Las consultas admitidas son predefinidas para no exponer SQL
arbitrario desde el navegador.

## Ejecutar localmente

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp env.example .env
python main.py
```

Para ejecutar las pruebas del gateway instala también `requirements-dev.txt` y
ejecuta `python -m unittest discover -p 'test_*.py'`.

Sin `ATHENA_ENABLED=true` y `ATHENA_OUTPUT_S3`, el servicio arranca en modo
deshabilitado y devuelve esa configuración en `/api/v1/analytics/status`; no inventa
resultados. En AWS usa un rol IAM de la MV o del contenedor. No pongas claves AWS en
el frontend ni en el repositorio.

## API

- `GET /health`: estado del proceso y si Athena está habilitado.
- `GET /api/v1/analytics/status`: configuración efectiva y faltantes.
- `GET /api/v1/analytics/reports`: cuatro reportes disponibles y dos vistas.
- `POST /api/v1/analytics/queries` con `{ "report": "fire_summary", "country": "Perú" }`: inicia una consulta y devuelve `query_id`.
- `GET /api/v1/analytics/queries/{query_id}`: estado `QUEUED`, `RUNNING`, `SUCCEEDED` o `FAILED`.
- `GET /api/v1/analytics/queries/{query_id}/results`: filas paginadas de Athena.
- `POST /api/v1/analytics/views`: encola la creación de `v_city_latest_weather` y `v_fire_city_exposure`.

Los reportes unen las tablas `fire_events`, `fire_detections`, `cities`,
`sensitive_sites` y `weather_readings`. La relación incendio–ciudad es geográfica
(150 km), mientras que `fire_detections.fire_event_id`, `sensitive_sites.city_id` y
`weather_readings.city_id` son relaciones por ID.

El esquema exacto y las ubicaciones S3 esperadas están documentados en
[`data-ingestion/athena_schema.json`](../data-ingestion/athena_schema.json). La
tabla `fires` no sustituye al modelo de MS1: las detecciones deben registrarse
como `fire_detections` y relacionarse con `fire_events` mediante `fire_event_id`.

La respuesta de Athena se obtiene de forma asíncrona: iniciar una consulta no espera
bloqueado al motor. Primero consulta el estado y después los resultados. La salida de
Athena debe estar en un bucket S3 accesible por el mismo rol IAM.

FastAPI publica Swagger UI en `http://127.0.0.1:8085/docs` y el esquema OpenAPI en
`http://127.0.0.1:8085/openapi.json`.
