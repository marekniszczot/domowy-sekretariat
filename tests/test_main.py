import pytest

from sekretariat.api.main import REQUIRED, build
from sekretariat.config import ConfigError


def test_missing_environment_is_a_clear_error():
    with pytest.raises(ConfigError, match="PROJECT_ID.*SMTP_PASSWORD"):
        build({})


def test_missing_household_is_a_clear_error():
    environ = {name: "x" for name in REQUIRED}
    with pytest.raises(ConfigError, match="HOUSEHOLD_FILE"):
        build(environ)
