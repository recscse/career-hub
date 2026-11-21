from career_hub import matching


def _cmp(matched, missing):
    return {"matched": [{"skill": m} for m in matched], "missing": missing}


def test_single_match_cannot_reach_100():
    f, _ = matching.fit("Backend Engineer", _cmp(["git"], []))
    assert f < 100


def test_sales_ranks_below_engineer():
    sales, _ = matching.fit("Commercial Account Executive", _cmp(["git"], []))
    eng, _ = matching.fit("Backend Engineer", _cmp(["python", "go"], ["ruby"]))
    assert eng > sales


def test_management_penalised_unless_allowed():
    c = _cmp(["python", "sql"], [])
    assert matching.fit("Director, Data Science", c)[0] < matching.fit("Director, Data Science", c, allow_management=True)[0]
