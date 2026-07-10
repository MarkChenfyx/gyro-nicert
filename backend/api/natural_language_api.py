from __future__ import annotations

from fastapi import APIRouter

from backend.api.schemas import NaturalLanguageSourceCreateRequest, NaturalLanguageSourceUpdateRequest
from backend.services import natural_language_source_service


router = APIRouter(prefix="/api/natural-language", tags=["natural-language"])


@router.get("/sources")
def list_natural_language_sources() -> dict:
    return natural_language_source_service.list_source_files()


@router.get("/sources/{filename}")
def get_natural_language_source(filename: str) -> dict:
    return natural_language_source_service.read_source_file(filename)


@router.post("/sources")
def create_natural_language_source(request: NaturalLanguageSourceCreateRequest) -> dict:
    return natural_language_source_service.create_source_file(filename=request.filename, text=request.text)


@router.put("/sources/{filename}")
def update_natural_language_source(filename: str, request: NaturalLanguageSourceUpdateRequest) -> dict:
    return natural_language_source_service.update_source_file(filename=filename, text=request.text)
