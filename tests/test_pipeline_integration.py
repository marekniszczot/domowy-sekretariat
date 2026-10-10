"""End-to-end pipeline on real services with a synthetic letter rendered to an image.

Run: GCLOUD_CONFIGURATION=<config> GCP_PROJECT=<project> uv run pytest -m integration
"""

import io
import os
import subprocess
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

FONTS = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
LETTER_LINES = [
    "Telekom Przykładowy S.A.",
    "Warszawa, 2 października 2026 r.",
    "",
    "Szanowny Pan",
    "Jan Testowy",
    "",
    "Wezwanie do zapłaty",
    "Prosimy o zapłatę kwoty 89,00 zł za usługi telefoniczne",
    "w terminie 14 dni od dnia doręczenia niniejszego pisma.",
    "Brak wpłaty spowoduje zawieszenie usług.",
    "",
    "Z poważaniem,",
    "Dział Rozliczeń",
]


def render_letter() -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    font_path = next((f for f in FONTS if Path(f).exists()), None)
    if font_path is None:
        pytest.skip("no font with Polish glyphs")
    font = ImageFont.truetype(font_path, 34)
    image = Image.new("RGB", (1400, 1000), "white")
    draw = ImageDraw.Draw(image)
    for number, line in enumerate(LETTER_LINES):
        draw.text((80, 60 + number * 64), line, fill="black", font=font)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture(scope="module")
def gcp():
    import google.oauth2.credentials

    config = os.environ["GCLOUD_CONFIGURATION"]
    project = os.environ["GCP_PROJECT"]
    token = subprocess.run(
        ["gcloud", "auth", "print-access-token", f"--configuration={config}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    credentials = google.oauth2.credentials.Credentials(token, quota_project_id=project)
    return project, credentials


def test_pipeline_on_real_services(gcp):
    from google import genai
    from google.cloud import dlp_v2, firestore, storage

    from sekretariat import ocr
    from sekretariat.blobs import GcsBlobs
    from sekretariat.household import Member, Role
    from sekretariat.llm import analyze
    from sekretariat.mask import inspect
    from sekretariat.pipeline import Services, process
    from sekretariat.store import FirestoreStore

    project, credentials = gcp
    db = firestore.Client(project=project, credentials=credentials)
    store = FirestoreStore(db, prefix="test_")
    blobs = GcsBlobs(storage.Client(project=project, credentials=credentials), f"{project}-letters")
    db.collection("test_rules").document("R1").set(
        {"text": "Rachunki za telefon do 300 zł opłaca OSOBA_1."}
    )
    household = [
        Member("dom1", Role.DOMOWNIK, ("Jan", "Jana"), ("Testowy",), ("j@example.com",)),
        Member("koord", Role.KOORDYNATOR, ("Piotr",), (), ("p@example.com",)),
    ]
    ocr_client = ocr.client(credentials=credentials)
    processor = next(
        p.name
        for p in ocr_client.list_processors(parent=f"projects/{project}/locations/eu")
        if p.display_name == "ocr"
    )
    dlp = dlp_v2.DlpServiceClient(credentials=credentials)
    gemini = genai.Client(
        vertexai=True, project=project, location="europe-central2", credentials=credentials
    )
    services = Services(
        store=store,
        blobs=blobs,
        ocr=lambda pages: ocr.ocr_pages(ocr_client, processor, pages),
        inspect=lambda text: inspect(dlp, project, "europe-central2", text),
        analyze=lambda text, rules: analyze(gemini, text, rules),
        household=household,
    )

    path = f"test/{uuid.uuid4().hex}/p1.png"
    blobs.put(path, render_letter(), "image/png")
    letter_id = store.create_letter(
        {
            "status": "received",
            "uploaded_by": "koord",
            "delivery_date": "2026-10-09",
            "upload_private": False,
            "pages": [{"path": path, "mime": "image/png"}],
        }
    )
    try:
        assert process(services, letter_id) == "verdict"
        letter = store.get_letter(letter_id)
        assert "Testowy" not in letter["masked_text"]
        assert "OSOBA_1" in letter["masked_text"]
        assert letter["addressee"] == "dom1"
        assert letter["verdict"] in {"SELF", "FORWARD"}
        assert letter["deadline"]["basis"] == "DELIVERY"
        assert letter["deadline"]["date"] == "2026-10-23"
        assert store.events(letter_id)[0]["cause"] == "INITIAL"
    finally:
        for event in (
            db.collection("test_letters").document(letter_id).collection("events").stream()
        ):
            event.reference.delete()
        db.collection("test_letters").document(letter_id).delete()
        db.collection("test_rules").document("R1").delete()
        blobs._bucket.blob(path).delete()
