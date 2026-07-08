from __future__ import annotations

from fastapi import APIRouter

from backend.services import natural_language_source_service


router = APIRouter(prefix="/api/natural-language", tags=["natural-language"])


@router.get("/sources")
def list_natural_language_sources() -> dict:
    return natural_language_source_service.list_source_files()


@router.get("/sources/{filename}")
def get_natural_language_source(filename: str) -> dict:
    return natural_language_source_service.read_source_file(filename)
