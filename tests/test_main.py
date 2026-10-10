import pytest

from sekretariat.api.main import build
from sekretariat.config import ConfigError


def test_missing_environment_is_a_clear_error():
    with pytest.raises(ConfigError, match="PROJECT_ID.*SESSION_SECRET"):
        build({})


def test_missing_household_is_a_clear_error():
    environ = {
        name: "x"
        for name in (
            "PROJECT_ID",
            "LETTERS_BUCKET",
            "OCR_PROCESSOR",
            "TASKS_QUEUE",
            "BASE_URL",
            "TASKS_SERVICE_ACCOUNT",
            "GOOGLE_CLIENT_ID",
            "SESSION_SECRET",
        )
    }
    with pytest.raises(ConfigError, match="HOUSEHOLD_FILE"):
        build(environ)
