import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

load_dotenv(Path(__file__).with_name('.env'))
app = FastAPI(title='MS5 — Analytics Gateway', version='1.0.0')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['GET'])


@app.get('/health')
def health():
    return {'status': 'ok', 'service': 'ms5-analytics-gateway'}


@app.get('/api/analytics/status')
def status():
    return {
        'status': 'pending',
        'service': 'ms5-analytics-gateway',
        'athena_enabled': False,
        'note': 'API del Hito 1 disponible. Consultas analíticas pendientes de implementación.',
    }


if __name__ == '__main__':
    uvicorn.run(app, host=os.getenv('HOST', '127.0.0.1'), port=int(os.getenv('PORT', '8085')))
