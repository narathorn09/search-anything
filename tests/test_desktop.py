"""Desktop app: data folder under the new name, moved from the earlier one."""

import sys

import pytest

from search_anything import desktop


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.delenv("SA_DATA_DIR", raising=False)
    monkeypatch.setattr(desktop.Path, "home", lambda: tmp_path)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    return tmp_path


def test_data_of_the_earlier_name_is_moved(home):
    new, old = desktop._data_dirs()
    old.mkdir(parents=True)
    (old / "search.db").write_text("notes and passwords")
    assert desktop.data_dir() == new
    assert (new / "search.db").read_text() == "notes and passwords"
    assert not old.exists()


def test_new_install_and_existing_new_folder(home):
    new, old = desktop._data_dirs()
    assert desktop.data_dir() == new and not new.exists()  # created later by main()
    new.mkdir(parents=True)
    old.mkdir(parents=True)  # both exist: never mix them, keep using the new one
    assert desktop.data_dir() == new and old.exists()


def test_names(home):
    new, old = desktop._data_dirs()
    if sys.platform.startswith("win"):
        assert (new.name, old.name) == ("CAHON", "SearchAnything")
    elif sys.platform == "darwin":
        assert (new.name, old.name) == ("CAHON", "Search Anything")
    else:
        assert (new.name, old.name) == ("cahon", "search-anything")
