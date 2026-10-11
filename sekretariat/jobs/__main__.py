"""Daily job (Cloud Scheduler 07:00 Europe/Warsaw → Cloud Run Job `jobs`).

    python -m sekretariat.jobs

Required: PROJECT_ID, BASE_URL, SMTP_HOST, SMTP_USER, SMTP_PASSWORD and
HOUSEHOLD_SECRET (or HOUSEHOLD_FILE locally). Optional: SMTP_PORT (default 465).
Exits with 1 when some reminders could not be sent; the next run retries them.
"""

import logging
import os
import sys

from sekretariat.config import ConfigError, load_household

REQUIRED = ("PROJECT_ID", "BASE_URL", "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD")


def main(environ: dict[str, str] | None = None) -> int:
    environ = os.environ if environ is None else environ
    missing = [name for name in REQUIRED if not environ.get(name)]
    if missing:
        raise ConfigError(f"missing environment variables: {', '.join(missing)}")

    from google.cloud import firestore

    from sekretariat import mailer
    from sekretariat.jobs.reminders import remind, today
    from sekretariat.store import FirestoreStore

    outcome = remind(
        FirestoreStore(firestore.Client(project=environ["PROJECT_ID"])),
        load_household(environ),
        mailer.from_environ(environ),
        environ["BASE_URL"].rstrip("/"),
        today(),
    )
    logging.info("reminders: %d sent, %d failed", outcome.sent, outcome.failed)
    return 1 if outcome.failed else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
