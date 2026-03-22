from datetime import datetime
from math import radians, cos, sin, sqrt, atan2


def haversine(lat1, lon1, lat2, lon2):
    """
    Calculate the great-circle distance between two points on the Earth using the Haversine formula.
    Returns distance in kilometers.
    """
    R = 6371  # Earth radius in km
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    return R * c


def get_day_type(event_time):
    """
    Parse event_time and return 'weekday' or 'weekend'.
    If event_time is invalid or None, use today.
    """
    if event_time:
        try:
            dt = datetime.fromisoformat(event_time)
        except Exception:
            try:
                dt = datetime.strptime(event_time, '%Y-%m-%d %H:%M')
            except Exception:
                dt = datetime.now()
    else:
        dt = datetime.now()
    return 'weekend' if dt.weekday() >= 5 else 'weekday'


def parse_datetime(dt: str | None) -> datetime | None:
    if dt is None:
        return None
    try:
        return datetime.fromisoformat(dt)
    except Exception:
        return None

def to_epoch_seconds(dt):
    if hasattr(dt, 'timestamp'):
        return int(dt.timestamp())
    return int(dt)