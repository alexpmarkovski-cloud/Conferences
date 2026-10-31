"""Single source of truth for how conferences are ordered."""
from typing import Mapping, Tuple

from . import config, geo


def tier(conf: Mapping) -> int:
    return geo.classify(conf.get("city"), conf.get("state"), bool(conf.get("is_virtual")))[1]


def sort_key(conf: Mapping) -> Tuple[int, int, str]:
    """Location tier desc, category weight desc, start date asc."""
    return (
        -tier(conf),
        -config.CATEGORY_WEIGHT.get(conf.get("category", ""), 0),
        conf.get("start_date", "9999-12-31"),
    )
