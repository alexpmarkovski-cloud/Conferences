"""Classify a conference location into a county and a ranking tier."""
from typing import Optional, Tuple

from . import config

SALT_LAKE_COUNTY = {
    "salt lake city", "slc", "west valley city", "west valley", "sandy", "west jordan",
    "south jordan", "draper", "murray", "taylorsville", "millcreek", "cottonwood heights",
    "holladay", "midvale", "riverton", "herriman", "bluffdale", "south salt lake",
    "kearns", "magna", "alta", "brighton", "white city", "copperton", "emigration canyon",
}
UTAH_COUNTY = {
    "provo", "orem", "lehi", "american fork", "pleasant grove", "lindon", "spanish fork",
    "springville", "saratoga springs", "eagle mountain", "highland", "alpine", "cedar hills",
    "payson", "santaquin", "mapleton", "salem", "vineyard", "elk ridge", "genola", "goshen",
}
UTAH_STATE_NAMES = {"ut", "utah"}


def _norm(value: Optional[str]) -> str:
    return (value or "").strip().lower().replace(".", "")


def county_for(city: Optional[str], state: Optional[str]) -> Optional[str]:
    """Return 'Salt Lake' or 'Utah' for cities in the two core counties, else None."""
    if _norm(state) not in UTAH_STATE_NAMES:
        return None
    c = _norm(city)
    if c in SALT_LAKE_COUNTY:
        return "Salt Lake"
    if c in UTAH_COUNTY:
        return "Utah"
    return None


def classify(city: Optional[str], state: Optional[str], is_virtual: bool) -> Tuple[Optional[str], int]:
    """Return (county, tier) for a location."""
    if _norm(state) in UTAH_STATE_NAMES and not is_virtual:
        county = county_for(city, state)
        return county, config.TIER_CORE if county else config.TIER_UTAH
    return None, config.TIER_OTHER
