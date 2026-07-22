from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..auth import require_token
from ..db import get_db
from ..schemas import ImportResult
from ..services_cards import import_payload

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/cards/import", response_model=ImportResult)
async def import_cards(
    file: UploadFile = File(...),
    only_approved: bool = True,
    db: Session = Depends(get_db),
    _token: str = Depends(require_token),
):
    raw = await file.read()
    try:
        payload: Any = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=400, detail=f"invalid json: {e}") from e
    try:
        return import_payload(db, payload, only_approved=only_approved)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/cards/import-seed", response_model=ImportResult)
def import_seed(
    db: Session = Depends(get_db),
    _token: str = Depends(require_token),
):
    seed = Path(__file__).resolve().parents[2] / "seed_data" / "candidates_offline_v1.json"
    if not seed.is_file():
        raise HTTPException(status_code=404, detail=f"seed not found: {seed}")
    payload = json.loads(seed.read_text(encoding="utf-8"))
    return import_payload(db, payload, only_approved=True)
