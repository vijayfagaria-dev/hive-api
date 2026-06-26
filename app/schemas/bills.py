"""Bill contracts."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class BillBody(BaseModel):
    type: str
    total: int = Field(ge=0)
    month: str = Field(min_length=1)  # 'YYYY-MM'
    paidBy: Optional[int] = None
