from fastapi import APIRouter

from app.api.v1.endpoints import analysis, auth, report, upload

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(upload.router)
api_router.include_router(analysis.router)
api_router.include_router(report.router)
