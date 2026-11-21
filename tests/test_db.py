import pytest

from career_hub import db


@pytest.fixture
def con():
    return db.connect(":memory:")


def test_profile_and_summary(con):
    uid = db.ensure_default_user(con)
    db.set_profile(con, uid, name="Ada", headline="Backend dev")
    db.set_profile(con, uid, location="Remote")  # partial update keeps earlier fields
    p = db.get_profile(con, uid)
    assert p["name"] == "Ada" and p["location"] == "Remote"
    assert "Ada" in db.summary(con, uid)


def test_add_update_delete(con):
    uid = db.ensure_default_user(con)
    s = db.add_item(con, uid, "skills", name="Python", level="advanced", years=5)
    assert s["visibility"] == "private"
    s = db.update_item(con, uid, "skills", s["id"], level="expert")
    assert s["level"] == "expert"
    db.delete_item(con, uid, "skills", s["id"])
    assert db.list_items(con, uid, "skills") == []


def test_rejects_unknown_fields_and_bad_visibility(con):
    uid = db.ensure_default_user(con)
    with pytest.raises(ValueError):
        db.add_item(con, uid, "skills", name="x", bogus=1)
    with pytest.raises(ValueError):
        db.add_item(con, uid, "skills", name="x", visibility="secret")
    with pytest.raises(ValueError):
        db.list_items(con, uid, "users; DROP TABLE users")


def test_duplicate_contribution_url_rejected(con):
    uid = db.ensure_default_user(con)
    db.add_item(con, uid, "contributions", repo="a/b", url="https://x/1")
    with pytest.raises(ValueError):
        db.add_item(con, uid, "contributions", repo="a/b", url="https://x/1")


def test_users_are_isolated(con):
    a, _ = db.create_user(con, "a")
    b, tok_b = db.create_user(con, "b")
    item = db.add_item(con, a, "skills", name="Go")
    assert db.list_items(con, b, "skills") == []
    with pytest.raises(ValueError):
        db.get_item(con, b, "skills", item["id"])
    with pytest.raises(ValueError):
        db.delete_item(con, b, "skills", item["id"])
    assert db.user_for_token(con, tok_b) == b
    assert db.user_for_token(con, "wrong") is None
