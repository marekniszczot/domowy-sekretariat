"""python -m sekretariat.eval [--k 3] [--only ID ...] [--report FILE] [--write-baseline]

Needs GCP_PROJECT. Locally also GCLOUD_CONFIGURATION (a token from that gcloud
configuration); in CI the credentials come from Workload Identity Federation.
Exit code 1 when the gate fails. With --only the soft gate is skipped, because a
subset is not comparable with the baseline.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from sekretariat.eval import harness
from sekretariat.eval.cases import load_cases, load_household, load_rules

REGION = "europe-central2"


def credentials(project: str):
    config = os.environ.get("GCLOUD_CONFIGURATION")
    if not config:
        return None  # Application Default Credentials
    import google.oauth2.credentials

    token = subprocess.run(
        ["gcloud", "auth", "print-access-token", f"--configuration={config}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return google.oauth2.credentials.Credentials(token, quota_project_id=project)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sekretariat.eval")
    parser.add_argument("--k", type=int, default=3, help="runs per case")
    parser.add_argument("--only", nargs="+", metavar="ID", help="run only these cases")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--report", type=Path, help="also write the markdown report here")
    parser.add_argument("--out", type=Path, help="write every run as JSON here")
    parser.add_argument("--write-baseline", action="store_true", help="save eval/baseline.json")
    args = parser.parse_args(argv)

    from google import genai
    from google.cloud import dlp_v2

    from sekretariat.llm import analyze
    from sekretariat.mask import inspect

    project = os.environ["GCP_PROJECT"]
    region = os.environ.get("REGION", REGION)
    creds = credentials(project)
    dlp = dlp_v2.DlpServiceClient(credentials=creds)
    gemini = genai.Client(vertexai=True, project=project, location=region, credentials=creds)

    cases = load_cases()
    if args.only:
        unknown = set(args.only) - {case.id for case in cases}
        if unknown:
            parser.error(f"unknown case ids: {', '.join(sorted(unknown))}")
        cases = [case for case in cases if case.id in args.only]

    results = harness.evaluate(
        cases,
        load_household(),
        load_rules(),
        inspect=lambda text: inspect(dlp, project, region, text),
        analyze=lambda text, rules: analyze(gemini, text, rules),
        k=args.k,
        workers=args.workers,
    )
    result = harness.score(cases, results)
    baseline = None if args.only else harness.load_baseline()
    problems = harness.gate(result, baseline)
    text = harness.report(result, baseline, problems, len(cases), args.k)
    print(text)
    if args.report:
        args.report.write_text(text, encoding="utf-8")
    if args.out:
        runs = {case_id: [run.__dict__ for run in runs] for case_id, runs in results.items()}
        args.out.write_text(json.dumps(runs, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.write_baseline:
        if args.only:
            parser.error("--write-baseline needs the whole set")
        data = harness.baseline_of(result, len(cases), args.k)
        harness.BASELINE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
