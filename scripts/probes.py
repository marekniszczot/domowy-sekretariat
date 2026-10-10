"""Availability probes for the GCP services the pipeline depends on.

1. Which Gemini models answer in which Vertex AI location.
2. Which DLP infoTypes exist for Polish, and whether `inspect` finds a PESEL,
   IBAN, phone number and address in a synthetic letter.

Standard library only. The access token comes from an explicit gcloud
configuration, never from Application Default Credentials.

Usage:
    GCLOUD_CONFIGURATION=<config> python3 scripts/probes.py <project-id> [--model ID ...]
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

LOCATIONS = ["europe-central2", "europe-west4", "global"]
DLP_LOCATION = "europe-central2"
SKIP_MODEL_MARKERS = ("tts", "live", "audio", "image", "embedding")

# Synthetic text. The PESEL is the textbook example number with a valid checksum.
SAMPLE_LETTER = (
    "Wezwanie do zapłaty. Pan Jan Kowalski, PESEL 44051401359, "
    "zam. ul. Długa 5/7, 00-238 Warszawa, tel. +48 600 700 800. "
    "Prosimy o wpłatę 245,00 zł na rachunek PL61 1090 1014 0000 0712 1981 2874 "
    "w terminie 14 dni od dnia doręczenia."
)
EXPECTED_INFO_TYPES = [
    "POLAND_PESEL_NUMBER",
    "IBAN_CODE",
    "PHONE_NUMBER",
    "STREET_ADDRESS",
    "PERSON_NAME",
]


def access_token() -> str:
    config = os.environ.get("GCLOUD_CONFIGURATION")
    if not config:
        sys.exit("set GCLOUD_CONFIGURATION to the gcloud configuration of the project owner")
    return subprocess.run(
        ["gcloud", "auth", "print-access-token", f"--configuration={config}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class Client:
    def __init__(self, project: str, token: str):
        self.project = project
        self.token = token

    def call(self, method: str, url: str, body: dict | None = None) -> tuple[int, dict]:
        request = urllib.request.Request(
            url,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Authorization": f"Bearer {self.token}",
                "x-goog-user-project": self.project,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            try:
                return error.code, json.load(error)
            except json.JSONDecodeError:
                return error.code, {}


def vertex_host(location: str) -> str:
    if location == "global":
        return "https://aiplatform.googleapis.com"
    return f"https://{location}-aiplatform.googleapis.com"


def discover_models(client: Client) -> list[str]:
    status, body = client.call(
        "GET", f"{vertex_host('europe-central2')}/v1beta1/publishers/google/models?pageSize=200"
    )
    if status != 200:
        sys.exit(f"model list failed: {status} {body.get('error', {}).get('message')}")
    names = [m["name"].rsplit("/", 1)[-1] for m in body.get("publisherModels", [])]
    return sorted(
        n for n in names if n.startswith("gemini") and not any(s in n for s in SKIP_MODEL_MARKERS)
    )


def probe_gemini(client: Client, models: list[str]) -> list[dict]:
    results = []
    for model in models:
        for location in LOCATIONS:
            url = (
                f"{vertex_host(location)}/v1/projects/{client.project}/locations/{location}"
                f"/publishers/google/models/{model}:generateContent"
            )
            status, body = client.call(
                "POST",
                url,
                {
                    "contents": [
                        {"role": "user", "parts": [{"text": "Odpowiedz jednym słowem: OK"}]}
                    ],
                    "generationConfig": {"maxOutputTokens": 256},
                },
            )
            note = "" if status == 200 else body.get("error", {}).get("status", "")
            results.append({"model": model, "location": location, "status": status, "note": note})
    return results


def probe_dlp(client: Client) -> dict:
    base = f"https://dlp.googleapis.com/v2/projects/{client.project}/locations/{DLP_LOCATION}"

    status, body = client.call("GET", f"{base}/infoTypes?languageCode=pl")
    if status != 200:
        return {"error": f"infoTypes.list {status}: {body.get('error', {}).get('message')}"}
    available = {t["name"] for t in body.get("infoTypes", [])}
    polish = sorted(n for n in available if n.startswith("POLAND_"))

    status, body = client.call(
        "POST",
        f"{base}/content:inspect",
        {
            "item": {"value": SAMPLE_LETTER},
            "inspectConfig": {
                "infoTypes": [{"name": n} for n in EXPECTED_INFO_TYPES if n in available],
                "minLikelihood": "POSSIBLE",
                "includeQuote": True,
            },
        },
    )
    if status != 200:
        return {
            "polish": polish,
            "error": f"inspect {status}: {body.get('error', {}).get('message')}",
        }
    findings = {}
    for finding in body.get("result", {}).get("findings", []):
        name = finding["infoType"]["name"]
        findings.setdefault(name, []).append(f"{finding.get('quote')} ({finding['likelihood']})")

    return {
        "polish": polish,
        "expected": {
            n: ("available" if n in available else "missing") for n in EXPECTED_INFO_TYPES
        },
        "findings": findings,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    parser.add_argument("--model", action="append", default=[], help="extra model id to probe")
    args = parser.parse_args()

    client = Client(args.project, access_token())
    models = sorted(set(discover_models(client)) | set(args.model))

    print("## Gemini (Vertex AI)\n")
    print("| model | " + " | ".join(LOCATIONS) + " |")
    print("|---|" + "---|" * len(LOCATIONS))
    rows: dict[str, dict[str, str]] = {}
    for r in probe_gemini(client, models):
        cell = "OK" if r["status"] == 200 else f"{r['status']} {r['note']}".strip()
        rows.setdefault(r["model"], {})[r["location"]] = cell
    for model, cells in rows.items():
        print(f"| `{model}` | " + " | ".join(cells[loc] for loc in LOCATIONS) + " |")

    print(f"\n## DLP ({DLP_LOCATION}, languageCode=pl)\n")
    dlp = probe_dlp(client)
    if "error" in dlp:
        print(f"Error: {dlp['error']}")
    print("Polish infoTypes: " + ", ".join(f"`{n}`" for n in dlp.get("polish", [])))
    for name, state in dlp.get("expected", {}).items():
        found = dlp["findings"].get(name)
        print(f"- `{name}`: {state}; found in sample: {'; '.join(found) if found else 'no'}")


if __name__ == "__main__":
    main()
