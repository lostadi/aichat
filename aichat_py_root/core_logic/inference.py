"""Lightweight inference engine with ML-aware scoring and transparent traces.

This module redesigns forward and backward chaining from first principles so every
derivation is prioritized, support-aware, and fully justified. The implementation
keeps a crisp separation of concerns: rules define structural intent, scorers
provide semantic strength, and chaining engines orchestrate search with explicit
proof steps. Wherever possible, a Hugging Face transformer powers the scoring
layer for robustness; a deterministic heuristic scorer is available for
environments without GPU access or where minimal dependencies are desired.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from heapq import heappop, heappush
from typing import Callable, Dict, Iterable, List, Optional, Protocol, Tuple


class SequenceScorer(Protocol):
    """Protocol for scoring how strongly one text supports another."""

    def score(self, premise: str, hypothesis: str) -> float:
        ...


class HeuristicOverlapScorer:
    """Token-overlap scorer that behaves deterministically and fast."""

    def score(self, premise: str, hypothesis: str) -> float:
        premise_tokens = set(premise.lower().split())
        hypothesis_tokens = set(hypothesis.lower().split())
        if not premise_tokens or not hypothesis_tokens:
            return 0.0
        overlap = premise_tokens & hypothesis_tokens
        return len(overlap) / max(len(premise_tokens), len(hypothesis_tokens))


class TransformerSimilarityScorer:
    """Semantic similarity scorer backed by a Hugging Face encoder model.

    The scorer attempts to load a lightweight sentence encoder and falls back
    to heuristic scoring if transformers or torch are unavailable. Embeddings
    are produced with mean pooling over the last hidden state, providing a
    stable cosine similarity that is resilient to noisy text.
    """

    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        device: Optional[str] = None,
    ) -> None:
        self._heuristic = HeuristicOverlapScorer()
        try:
            from transformers import AutoModel, AutoTokenizer  # type: ignore
            import torch  # type: ignore

            self._torch = torch
            self._tokenizer = AutoTokenizer.from_pretrained(model_name)
            self._model = AutoModel.from_pretrained(model_name)
            if device:
                self._model.to(device)
            self._model.eval()
        except Exception:
            # transformers is optional; fall back to a deterministic scorer
            self._torch = None
            self._tokenizer = None
            self._model = None

    def _encode(self, text: str):
        if self._model is None or self._tokenizer is None or self._torch is None:
            return None
        tokens = self._tokenizer(text, return_tensors="pt", truncation=True)
        with self._torch.no_grad():
            outputs = self._model(**tokens)
        hidden = outputs.last_hidden_state
        mask = tokens["attention_mask"].unsqueeze(-1)
        pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-8)
        return pooled[0]

    def score(self, premise: str, hypothesis: str) -> float:
        if self._model is None:
            return self._heuristic.score(premise, hypothesis)
        premise_vec = self._encode(premise)
        hypothesis_vec = self._encode(hypothesis)
        if premise_vec is None or hypothesis_vec is None:
            return self._heuristic.score(premise, hypothesis)
        denom = premise_vec.norm() * hypothesis_vec.norm()
        if denom == 0:
            return 0.0
        return float(self._torch.dot(premise_vec, hypothesis_vec) / denom)


@dataclass
class Justification:
    """Evidence for a derived fact."""

    rule: str
    supports: List[str]
    score: float


@dataclass
class Fact:
    """Atomic piece of knowledge tracked by the inference engines."""

    statement: str
    tags: Dict[str, str] = field(default_factory=dict)
    confidence: float = 1.0
    justification: Optional[Justification] = None


@dataclass
class PremisePattern:
    """Predicate describing which facts satisfy a rule premise."""

    description: str
    matcher: Callable[[Fact], bool]


@dataclass
class DerivationCandidate:
    """Potential fact produced by applying a rule to supporting facts."""

    fact: Fact
    supports: List[Fact]
    score: float
    rule_name: str


@dataclass
class ProofStep:
    """Detailed reasoning step for proof tracing."""

    rule: str
    derived: Fact
    supports: List[Fact]
    priority: float


class InferenceRule:
    """Declarative rule describing how to derive conclusions from premises."""

    def __init__(
        self,
        name: str,
        premises: List[PremisePattern],
        conclusion_builder: Callable[[List[Fact]], Fact],
        weight: float = 1.0,
        description: str = "",
        validator: Optional[Callable[[List[Fact]], bool]] = None,
        conclusion_hint: Optional[str] = None,
    ) -> None:
        self.name = name
        self.premises = premises
        self.conclusion_builder = conclusion_builder
        self.weight = weight
        self.description = description or name
        self.validator = validator
        self.conclusion_hint = conclusion_hint or description or name

    def generate_candidates(
        self, facts: List[Fact], scorer: SequenceScorer
    ) -> List[DerivationCandidate]:
        """Enumerate candidate derivations by pairing compatible facts."""

        if not self.premises:
            return []

        premise_matches: List[List[Tuple[float, Fact]]] = []
        for premise in self.premises:
            matches = []
            for fact in facts:
                if premise.matcher(fact):
                    matches.append((scorer.score(premise.description, fact.statement), fact))
            if not matches:
                return []
            # keep strongest few to limit combinatorial explosion
            matches.sort(key=lambda item: item[0], reverse=True)
            premise_matches.append(matches[:5])

        candidates: List[DerivationCandidate] = []
        for combo in itertools.product(*premise_matches):
            scores, combo_facts = zip(*combo)
            if self.validator and not self.validator(list(combo_facts)):
                continue
            confidence = float(sum(scores) / len(scores))
            derived_fact = self.conclusion_builder(list(combo_facts))
            derived_fact.confidence *= confidence * self.weight
            justification = Justification(
                rule=self.name,
                supports=[fact.statement for fact in combo_facts],
                score=derived_fact.confidence,
            )
            derived_fact.justification = justification
            candidates.append(
                DerivationCandidate(
                    fact=derived_fact,
                    supports=list(combo_facts),
                    score=derived_fact.confidence,
                    rule_name=self.name,
                )
            )
        return candidates


class ForwardChainer:
    """Priority-driven forward chaining with explicit justification tracking."""

    def __init__(
        self,
        rules: List[InferenceRule],
        scorer: SequenceScorer,
        max_steps: int = 50,
    ) -> None:
        self.rules = rules
        self.scorer = scorer
        self.max_steps = max_steps

    def run(self, initial_facts: Iterable[Fact]) -> Tuple[List[Fact], List[ProofStep]]:
        agenda: List[Tuple[float, int, DerivationCandidate]] = []
        known: Dict[str, Fact] = {fact.statement: fact for fact in initial_facts}
        trace: List[ProofStep] = []
        counter = 0

        def push_candidates(new_facts: List[Fact]):
            nonlocal counter
            for rule in self.rules:
                candidates = rule.generate_candidates(list(known.values()), self.scorer)
                for candidate in candidates:
                    if candidate.fact.statement in known:
                        continue
                    priority = -candidate.score
                    heappush(agenda, (priority, counter, candidate))
                    counter += 1

        push_candidates(list(known.values()))

        steps = 0
        while agenda and steps < self.max_steps:
            priority, _, candidate = heappop(agenda)
            if candidate.fact.statement in known:
                continue
            known[candidate.fact.statement] = candidate.fact
            trace.append(
                ProofStep(
                    rule=candidate.rule_name,
                    derived=candidate.fact,
                    supports=candidate.supports,
                    priority=-priority,
                )
            )
            steps += 1
            push_candidates([candidate.fact])

        return list(known.values()), trace


class BackwardChainer:
    """Support-aware backward chaining with cycle protection and proof traces."""

    def __init__(
        self,
        rules: List[InferenceRule],
        scorer: SequenceScorer,
        known_facts: Iterable[Fact],
        max_depth: int = 4,
    ) -> None:
        self.rules = rules
        self.scorer = scorer
        self.known = {fact.statement: fact for fact in known_facts}
        self.max_depth = max_depth

    def prove(self, goal: str) -> Optional[List[ProofStep]]:
        visited: set[str] = set()
        return self._prove(goal, depth=0, visited=visited)

    def _prove(
        self, goal: str, depth: int, visited: set[str]
    ) -> Optional[List[ProofStep]]:
        if goal in visited or depth > self.max_depth:
            return None
        if goal in self.known:
            fact = self.known[goal]
            return [ProofStep(rule="given", derived=fact, supports=[], priority=fact.confidence)]

        visited.add(goal)
        ranked_rules = sorted(
            self.rules,
            key=lambda rule: self._rule_priority(rule, goal),
            reverse=True,
        )

        for rule in ranked_rules:
            candidates = rule.generate_candidates(list(self.known.values()), self.scorer)
            for candidate in sorted(candidates, key=lambda c: c.score, reverse=True):
                proximity = self.scorer.score(candidate.fact.statement, goal)
                combined_priority = (candidate.score + proximity) / 2
                if proximity < 0.5:
                    continue
                sub_trace = [
                    ProofStep(
                        rule=candidate.rule_name,
                        derived=candidate.fact,
                        supports=candidate.supports,
                        priority=combined_priority,
                    )
                ]
                # ensure premises are justified or prove them recursively
                premises_resolved = True
                for support in candidate.supports:
                    if support.statement in self.known:
                        continue
                    proof = self._prove(support.statement, depth + 1, visited)
                    if proof is None:
                        premises_resolved = False
                        break
                    sub_trace = proof + sub_trace
                if premises_resolved:
                    self.known[candidate.fact.statement] = candidate.fact
                    return sub_trace
        return None

    def _rule_priority(self, rule: InferenceRule, goal: str) -> float:
        hint = rule.conclusion_hint or rule.description
        return rule.weight * self.scorer.score(hint, goal)

