"""Gateway seguro y asíncrono para consultas predefinidas de Amazon Athena."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv(Path(__file__).with_name('.env'))
PUBLIC_BASE_PATH = os.getenv('PUBLIC_BASE_PATH', '').strip().rstrip('/') or ''

REPORTS = {
    'fire_summary': {
        'title': 'Resumen de incendios y detecciones',
        'description': 'Agrega potencia, eventos y detecciones por país.',
        'sql': """
SELECT fe.country_hint AS country, COUNT(DISTINCT fe.id) AS fire_events,
       COUNT(fd.id) AS detections, ROUND(MAX(fe.max_frp), 2) AS max_frp_mw,
       ROUND(AVG(fe.max_frp), 2) AS avg_event_frp_mw
FROM fire_events fe LEFT JOIN fire_detections fd ON fd.fire_event_id = fe.id
WHERE 1 = 1 {country_filter}
GROUP BY fe.country_hint ORDER BY detections DESC
""",
    },
    'weather_by_city': {
        'title': 'Último clima por ciudad',
        'description': 'Relaciona ciudades con su lectura meteorológica más reciente.',
        'sql': """
WITH latest_weather AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY city_id ORDER BY timestamp DESC) AS rn FROM weather_readings)
SELECT c.id AS city_id, c.name, c.country, c.population, w.timestamp, w.temperature_c,
       w.wind_speed_kmh, w.wind_direction_deg, w.pm25_ug_m3, w.humidity_pct
FROM cities c JOIN latest_weather w ON w.city_id = c.id AND w.rn = 1
WHERE 1 = 1 {country_filter} ORDER BY c.country, c.name
""",
    },
    'fire_city_exposure': {
        'title': 'Exposición de ciudades a incendios',
        'description': 'Une incendios con ciudades cercanas mediante distancia geográfica.',
        'sql': """
SELECT fe.id AS fire_event_id, fe.country_hint AS fire_country, c.id AS city_id,
       c.name, c.country, c.population,
       ROUND(6371 * 2 * ASIN(SQRT(POWER(SIN(RADIANS(c.latitude-fe.centroid_lat)/2),2) +
       COS(RADIANS(fe.centroid_lat))*COS(RADIANS(c.latitude))*POWER(SIN(RADIANS(c.longitude-fe.centroid_lon)/2),2))),2) AS distance_km,
       fe.max_frp, fe.last_detected_at
FROM fire_events fe JOIN cities c ON 6371 * 2 * ASIN(SQRT(POWER(SIN(RADIANS(c.latitude-fe.centroid_lat)/2),2) +
       COS(RADIANS(fe.centroid_lat))*COS(RADIANS(c.latitude))*POWER(SIN(RADIANS(c.longitude-fe.centroid_lon)/2),2))) <= 150
WHERE 1 = 1 {country_filter} ORDER BY distance_km, fe.max_frp DESC
""",
    },
    'sensitive_sites_exposure': {
        'title': 'Sitios sensibles cercanos a incendios',
        'description': 'Relaciona sitios sensibles, ciudades e incendios próximos.',
        'sql': """
SELECT ss.id AS sensitive_site_id, ss.name AS site_name, ss.type, c.id AS city_id,
       c.name AS city_name, c.country, fe.id AS fire_event_id, fe.max_frp, fe.last_detected_at
FROM sensitive_sites ss JOIN cities c ON c.id = ss.city_id JOIN fire_events fe ON 6371 * 2 * ASIN(SQRT(
       POWER(SIN(RADIANS(c.latitude-fe.centroid_lat)/2),2) + COS(RADIANS(fe.centroid_lat))*COS(RADIANS(c.latitude))*
       POWER(SIN(RADIANS(c.longitude-fe.centroid_lon)/2),2))) <= 150
WHERE 1 = 1 {country_filter} ORDER BY fe.max_frp DESC, c.country, c.name
""",
    },
}

VIEWS = {
    'v_city_latest_weather': """
CREATE OR REPLACE VIEW v_city_latest_weather AS
WITH ranked AS (SELECT w.*, ROW_NUMBER() OVER (PARTITION BY city_id ORDER BY timestamp DESC) AS rn FROM weather_readings w)
SELECT c.id AS city_id, c.name, c.country, c.population, r.timestamp, r.temperature_c,
       r.wind_speed_kmh, r.wind_direction_deg, r.pm25_ug_m3, r.humidity_pct
FROM cities c JOIN ranked r ON r.city_id = c.id AND r.rn = 1
""",
    'v_fire_city_exposure': """
CREATE OR REPLACE VIEW v_fire_city_exposure AS
SELECT fe.id AS fire_event_id, c.id AS city_id, c.name, c.country, fe.max_frp, fe.last_detected_at,
       6371 * 2 * ASIN(SQRT(POWER(SIN(RADIANS(c.latitude-fe.centroid_lat)/2),2) +
       COS(RADIANS(fe.centroid_lat))*COS(RADIANS(c.latitude))*POWER(SIN(RADIANS(c.longitude-fe.centroid_lon)/2),2))) AS distance_km
FROM fire_events fe JOIN cities c ON 6371 * 2 * ASIN(SQRT(POWER(SIN(RADIANS(c.latitude-fe.centroid_lat)/2),2) +
       COS(RADIANS(fe.centroid_lat))*COS(RADIANS(c.latitude))*POWER(SIN(RADIANS(c.longitude-fe.centroid_lon)/2),2))) <= 150
""",
}


def settings():
    return {'region': os.getenv('AWS_REGION', 'us-east-1'), 'database': os.getenv('ATHENA_DATABASE', 'smokecast_analytics'),
            'catalog': os.getenv('ATHENA_CATALOG', 'AwsDataCatalog'), 'output': os.getenv('ATHENA_OUTPUT_S3', ''),
            'workgroup': os.getenv('ATHENA_WORKGROUP', 'primary')}


def is_enabled():
    return os.getenv('ATHENA_ENABLED', 'false').lower() == 'true' and bool(settings()['output'])


def client():
    try:
        import boto3
    except ImportError as exc:
        raise HTTPException(status_code=503, detail='Instala boto3 para habilitar Athena') from exc
    return boto3.client('athena', region_name=settings()['region'])


def country_filter(country: str | None, column: str):
    if not country:
        return ''
    value = country.strip()
    if not re.fullmatch(r"[\wÀ-ÿ .'-]{1,80}", value, re.UNICODE):
        raise HTTPException(status_code=400, detail='country contiene caracteres inválidos')
    # El valor se valida y escapa antes de interpolarlo en SQL predefinido.
    # El nombre de columna se elige desde una lista fija por reporte; el valor
    # recibido se valida y escapa antes de interpolarlo en SQL predefinido.
    return " AND lower(COALESCE(" + column + ", '')) = lower('" + value.replace("'", "''") + "')"


REPORT_COUNTRY_COLUMNS = {
    'fire_summary': 'fe.country_hint',
    'weather_by_city': 'c.country',
    'fire_city_exposure': 'c.country',
    'sensitive_sites_exposure': 'c.country',
}


class QueryRequest(BaseModel):
    report: str = Field(..., min_length=1, max_length=80)
    country: str | None = Field(default=None, max_length=80)


app = FastAPI(title='MS5 — Analytics Gateway', version='1.0.0', root_path=PUBLIC_BASE_PATH,
              servers=[{'url': PUBLIC_BASE_PATH or '/'}])
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['GET', 'POST'], allow_headers=['*'])


@app.get('/health')
def health():
    return {'status': 'ok', 'service': 'ms5-analytics-gateway', 'athena_enabled': is_enabled()}


@app.get('/api/v1/analytics/status')
def status():
    cfg = settings()
    ready = is_enabled()
    return {'status': 'ready' if ready else 'disabled', 'service': 'ms5-analytics-gateway', 'athena_enabled': ready,
            'database': cfg['database'], 'workgroup': cfg['workgroup'],
            'missing_configuration': ([] if ready else ['ATHENA_ENABLED=true', 'ATHENA_OUTPUT_S3']),
            'note': 'Athena configurado; listo para consultas.' if ready else 'Configura ATHENA_ENABLED=true y ATHENA_OUTPUT_S3 para habilitar Athena.'}


@app.get('/api/v1/analytics/reports')
def reports():
    return {'reports': [{'id': key, 'title': value['title'], 'description': value['description']} for key, value in REPORTS.items()], 'views': list(VIEWS)}


@app.post('/api/v1/analytics/queries', status_code=202)
def start_query(request: QueryRequest):
    if request.report not in REPORTS:
        raise HTTPException(status_code=404, detail='Reporte analítico no encontrado')
    if not is_enabled():
        raise HTTPException(status_code=503, detail='Athena no está configurado')
    cfg = settings()
    try:
        result = client().start_query_execution(QueryString=REPORTS[request.report]['sql'].format(
            country_filter=country_filter(request.country, REPORT_COUNTRY_COLUMNS[request.report])),
            QueryExecutionContext={'Database': cfg['database'], 'Catalog': cfg['catalog']},
            ResultConfiguration={'OutputLocation': cfg['output']}, WorkGroup=cfg['workgroup'])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f'No se pudo iniciar la consulta Athena: {exc}') from exc
    return {'query_id': result['QueryExecutionId'], 'report': request.report, 'status': 'QUEUED'}


def valid_query_id(query_id: str):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', query_id):
        raise HTTPException(status_code=400, detail='query_id inválido')


@app.get('/api/v1/analytics/queries/{query_id}')
def query_status(query_id: str):
    valid_query_id(query_id)
    if not is_enabled():
        raise HTTPException(status_code=503, detail='Athena no está configurado')
    try:
        execution = client().get_query_execution(QueryExecutionId=query_id)['QueryExecution']
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f'No se pudo consultar Athena: {exc}') from exc
    status_data = execution['Status']
    return {'query_id': query_id, 'status': status_data['State'], 'reason': status_data.get('StateChangeReason'),
            'submitted_at': status_data.get('SubmissionDateTime'), 'completed_at': status_data.get('CompletionDateTime'),
            'statistics': execution.get('Statistics')}


@app.get('/api/v1/analytics/queries/{query_id}/results')
def query_results(query_id: str, next_token: str | None = None, max_results: int = Query(default=100, ge=1, le=1000)):
    valid_query_id(query_id)
    if not is_enabled():
        raise HTTPException(status_code=503, detail='Athena no está configurado')
    kwargs: dict[str, Any] = {'QueryExecutionId': query_id, 'MaxResults': max_results}
    if next_token:
        kwargs['NextToken'] = next_token
    try:
        result = client().get_query_results(**kwargs)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f'No se pudieron obtener resultados: {exc}') from exc
    columns = [x.get('Name') for x in result.get('ResultSet', {}).get('ResultSetMetadata', {}).get('ColumnInfo', [])]
    raw_rows = result.get('ResultSet', {}).get('Rows', [])
    rows = [[cell.get('VarCharValue') for cell in row.get('Data', [])] for row in raw_rows]
    if rows and columns and rows[0] == columns:
        rows = rows[1:]
    return {'query_id': query_id, 'columns': columns, 'rows': [dict(zip(columns, row)) for row in rows], 'next_token': result.get('NextToken')}


@app.post('/api/v1/analytics/views', status_code=202)
def create_views():
    if not is_enabled():
        raise HTTPException(status_code=503, detail='Athena no está configurado')
    cfg, queries = settings(), []
    try:
        for name, sql in VIEWS.items():
            result = client().start_query_execution(QueryString=sql, QueryExecutionContext={'Database': cfg['database'], 'Catalog': cfg['catalog']},
                ResultConfiguration={'OutputLocation': cfg['output']}, WorkGroup=cfg['workgroup'])
            queries.append({'view': name, 'query_id': result['QueryExecutionId']})
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f'No se pudieron crear las vistas: {exc}') from exc
    return {'status': 'QUEUED', 'views': queries}


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host=os.getenv('HOST', '127.0.0.1'), port=int(os.getenv('PORT', '8085')))
