from fastapi import FastAPI
import uvicorn

app = FastAPI()

@app.get("/api/analytics/status")
def status():
    return {"status": "Ms5 esqueleto activo", "note": "Consultas Athena se agregan la próxima semana"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8085, reload=True)