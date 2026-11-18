"""Origin numeric missing marker; do not treat large finite measurements as missing."""
import math

ORIGIN_MISSING = -1.23456789e-300

def is_origin_missing(value):
    return value is None or (isinstance(value, float) and (math.isnan(value) or value == ORIGIN_MISSING))
