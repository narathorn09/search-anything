import time
from pathlib import Path

import pytest

from search_anything import db as db_mod
from search_anything.db import Database
from search_anything.indexer import Indexer


@pytest.fixture
def big(tmp_path: Path, monkeypatch) -> Database:
    # Small caps so a few hundred files behave like a huge index.
    monkeypatch.setattr(db_mod, "CANDIDATES", 7)
    monkeypatch.setattr(db_mod, "NAME_CAP", 5)
    root = tmp_path / "big"
    for d in range(4):
        (root / f"dir{d}").mkdir(parents=True)
        for i in range(60):
            p = root / f"dir{d}" / (f"wombat-{d}-{i}.txt" if i % 10 == 0 else f"f{d}-{i}.txt")
            p.write_text(f"common wombat text {d} {i}")
            import os
            os.utime(p, (1_000_000 + d * 100 + i, 1_000_000 + d * 100 + i))
    db = Database(tmp_path / "t.db")
    Indexer(db, [str(root)]).run()
    db.add_item("note", "wombat note", "about wombat")
    return db


def scroll_all(db, q, sort="relevance", kind=None, size=17):
    seen, offset = [], 0
    while True:
        page = db.page(q, kind, sort, offset, size)
        seen += [r["id"] for r in page["results"]]
        offset += size
        if not page["has_more"]:
            return seen, page


def test_first_page_is_fast_path_and_total_comes_later(big):
    first = big.page("wombat", None, "relevance", 0, 10)
    assert first["total"] is None and first["has_more"]  # too many to know at once
    assert big.count("wombat") == {"total": 241, "approx": False}


def test_scrolling_returns_every_match_once_in_a_stable_order(big):
    ids, last = scroll_all(big, "wombat")
    assert len(ids) == len(set(ids)) == 241  # no repeats, nothing missing
    assert last["total"] == 241
    # The first page shown before counting is exactly the start of the full list.
    first = [r["id"] for r in big.page("wombat", None, "relevance", 0, 17)["results"]]
    assert ids[:17] == first
    # The first page lists name matches before content-only matches.
    titles = [big.get_item(i)["title"] for i in ids[:17]]
    assert all("wombat" in t for t in titles)


def test_scrolling_with_other_sorts_and_filters(big):
    ids, _ = scroll_all(big, "wombat", sort="name")
    titles = [big.get_item(i)["title"] for i in ids]
    assert titles == sorted(titles, key=str.casefold) and len(ids) == 241
    files, page = scroll_all(big, "wombat", kind="file")
    assert len(files) == 240 and page["total"] == 240
    notes, page = scroll_all(big, "wombat", kind="note")
    assert len(notes) == 1 and page["total"] == 1


def test_small_result_sets_have_an_exact_total_immediately(big):
    page = big.page("f2-33", None, "relevance", 0, 50)
    assert page["total"] == 1 and page["has_more"] is False


def test_recent_list_pages_and_total(big):
    ids, page = scroll_all(big, "")
    assert page["total"] == 241 and len(ids) == len(set(ids)) == 241
    by_name, _ = scroll_all(big, "", sort="name")
    assert len(by_name) == 241


def test_count_is_cut_short_instead_of_hanging(big, monkeypatch):
    monkeypatch.setattr(db_mod, "SNAPSHOT_DEADLINE", 0.0)  # no time at all
    big.invalidate()
    res = big.count("text")
    assert res["approx"] is True and res["total"] < 241


def test_newer_count_cancels_older_one(big):
    big.invalidate()
    calls = []
    shard = big.shards[0]
    real = shard.all_matches

    def slow(long_terms, short_terms, should_stop):
        big._snap_gen += 1  # a newer search started meanwhile
        calls.append(should_stop())
        return real(long_terms, short_terms, should_stop)

    shard.all_matches = slow
    res = big.count("text")
    assert calls and calls[0] is True and res["approx"] is True
    assert big._snap_get(big._snap_key("text", None, "relevance")) is None  # not cached


def test_cache_is_dropped_when_data_changes(big):
    assert big.count("wombat")["total"] == 241
    big.add_item("note", "another wombat", "")
    big.invalidate()
    assert big.count("wombat")["total"] == 242
