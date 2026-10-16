"""Working-day calendars per jurisdiction (weekend days + seeded holidays) for SLAs and deadlines."""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Holiday, Jurisdiction


def _country(db: Session, jurisdiction_id: uuid.UUID | None) -> Jurisdiction | None:
    j = db.get(Jurisdiction, jurisdiction_id) if jurisdiction_id else None
    while j is not None and j.parent_id is not None and not j.weekend_days:
        j = db.get(Jurisdiction, j.parent_id)
    return j


def _holidays(db: Session, jurisdiction_id: uuid.UUID | None) -> set[date]:
    ids = []
    j = db.get(Jurisdiction, jurisdiction_id) if jurisdiction_id else None
    while j is not None:
        ids.append(j.id)
        j = db.get(Jurisdiction, j.parent_id) if j.parent_id else None
    if not ids:
        return set()
    return set(db.execute(select(Holiday.day).where(Holiday.jurisdiction_id.in_(ids))).scalars())


def is_working_day(db: Session, jurisdiction_id: uuid.UUID | None, d: date) -> bool:
    country = _country(db, jurisdiction_id)
    weekend = set(country.weekend_days) if country else {6, 7}
    return d.isoweekday() not in weekend and d not in _holidays(db, jurisdiction_id)


def add_working_days(db: Session, jurisdiction_id: uuid.UUID | None, start: datetime, days: int) -> datetime:
    """Deadline = end of the Nth working day (17:00 local time of the jurisdiction)."""
    country = _country(db, jurisdiction_id)
    weekend = set(country.weekend_days) if country else {6, 7}
    tzname = country.timezone if country else "UTC"
    holidays = _holidays(db, jurisdiction_id)
    local = start.astimezone(ZoneInfo(tzname)).date()
    remaining = days
    while remaining > 0:
        local += timedelta(days=1)
        if local.isoweekday() not in weekend and local not in holidays:
            remaining -= 1
    return datetime.combine(local, time(17, 0), tzinfo=ZoneInfo(tzname))


def working_days_between(db: Session, jurisdiction_id: uuid.UUID | None, a: datetime, b: datetime) -> int:
    country = _country(db, jurisdiction_id)
    weekend = set(country.weekend_days) if country else {6, 7}
    holidays = _holidays(db, jurisdiction_id)
    d, end, n = a.date(), b.date(), 0
    while d < end:
        d += timedelta(days=1)
        if d.isoweekday() not in weekend and d not in holidays:
            n += 1
    return n
