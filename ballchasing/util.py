import logging
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from aiohttp.formdata import FormData

log = logging.getLogger(__name__)

GROUP_URL_RE = re.compile(r"^/group/(?P<id>[^/]+)")


def parse_group_id(value: str) -> str:
    """Accept either a bare group id or a ballchasing group URL.

    Lets callers paste a link straight out of the browser.
    """
    if not value.startswith(("http://", "https://")):
        return value

    match = GROUP_URL_RE.match(urlparse(value).path)
    if not match:
        raise ValueError(f"Not a ballchasing group URL: {value}")
    return match.group("id")


def parse_retry_after(value: str | None) -> float | None:
    """Parse a ``Retry-After`` header into seconds from now.

    Per RFC 9110 the value is either a number of seconds or an HTTP date.
    Returns None when absent or unparseable, so the caller can fall back to
    its own backoff.
    """
    if value is None:
        return None

    value = value.strip()
    if not value:
        return None

    try:
        return max(float(value), 0.0)
    except ValueError:
        pass

    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        log.debug(f"Could not parse Retry-After header: {value!r}")
        return None

    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max((when - datetime.now(UTC)).total_seconds(), 0.0)


def rfc3339(dt):
    if dt is None or isinstance(dt, str):
        return dt
    elif isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.isoformat().replace("+00:00", "Z")
    else:
        raise ValueError("Date must be either string or datetime")


def log_form_data(form_data: FormData):
    if not isinstance(form_data, FormData):
        log.debug("Not a FormData instance, cannot log form data")
        return

    for field in form_data._fields:
        type_options, _headers, value = field
        name = type_options.get("name", "unknown")

        if isinstance(value, bytes):
            # Show truncated preview or just size
            log.debug(f"{name}: <binary data, {len(value)} bytes>")
        elif hasattr(value, "read"):
            # File-like object
            log.debug(f"{name}: <file-like object>")
        else:
            log.debug(f"{name}: {value}")
