from __future__ import annotations

from app import cli, indexer
from app.index_format import INDEX_FILE


def test_index_then_check(album, tmp_path, capsys):
    table = tmp_path / "bibs.csv"
    table.write_text("IMG_0002.jpg;31\n", encoding="utf-8")
    assert cli.main(["index", str(album), "--csv", str(table)]) == 0
    assert "written" in capsys.readouterr().out
    assert indexer.bibs_of(indexer.load(album)["photos"][1]) == ["31"]
    assert cli.main(["check", str(album)]) == 0
    assert "would accept" in capsys.readouterr().out


def test_check_reports_a_missing_or_broken_index(album, capsys):
    assert cli.main(["check", str(album)]) == 1
    (album / INDEX_FILE).write_text('{"photos": [], "revision": 0}', encoding="utf-8")
    assert cli.main(["check", str(album)]) == 1
    assert "schema_version" in capsys.readouterr().out
    (album / INDEX_FILE).write_text("{oops", encoding="utf-8")
    assert cli.main(["check", str(album)]) == 2
