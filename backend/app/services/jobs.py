"""PostgreSQL-backed job queue (SELECT ... FOR UPDATE SKIP LOCKED) with bounded retries and dead-lettering."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import Job


def enqueue(
    db: Session,
    kind: str,
    payload: dict | None = None,
    *,
    run_after: datetime | None = None,
    dedupe_key: str | None = None,
    max_attempts: int = 5,
) -> Job:
    if dedupe_key:
        existing = db.execute(
            select(Job).where(Job.dedupe_key == dedupe_key, Job.status.in_(("queued", "running")))
        ).scalar_one_or_none()
        if existing:
            return existing
    job = Job(
        kind=kind,
        payload=payload or {},
        run_after=run_after or utcnow(),
        dedupe_key=dedupe_key,
        max_attempts=max_attempts,
        status="queued",
    )
    db.add(job)
    db.flush()
    return job


def claim(db: Session, worker_id: str, limit: int = 5) -> list[Job]:
    now = utcnow()
    jobs = (
        db.execute(
            select(Job)
            .where(Job.status == "queued", Job.run_after <= now)
            .order_by(Job.run_after)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )
    for j in jobs:
        j.status = "running"
        j.locked_by = worker_id
        j.locked_at = now
        j.attempts += 1
    db.commit()
    return list(jobs)


def backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(300, 5 * (2 ** (attempts - 1))))


def fail(db: Session, job: Job, error: str) -> None:
    job.last_error = error[:2000]
    job.locked_by = None
    if job.attempts >= job.max_attempts:
        job.status = "dead"
        job.finished_at = utcnow()
    else:
        job.status = "queued"
        job.run_after = utcnow() + backoff(job.attempts)
    db.commit()


def succeed(db: Session, job: Job) -> None:
    job.status = "succeeded"
    job.finished_at = utcnow()
    job.locked_by = None
    db.commit()


def requeue_stale(db: Session, older_than_s: int = 600) -> int:
    cutoff = utcnow() - timedelta(seconds=older_than_s)
    stale = db.execute(select(Job).where(Job.status == "running", Job.locked_at < cutoff)).scalars().all()
    for j in stale:
        j.status = "queued"
        j.locked_by = None
        j.last_error = (j.last_error + "\nrequeued after stale lock").strip()
    db.commit()
    return len(stale)
