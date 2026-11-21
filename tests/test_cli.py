from typer.testing import CliRunner

from night_shift.cli import app

runner = CliRunner()


def test_help_lists_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("init", "doctor", "db", "version"):
        assert cmd in result.output


def test_init_creates_config_and_db(paths):
    result = runner.invoke(app, ["init"])

    assert result.exit_code == 0, result.output
    assert paths.profile_file.exists()
    assert paths.db_path.exists()
    assert "preencha" in result.output


def test_init_is_idempotent(paths):
    runner.invoke(app, ["init"])
    paths.profile_file.write_text("name: Eu\nemail: eu@x.com\n", encoding="utf-8")

    result = runner.invoke(app, ["init"])

    assert result.exit_code == 0, result.output
    assert "Eu" in paths.profile_file.read_text(encoding="utf-8")


def test_doctor_fails_before_init_and_passes_after(paths):
    assert runner.invoke(app, ["doctor"]).exit_code == 1
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
