from conferences import config, geo, ranking


def test_core_counties():
    assert geo.classify("Lehi", "UT", False) == ("Utah", config.TIER_CORE)
    assert geo.classify("Salt Lake City", "Utah", False) == ("Salt Lake", config.TIER_CORE)
    assert geo.classify("St. George", "UT", False) == (None, config.TIER_UTAH)
    assert geo.classify("Austin", "TX", False) == (None, config.TIER_OTHER)
    assert geo.classify("Provo", "UT", True) == (None, config.TIER_OTHER)


def test_sort_order_location_then_category_then_date():
    confs = [
        {"name": "us-ai", "category": "ai", "start_date": "2027-01-01", "city": "Austin", "state": "TX"},
        {"name": "slc-fin", "category": "finance", "start_date": "2027-01-01", "city": "Sandy", "state": "UT"},
        {"name": "slc-ai-late", "category": "ai", "start_date": "2027-06-01", "city": "Provo", "state": "UT"},
        {"name": "slc-ai-early", "category": "ai", "start_date": "2027-02-01", "city": "Draper", "state": "UT"},
        {"name": "ogden-tech", "category": "tech", "start_date": "2027-01-01", "city": "Ogden", "state": "UT"},
    ]
    order = [c["name"] for c in sorted(confs, key=ranking.sort_key)]
    assert order == ["slc-ai-early", "slc-ai-late", "slc-fin", "ogden-tech", "us-ai"]
