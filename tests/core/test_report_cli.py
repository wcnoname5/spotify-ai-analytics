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
         "--end", "2026-07-12", "--period-type", "weekly", "--no-save"],
    )
    assert main() == 0
    assert capsys.readouterr().out.strip() == "# Weekly Roast"
