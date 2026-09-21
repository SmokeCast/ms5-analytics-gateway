# MS5 — Analytics Gateway

API FastAPI del Hito 1. Puerto predeterminado: 8085.

## Ejecución local

Python 3.11 es la versión de referencia. Desde esta carpeta:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp env.example .env
# Editar .env con la configuración local.
python main.py
```

En Windows, activar con `.venv\Scripts\activate`.
Los paquetes de `requirements.txt` corresponden únicamente a la API.
Swagger UI está disponible en `/docs` y el contrato en `/openapi.json`.

## Endpoints y alcance

- `GET /health`: estado de la API.
- `GET /api/analytics/status`: informa `status: pending` y `athena_enabled: false`.

No requiere bases, credenciales AWS ni boto3 para arrancar. Las consultas Athena
están pendientes y no se sustituyen por resultados ficticios.
Configurar `HOST` y `PORT` en `.env` si es necesario.
Para desarrollo: `python -m uvicorn main:app --reload --port 8085`.
