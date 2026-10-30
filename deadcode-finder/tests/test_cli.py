import json

from deadcode_finder.cli import main


def make_project(tmp_path):
    (tmp_path / "app.py").write_text(
        "import os\nimport sys\n\ndef dead():\n    pass\n\nprint(sys.argv)\n"
    )
    return tmp_path


def test_exit_codes(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(make_project(tmp_path))
    assert main(["."]) == 1
    assert main([".", "--exit-zero"]) == 0
    out = capsys.readouterr().out
    assert "unused-import" in out and "unused-function" in out


def test_clean_project_exits_zero(tmp_path, monkeypatch, capsys):
    (tmp_path / "ok.py").write_text("print('hi')\n")
    monkeypatch.chdir(tmp_path)
    assert main(["."]) == 0
    assert "No dead code" in capsys.readouterr().out


def test_json_output(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(make_project(tmp_path))
    main([".", "-f", "json"])
    data = json.loads(capsys.readouterr().out)
    assert data["total"] == 2
    assert data["by_kind"] == {"unused-import": 1, "unused-function": 1}


def test_html_report_file(tmp_path, monkeypatch):
    monkeypatch.chdir(make_project(tmp_path))
    main([".", "-f", "html", "-o", "report.html"])
    html = (tmp_path / "report.html").read_text()
    assert "<title>Dead Code Report</title>" in html and "unused import" in html


def test_github_annotations(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(make_project(tmp_path))
    main([".", "-f", "github"])
    assert "::warning file=" in capsys.readouterr().out


def test_fix_then_only_function_left(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(make_project(tmp_path))
    main([".", "--fix", "-f", "json"])
    data = json.loads(capsys.readouterr().out)
    assert data["by_kind"] == {"unused-function": 1}
    assert "import os" not in (tmp_path / "app.py").read_text()


def test_only_filter(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(make_project(tmp_path))
    main([".", "--only", "unused-function", "-f", "json"])
    assert json.loads(capsys.readouterr().out)["by_kind"] == {"unused-function": 1}


def test_pyproject_config(tmp_path, monkeypatch, capsys):
    make_project(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[tool.deadcode-finder]\nignore-names = ["dead"]\n')
    monkeypatch.chdir(tmp_path)
    main(["-f", "json"])
    assert json.loads(capsys.readouterr().out)["by_kind"] == {"unused-import": 1}


def test_missing_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["nope"]) == 2
