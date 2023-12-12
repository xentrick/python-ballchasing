from datetime import datetime
from pathlib import Path
from ballchasing import models

def rfc3339(dt):
    if dt is None:
        return dt
    elif isinstance(dt, str):
        return dt
    elif isinstance(dt, datetime):
        return dt.isoformat("T") + "Z"
    else:
        raise ValueError("Date must be either string or datetime")
