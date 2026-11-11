from pathlib import Path

from sprout.config import ENV


def test_every_setting_is_documented():
    readme = (Path(__file__).parents[1] / "README.md").read_text()
    for var in ENV:
        assert f"`{var}`" in readme, var
