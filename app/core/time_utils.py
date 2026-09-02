"""
Timezone helper for API responses.

This app's convention is that every naive datetime it produces or stores
(Python `datetime.utcnow()`, Postgres `NOW()` on a `timestamp without time
zone` column) is UTC-valued, just not marked as such. FastAPI's default JSON
encoder calls a naive datetime's `.isoformat()` as-is, with no `Z`/offset
suffix -- so the browser's `new Date(...)` then parses those raw UTC
clock-face numbers as if they were already local time, silently shifting
every displayed timestamp by the viewer's UTC offset instead of correctly
converting it. Same failure mode already diagnosed once on the input side,
see app/api/scans.py's `dt_parsed.replace(tzinfo=timezone.utc)` comment.

Attach UTC explicitly before returning any datetime in an API response, so
the serialized string carries a real offset and the frontend can convert it
correctly.
"""
from datetime import datetime, timezone
from typing import Optional


def as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None or dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=timezone.utc)
