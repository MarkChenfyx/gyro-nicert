from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api import data_api, natural_language_api, pool_api, research_api, run_api, strategy_api, task_api


app = FastAPI(title="gyro_nicert API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(FileNotFoundError)
async def not_found_handler(request: Request, exc: FileNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": {"type": "not_found", "message": str(exc)}})


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": {"type": "validation_error", "message": str(exc)}})


@app.exception_handler(Exception)
async def general_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"error": {"type": "server_error", "message": str(exc)}})


@app.get("/api/health", tags=["health"])
def health() -> dict:
    return {"ok": True, "service": "gyro_nicert"}


app.include_router(strategy_api.router)
app.include_router(research_api.router)
app.include_router(run_api.router)
app.include_router(pool_api.router)
app.include_router(task_api.router)
app.include_router(data_api.router)
app.include_router(natural_language_api.router)
