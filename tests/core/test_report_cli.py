import sys

from spotify_core.report.__main__ import main


def test_cli_prints_report_to_stdout(monkeypatch, capsys):
    monkeypatch.setattr(
        "spotify_core.report.models.build_chat_model", lambda provider, model: "fake-model"
    )

    def fake_generate(**kw):
        assert kw["style"] == "roast"
        assert kw["period_type"] == "weekly"
        assert kw["model"] == "fake-model"
        return "# Weekly Roast"

    monkeypatch.setattr("spotify_core.report.agent.generate_report", fake_generate)
    monkeypatch.setattr(
        sys, "argv",
        ["report", "--style", "roast", "--start", "2026-07-06",
         "--end", "2026-07-12", "--period-type", "weekly"],
    )
    assert main() == 0
    assert capsys.readouterr().out.strip() == "# Weekly Roast"


def test_cli_db_arg_wins_over_settings(monkeypatch, capsys, tmp_path):
    """The caller owns the path; this process must not re-derive it from env."""
    monkeypatch.setattr(
        "spotify_core.report.models.build_chat_model", lambda provider, model: "fake-model"
    )
    seen = {}

    def fake_generate(**kw):
        seen["db_path"] = kw["db_path"]
        return "# Report"

    monkeypatch.setattr("spotify_core.report.agent.generate_report", fake_generate)
    explicit = tmp_path / "elsewhere" / "history.db"
    monkeypatch.setattr(
        sys, "argv",
        ["report", "--style", "roast", "--start", "2026-07-06",
         "--end", "2026-07-12", "--db", str(explicit)],
    )
    assert main() == 0
    assert seen["db_path"] == str(explicit)
