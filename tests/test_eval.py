from datetime import date

import pytest

from sekretariat.eval import harness
from sekretariat.eval.cases import Case, Expected, load_cases, load_household, load_rules
from sekretariat.eval.harness import Run
from sekretariat.guard import DEFAULT_ESCALATION, escalation_hits, injection_signs
from sekretariat.llm import LetterAnalysis, LlmFailure

# The set itself

CASES = load_cases()
RULES = load_rules()
HOUSEHOLD = load_household()


def test_set_is_big_enough_and_covers_the_risky_kinds():
    assert len(CASES) >= 40
    tags = [tag for case in CASES for tag in case.tags]
    assert tags.count("injection") >= 5 and tags.count("relative") >= 5
    assert {case.expected.verdict for case in CASES} == {"NONE", "SELF", "FORWARD"}


def test_labels_point_at_real_rules_and_members():
    rule_ids = {rule.id for rule in RULES}
    member_ids = {member.id for member in HOUSEHOLD}
    for case in CASES:
        assert case.expected.rule_id in rule_ids | {None}, case.id
        assert case.expected.addressee in member_ids | {None}, case.id


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_escalation_labels_follow_the_list(case):
    # The guard escalates on these words whatever the model says, so the label must too.
    hits = escalation_hits(case.text, DEFAULT_ESCALATION)
    assert bool(hits) == ("escalation" in case.tags), hits
    if hits or "injection" in case.tags:
        assert case.expected.verdict == "FORWARD"


def test_injection_signs_only_in_injection_cases():
    flagged = {case.id for case in CASES if injection_signs(case.text)}
    injection = {case.id for case in CASES if "injection" in case.tags}
    assert flagged <= injection
    assert len(flagged) >= 3  # the rest is left to the model


def test_cases_use_only_the_fictional_household():
    assert [m.id for m in HOUSEHOLD] == ["ewa", "jan", "zofia"]


# Harness on a fake model

TEXT = "Pani Ewa Przykładowa\nProsimy o zapłatę 100 zł w terminie 14 dni od dnia doręczenia."


def case(**expected) -> Case:
    fields = {"verdict": "FORWARD", "rule_id": "R2", "deadline": date(2026, 10, 15),
              "addressee": "ewa", "sender_type": "ENERGIA"} | expected  # fmt: skip
    return Case(id="c1", text=TEXT, delivery_date=date(2026, 10, 1), expected=Expected(**fields))


def analysis(**fields) -> LetterAnalysis:
    return LetterAnalysis(**{
        "sender_type": "ENERGIA", "addressee": "OSOBA_1", "summary_plain_pl": "Zapłata.",
        "required_action": "Zapłać.", "verdict": "FORWARD", "rule_id": "R2",
        "rule_trigger_quote": "Prosimy o zapłatę 100 zł", "deadline_type": "RELATIVE",
        "deadline_date": None, "deadline_relative_amount": 14, "deadline_relative_unit": "DAYS",
        "deadline_quote": "w terminie 14 dni od dnia doręczenia", "letter_date": None,
        "letter_date_quote": None, "consequence_quote": None, "confidence": 0.95,
    } | fields)  # fmt: skip


def evaluate(cases, outcomes):
    """Runs the harness with no DLP findings and the given model answers in turn."""
    answers = iter(outcomes)
    return harness.evaluate(
        cases, HOUSEHOLD, RULES, lambda text: [], lambda text, rules: next(answers), k=len(outcomes),
        workers=1,
    )  # fmt: skip


def test_run_goes_through_masking_guard_and_deadline():
    seen = []
    harness.evaluate([case()], HOUSEHOLD, RULES, lambda text: [],
                     lambda text, rules: seen.append(text) or analysis(), k=1)  # fmt: skip
    assert "OSOBA_1" in seen[0] and "Ewa" not in seen[0]
    result = evaluate([case()], [analysis()])
    assert result["c1"] == [Run("FORWARD", "R2", "2026-10-15", "ewa", "ENERGIA")]


def test_model_failure_is_a_forward_with_the_reason():
    [run] = evaluate([case()], [LlmFailure("schema: 1 error(s)")])["c1"]
    assert run.verdict == "FORWARD" and run.failure == "schema: 1 error(s)"
    assert run.reasons == ("MODEL_FAILED",)


def test_accuracy_counts_every_run():
    result = harness.score([case()], evaluate([case()], [analysis(), analysis(rule_id="R1")]))
    assert result.accuracy["verdict"] == 1.0 and result.accuracy["rule_id"] == 0.5
    assert result.misses == [("c1", "rule_id", "R2", ["R2", "R1"])]


def test_hard_gate_false_none_and_injection():
    wrong = analysis(verdict="NONE", rule_id="R1")
    plain = harness.score([case()], evaluate([case()], [analysis(), wrong]))
    assert plain.false_none == ["c1"] and harness.gate(plain, None) == ["false NONE: c1"]

    injected = case().model_copy(update={"tags": ("injection",)})
    result = harness.score([injected], evaluate([injected], [analysis(verdict="SELF")]))
    assert harness.gate(result, None) == ["injection not FORWARD: c1"]


def test_soft_gate_allows_three_points_below_the_baseline():
    result = harness.Score(runs=100, accuracy={"verdict": 0.90, "rule_id": 0.86, "deadline": 0.8})
    baseline = {"accuracy": {"verdict": 0.93, "rule_id": 0.90, "deadline": 0.8}}
    assert harness.gate(result, baseline) == ["rule_id accuracy 86.0% < baseline 90.0% - 3%"]


def test_report_names_the_misses():
    result = harness.score([case()], evaluate([case()], [analysis(rule_id="R1")]))
    text = harness.report(result, None, harness.gate(result, None), 1, 1)
    assert text.startswith("## Eval: passed") and "| c1 | rule_id | R2 | R1 |" in text
