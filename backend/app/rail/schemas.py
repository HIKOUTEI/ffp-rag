"""`/rail` 的请求模型。

与 `app/schemas.py` 分开放，是为了让铁路模块保持自包含——它是同服务内的独立模块
（ADR-0007），与 RAG 问答没有共享模型。
"""
from typing import Optional

from pydantic import BaseModel


class JourneyCreate(BaseModel):
    train_number: str
    ride_date: str                        # YYYY-MM-DD
    from_seq: Optional[int] = None        # source='timetable' 时必填
    to_seq: Optional[int] = None
    from_station: Optional[str] = None    # source='manual' 时必填
    to_station: Optional[str] = None
    note: Optional[str] = None
    source: str = "timetable"


class JourneyUpdate(BaseModel):
    """只允许改这两项。改车次/站点等于换了一段经历，让用户删了重记更清楚。"""
    ride_date: Optional[str] = None
    note: Optional[str] = None
