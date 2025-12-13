from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel

from src.dependencies import get_db
from src.models.naf_code import NafCode  # ✅ import direct

# ✅ REDIS CACHE
from src.utils.redis_manager import cache_result

router = APIRouter(prefix="/naf-codes", tags=["naf-codes"])


class NafCodeResponse(BaseModel):
    code: str
    label: str | None = None
    section: str | None = None
    division: str | None = None
    group: str | None = None
    class_field: str | None = None
    sector_suggested: str | None = None

    class Config:
        orm_mode = True


@router.get("/{code}", response_model=NafCodeResponse)
@cache_result(ttl=86400, key_prefix="naf_code")  # ✅ Cache 24h (données statiques)
def get_naf_code(code: str, db: Session = Depends(get_db)):
    """Retourne les informations NAF correspondant au code donné."""
    cleaned_code = code.strip().upper()

    naf = (
        db.query(NafCode)
        .filter(func.upper(func.trim(NafCode.code)) == cleaned_code)
        .first()
    )

    if not naf:
        raise HTTPException(status_code=404, detail="Code NAF non trouvé")

    return naf
