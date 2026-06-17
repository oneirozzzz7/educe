"""IterationState 单元测试"""
import time
from pathlib import Path
from educe.core.iteration_state import (
    Claim, FactStatus, IterationState, StateLog,
)


def test_claim_new():
    c = Claim.new("file app.py exists", FactStatus.OPEN)
    assert c.claim_id
    assert c.status == FactStatus.OPEN
    assert c.text == "file app.py exists"


def test_claim_idempotent_id():
    c1 = Claim.new("file app.py exists")
    c2 = Claim.new("file app.py exists")
    assert c1.claim_id == c2.claim_id


def test_claim_with_status():
    c = Claim.new("server responds 200", FactStatus.OPEN)
    c2 = c.with_status(FactStatus.VERIFIED, ("ev_001",))
    assert c2.status == FactStatus.VERIFIED
    assert "ev_001" in c2.evidence
    assert c2.claim_id == c.claim_id


def test_state_empty():
    s = IterationState(task_id="t1")
    assert s.convergence_metric() == 0.0
    assert s.verified() == []
    assert s.ruled_out() == []
    assert s.open_hyp() == []


def test_state_apply():
    s0 = IterationState(task_id="t1")
    c1 = Claim.new("app.py created", FactStatus.VERIFIED)
    s1 = s0.apply(c1)
    assert s1.revision == 1
    assert len(s1.verified()) == 1
    assert s1.convergence_metric() == 1.0
    # Original unchanged
    assert s0.revision == 0
    assert len(s0.claims) == 0


def test_state_convergence_mixed():
    s = IterationState(task_id="t1")
    s = s.apply(Claim.new("fact A", FactStatus.VERIFIED))
    s = s.apply(Claim.new("fact B", FactStatus.OPEN))
    s = s.apply(Claim.new("fact C", FactStatus.RULED_OUT))
    # 2 resolved out of 3
    assert abs(s.convergence_metric() - 2/3) < 0.01


def test_state_hash_stable():
    s = IterationState(task_id="t1")
    s = s.apply(Claim.new("X", FactStatus.VERIFIED))
    s = s.apply(Claim.new("Y", FactStatus.OPEN))
    h1 = s.state_hash()
    h2 = s.state_hash()
    assert h1 == h2


def test_state_hash_differs():
    s1 = IterationState(task_id="t1")
    s1 = s1.apply(Claim.new("X", FactStatus.OPEN))
    s2 = IterationState(task_id="t1")
    s2 = s2.apply(Claim.new("X", FactStatus.VERIFIED))
    assert s1.state_hash() != s2.state_hash()


def test_state_serialization():
    s = IterationState(task_id="t1")
    s = s.apply(Claim.new("server up", FactStatus.VERIFIED, ("ev1",)))
    d = s.to_dict()
    s2 = IterationState.from_dict(d)
    assert s2.task_id == "t1"
    assert len(s2.verified()) == 1
    assert s2.state_hash() == s.state_hash()


def test_state_log(tmp_path):
    log_path = tmp_path / "test_log.jsonl"
    log = StateLog(log_path)

    s0 = IterationState(task_id="t1")
    log.record(s0)
    s1 = s0.apply(Claim.new("step 1 done", FactStatus.VERIFIED))
    log.record(s1)
    s2 = s1.apply(Claim.new("step 2 done", FactStatus.VERIFIED))
    log.record(s2)

    curve = log.convergence_curve()
    assert curve == [0.0, 1.0, 1.0]

    diff = log.diff(0, 2)
    assert len(diff["newly_verified"]) == 2
    assert diff["convergence_delta"] == 1.0


def test_state_log_load(tmp_path):
    log_path = tmp_path / "persist.jsonl"
    log1 = StateLog(log_path)
    s = IterationState(task_id="t1")
    s = s.apply(Claim.new("fact", FactStatus.VERIFIED))
    log1.record(s)

    # Reload from disk
    log2 = StateLog(log_path)
    log2.load()
    assert log2.latest() is not None
    assert log2.latest().convergence_metric() == 1.0


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
