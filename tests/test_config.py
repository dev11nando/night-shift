import pytest

from night_shift.config import ConfigError, SalaryTarget, bootstrap_config, load_profile
from night_shift.domain.enums import Level


def test_example_profile_is_valid(paths):
    bootstrap_config(paths.config_dir)
    profile = load_profile(paths.profile_file)

    assert profile.automation.enabled is False, "exemplo deve vir com automação desligada"
    assert profile.preferences.levels == [Level.PLENO, Level.JUNIOR]
    assert profile.preferences.salary[Level.PLENO].clt_min == 6000


def test_pj_min_defaults_to_clt_times_factor():
    assert SalaryTarget(clt_min=6000).effective_pj_min == 8700
    assert SalaryTarget(clt_min=6000, pj_min=9500).effective_pj_min == 9500


def test_bootstrap_never_overwrites(paths):
    paths.profile_file.write_text("name: Eu\nemail: eu@x.com\n", encoding="utf-8")

    created = bootstrap_config(paths.config_dir)

    assert paths.profile_file not in created
    assert load_profile(paths.profile_file).name == "Eu"
    assert {p.name for p in created} == {"companies.yaml", "cv_master.yaml"}


def test_missing_profile_has_actionable_error(paths):
    with pytest.raises(ConfigError, match="night-shift init"):
        load_profile(paths.profile_file)


def test_invalid_profile_reports_field(paths):
    paths.profile_file.write_text(
        "name: Eu\nemail: eu@x.com\nautomation: {auto_apply_min_score: 150}\n", encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="auto_apply_min_score"):
        load_profile(paths.profile_file)
