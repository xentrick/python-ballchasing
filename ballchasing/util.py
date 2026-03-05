import logging
from datetime import datetime
from aiohttp.formdata import FormData

log = logging.getLogger(__name__)


def rfc3339(dt):
    if dt is None:
        return dt
    elif isinstance(dt, str):
        return dt
    elif isinstance(dt, datetime):
        return dt.isoformat()
    else:
        raise ValueError("Date must be either string or datetime")


def log_form_data(form_data: FormData):
    if not isinstance(form_data, FormData):
        log.debug("Not a FormData instance, cannot log form data")
        return

    for field in form_data._fields:
        type_options, headers, value = field
        name = type_options.get("name", "unknown")

        if isinstance(value, bytes):
            # Show truncated preview or just size
            log.debug(f"{name}: <binary data, {len(value)} bytes>")
        elif hasattr(value, "read"):
            # File-like object
            log.debug(f"{name}: <file-like object>")
        else:
            log.debug(f"{name}: {value}")
