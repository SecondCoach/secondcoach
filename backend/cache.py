import time

_cache = {}


def get_cache(key: str, ttl_seconds: int):
    item = _cache.get(key)

    if not item:
        return None

    value, ts = item

    if time.time() - ts > ttl_seconds:
        return None

    return value


def set_cache(key: str, value):
    _cache[key] = (value, time.time())