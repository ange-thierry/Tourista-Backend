import secrets
import string
from datetime import datetime, timezone as dt_timezone

from django.utils import timezone

_ALPHABET = string.ascii_uppercase + string.digits


def random_token(length: int) -> str:
    return ''.join(secrets.choice(_ALPHABET) for _ in range(length))


def make_id(prefix: str) -> str:
    """IDs in the same shape the frontend generated (`bk_<ms>_<RAND>`)."""
    return f'{prefix}_{int(timezone.now().timestamp() * 1000)}_{random_token(6)}'


def make_reference() -> str:
    """Human-readable booking/payment reference, e.g. `TR-20261008-4KQZ`."""
    return f'TR-{timezone.localdate():%Y%m%d}-{random_token(4)}'


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(dt_timezone.utc).isoformat().replace('+00:00', 'Z')


def money(value) -> float:
    return round(float(value), 2)
