from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from ..auth import require_token
from ..core.errors import InvalidRequestError, ResourceNotFoundError
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
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidRequestError(
            code="INVALID_JSON",
            message="上传文件不是有效的 JSON",
        ) from exc
    return import_payload(db, payload, only_approved=only_approved)


@router.post("/cards/import-seed", response_model=ImportResult)
def import_seed(
    db: Session = Depends(get_db),
    _token: str = Depends(require_token),
):
    seed = Path(__file__).resolve().parents[2] / "seed_data" / "candidates_offline_v1.json"
    if not seed.is_file():
        raise ResourceNotFoundError(code="SEED_NOT_FOUND", message="示例卡片数据不存在")
    payload = json.loads(seed.read_text(encoding="utf-8"))
    return import_payload(db, payload, only_approved=True)
