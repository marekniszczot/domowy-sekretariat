"""Production wiring from environment variables (set by Terraform on Cloud Run).

    uvicorn sekretariat.api.main:app

Required: PROJECT_ID, LETTERS_BUCKET, OCR_PROCESSOR, TASKS_QUEUE, BASE_URL,
TASKS_SERVICE_ACCOUNT, GOOGLE_CLIENT_ID, SESSION_SECRET and HOUSEHOLD_SECRET (or
HOUSEHOLD_FILE locally). Optional: REGION (default europe-central2).
"""

import os

from fastapi import FastAPI

from sekretariat.config import ConfigError, load_household

REQUIRED = (
    "PROJECT_ID",
    "LETTERS_BUCKET",
    "OCR_PROCESSOR",
    "TASKS_QUEUE",
    "BASE_URL",
    "TASKS_SERVICE_ACCOUNT",
    "GOOGLE_CLIENT_ID",
    "SESSION_SECRET",
)


def build(environ: dict[str, str] | None = None) -> FastAPI:
    environ = os.environ if environ is None else environ
    missing = [name for name in REQUIRED if not environ.get(name)]
    if missing:
        raise ConfigError(f"missing environment variables: {', '.join(missing)}")

    from google import genai
    from google.cloud import dlp_v2, firestore, storage, tasks_v2

    from sekretariat import ocr
    from sekretariat.api.app import AppConfig, create_app
    from sekretariat.auth import Sessions, verify_google_token
    from sekretariat.blobs import GcsBlobs
    from sekretariat.letters import Letters
    from sekretariat.llm import analyze
    from sekretariat.mask import inspect
    from sekretariat.pipeline import Services, process
    from sekretariat.store import FirestoreStore
    from sekretariat.tasks import TaskQueue

    project = environ["PROJECT_ID"]
    region = environ.get("REGION", "europe-central2")
    household = load_household(environ)
    store = FirestoreStore(firestore.Client(project=project))
    blobs = GcsBlobs(storage.Client(project=project), environ["LETTERS_BUCKET"])
    ocr_client = ocr.client()
    dlp = dlp_v2.DlpServiceClient()
    gemini = genai.Client(vertexai=True, project=project, location=region)
    queue = TaskQueue(
        tasks_v2.CloudTasksClient(),
        environ["TASKS_QUEUE"],
        environ["BASE_URL"],
        environ["TASKS_SERVICE_ACCOUNT"],
    )
    services = Services(
        store=store,
        blobs=blobs,
        ocr=lambda pages: ocr.ocr_pages(ocr_client, environ["OCR_PROCESSOR"], pages),
        inspect=lambda text: inspect(dlp, project, region, text),
        analyze=lambda text, rules: analyze(gemini, text, rules),
        household=household,
    )
    return create_app(
        AppConfig(
            letters=Letters(store, blobs, queue.enqueue, household),
            household=household,
            sessions=Sessions(environ["SESSION_SECRET"]),
            google_client_id=environ["GOOGLE_CLIENT_ID"],
            verify_token=verify_google_token,
            tasks_audience=environ["BASE_URL"].rstrip("/"),
            tasks_service_account=environ["TASKS_SERVICE_ACCOUNT"],
            process=lambda letter_id, attempt: process(services, letter_id, attempt),
        )
    )


def __getattr__(name: str):
    # `uvicorn sekretariat.api.main:app` builds the app on first access, not on import.
    if name == "app":
        return build()
    raise AttributeError(name)
