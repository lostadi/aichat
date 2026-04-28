import pytest

from .inference import (
    BackwardChainer,
    Fact,
    ForwardChainer,
    HeuristicOverlapScorer,
    InferenceRule,
    PremisePattern,
)


def _parent_matcher(subject: str | None = None, obj: str | None = None):
    def matcher(fact: Fact) -> bool:
        return (
            fact.tags.get("predicate") == "parent"
            and (subject is None or fact.tags.get("subject") == subject)
            and (obj is None or fact.tags.get("object") == obj)
        )

    return matcher


def _grandparent_rule():
    def validator(facts: list[Fact]) -> bool:
        return facts[0].tags.get("object") == facts[1].tags.get("subject")

    def conclusion(facts: list[Fact]) -> Fact:
        elder = facts[0].tags["subject"]
        youngster = facts[1].tags["object"]
        statement = f"{elder} is an ancestor of {youngster}"
        return Fact(
            statement=statement,
            tags={"predicate": "ancestor", "subject": elder, "object": youngster},
            confidence=min(f.confidence for f in facts),
        )

    return InferenceRule(
        name="grandparent",
        premises=[
            PremisePattern("first parent link", _parent_matcher()),
            PremisePattern("second parent link", _parent_matcher()),
        ],
        conclusion_builder=conclusion,
        weight=1.25,
        description="chain parents into an ancestor",
        validator=validator,
        conclusion_hint="ancestor inference",
    )


def _make_parent_fact(subject: str, obj: str, confidence: float) -> Fact:
    return Fact(
        statement=f"{subject} is parent of {obj}",
        tags={"predicate": "parent", "subject": subject, "object": obj},
        confidence=confidence,
    )


def test_forward_chaining_prioritizes_high_confidence_paths():
    scorer = HeuristicOverlapScorer()
    facts = [
        _make_parent_fact("alice", "bob", 0.9),
        _make_parent_fact("bob", "cara", 0.85),
        _make_parent_fact("alice", "dylan", 0.4),
    ]
    rules = [_grandparent_rule()]

    chainer = ForwardChainer(rules=rules, scorer=scorer, max_steps=3)
    derived, trace = chainer.run(facts)

    ancestor_statements = {f.statement for f in derived if f.tags.get("predicate") == "ancestor"}
    assert "alice is an ancestor of cara" in ancestor_statements
    assert all(step.priority > 0 for step in trace)
    # the strongest path should use the higher-confidence bob -> cara branch
    prioritized = trace[0]
    assert prioritized.supports[0].tags["object"] == "bob"
    assert prioritized.supports[1].tags["subject"] == "bob"


def test_backward_chaining_returns_proof_trace():
    scorer = HeuristicOverlapScorer()
    facts = [
        _make_parent_fact("alice", "bob", 0.9),
        _make_parent_fact("bob", "cara", 0.85),
    ]
    goal = "alice is an ancestor of cara"
    rules = [_grandparent_rule()]

    chainer = BackwardChainer(rules=rules, scorer=scorer, known_facts=facts, max_depth=3)
    trace = chainer.prove(goal)

    assert trace is not None
    assert any(step.derived.statement == goal for step in trace)
    # ensure cycle protection keeps recursion shallow
    assert len(trace) <= 3

