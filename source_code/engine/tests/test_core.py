import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SLVD_DATA_DIR", "/tmp/slvd-test")
os.environ.setdefault("SLVD_SIMULATION", "1")

import pytest  # noqa: E402

from engine import store  # noqa: E402
from engine.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    import shutil
    d = "/tmp/slvd-test"
    if os.path.exists(d):
        shutil.rmtree(d)
    os.makedirs(d, exist_ok=True)
    store.reset_for_tests()
    store.init_db()
    yield
    store.reset_for_tests()


def test_policy_threshold_boundary():
    from engine.policy import evaluate
    assert evaluate(settings.approval_threshold_usd, "clear").approval_required is True
    assert evaluate(settings.approval_threshold_usd - 1, "clear").approval_required is False
    assert evaluate(settings.approval_threshold_usd - 1, "pending").approval_required is True
    assert evaluate(1_000_000, "PENDING").approval_required is True
    assert evaluate(1_000_000, "clear").approval_required is False
    # OR-rule: amount OR kyc
    r = evaluate(5_000_000, "pending")
    assert r.approval_required and len(r.reasons) == 2


def test_policy_audit_line():
    from engine.policy import evaluate, policy_audit_line
    assert "approval required" in policy_audit_line(evaluate(9_000_000, "clear"))
    assert "no approval required" in policy_audit_line(evaluate(1_000_000, "clear"))


def test_jwt_roundtrip_and_expiry():
    import jwt as pyjwt
    import time
    from engine.security import Identity, issue_token, verify_token
    ident = Identity("nick", "Nick Johnson", "Risk Analyst", "E102938")
    tok = issue_token(ident)
    back = verify_token(tok)
    assert back is not None and back.user_id == "nick" and back.employee_id == "E102938"
    # tampered
    assert verify_token(tok + "x") is None
    # expired
    payload = pyjwt.decode(tok, settings.jwt_secret, algorithms=["HS256"])
    payload["exp"] = int(time.time()) - 10
    bad = pyjwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    assert verify_token(bad) is None


def test_authenticate():
    from engine.security import authenticate
    assert authenticate("nick", "analyst123") is not None
    assert authenticate("nick", "wrong") is None
    assert authenticate("ghost", "x") is None


def test_hmac_link_single_use_semantics():
    import time
    from engine.security import build_approval_link, verify_approval_link
    exp = int(time.time()) + 3600
    link = build_approval_link("req-1", "approve", 8, exp)
    # parse sig
    sig = link.split("sig=")[1]
    assert verify_approval_link("req-1", "approve", 8, exp, sig) is True
    # wrong decision
    sig2 = link.split("sig=")[1]
    assert verify_approval_link("req-1", "reject", 8, exp, sig2) is False
    # expired
    assert verify_approval_link("req-1", "approve", 8, int(time.time()) - 1, sig) is False
    # tampered
    assert verify_approval_link("req-1", "approve", 8, exp, "deadbeef") is False


def test_run_lifecycle_and_steps():
    run_id = store.create_run("CR-2026-00451", "Nick Johnson", "E102938", 5_000_000)
    assert run_id.startswith("RUN-")
    snap = store.snapshot(run_id)
    assert len(snap["steps"]) == 10
    assert snap["run"]["status"] == "PENDING"
    store.set_run_status(run_id, "RUNNING")
    store.set_step(run_id, 1, "done")
    store.set_step(run_id, 2, "done")
    store.set_step(run_id, 3, "active")
    snap = store.snapshot(run_id)
    states = {s["seq"]: s["state"] for s in snap["steps"]}
    assert states[1] == "done" and states[2] == "done" and states[3] == "active"
    assert states[4] == "pending"


def test_audit_append_only_and_order():
    run_id = store.create_run("CR-2026-00451", "Nick Johnson", "E102938", 5_000_000)
    store.add_audit(run_id, "system", "Identity validated", "Nick Johnson")
    store.add_audit(run_id, "system", "Case resolved", "CR-2026-00451")
    audit = store.get_audit(run_id)
    assert [a["action"] for a in audit] == ["Identity validated", "Case resolved"]
    assert audit[0]["ts"] <= audit[1]["ts"]
    # append-only: no update/delete API exists
    assert not hasattr(store, "update_audit") and not hasattr(store, "delete_audit")


def test_active_run_for_case():
    r1 = store.create_run("CR-2026-00451", "Nick", "E1", 5_000_000)
    store.set_run_status(r1, "RUNNING")
    assert store.active_run_for_case("CR-2026-00451")["run_id"] == r1
    store.set_run_status(r1, "COMPLETED")
    assert store.active_run_for_case("CR-2026-00451") is None


def test_approval_request_single_use():
    run_id = store.create_run("CR-2026-00451", "Nick", "E1", 5_000_000)
    req_id = store.create_approval_request(run_id, 24)
    assert store.record_decision(req_id, "approve", 8, "Sarah") == "recorded"
    assert store.record_decision(req_id, "reject", 24, "Nick") == "already_recorded"
    req = store.get_approval_request(req_id)
    assert req["status"] == "approved" and req["decision"] == "approve"
    assert store.record_decision("nope", "approve", 8, "x") == "not_found"


def _load_case(cid: str) -> dict:
    import json
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(root, "mockdata", "cases.json")) as f:
        return json.load(f)["cases"][cid]


def test_memo_stub_and_validator():
    from engine.memo import build_stub_memo, validate_memo
    case = _load_case("CR-2026-00451")
    memo = build_stub_memo(case, 5_000_000)
    check = validate_memo(memo, case, 5_000_000)
    assert check.ok, check.missing
    # mutation: strip a required value
    bad = memo.replace("$3,800,000", "$1,111,111")
    assert not validate_memo(bad, case, 5_000_000).ok
    # mutation: remove client code
    bad2 = memo.replace("CL-77821", "CL-XXXXX")
    assert not validate_memo(bad2, case, 5_000_000).ok


def test_memo_validator_missing_decision_section():
    from engine.memo import validate_memo
    case = _load_case("CR-2026-00451")
    memo = ("# Loan Renewal Decision Memo\nClient: Acme Industrial Holdings (CL-77821) — "
            "Renewal Request\n## Overview\n- Requested renewal amount: $5,000,000\n"
            "- Current utilization: $3,800,000 (76% of limit)\n- Facility type: Revolving credit\n"
            "- Risk rating: BB\n- Status: In compliance with covenants\n"
            "## Key Considerations\n1. a\n2. b\n3. c\n")
    check = validate_memo(memo, case, 5_000_000)
    assert not check.ok and "recommended decision" in check.missing
