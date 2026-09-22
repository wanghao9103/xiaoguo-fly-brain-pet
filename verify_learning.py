"""Offline deterministic evidence for learning, reversal, and JSON persistence.

Run: python verify_learning.py
Prints measured JSON to stdout and never opens or writes a pet save file.
"""

from __future__ import annotations

import json

from brain import ACTIONS, FlyBrain


def context(*base_values: float) -> list[float]:
    if len(base_values) != 12:
        raise ValueError("expected 12 base features")
    return [value for base in base_values for value in (base, 1 - base)]


def run_verification() -> dict:
    brain = FlyBrain(seed=42)
    # Tired/satiated/calm versus lively/hungry/curious. Both obey paired encoding.
    tired = context(.08, .90, .20, .10, .10, .95, .85, .05, .85, .90, .10, .95)
    lively = context(.95, .10, .90, .95, .90, .15, .10, .90, .05, .05, .90, .20)
    observed = {"tired": tired, "lively": lively}

    def snapshot() -> dict:
        return {name: dict(zip(ACTIONS, brain.probabilities(features)))
                for name, features in observed.items()}

    stages = [{"name": "before_learning", "probabilities": snapshot(), "updates": brain.updates}]
    for _ in range(70):
        for action in ACTIONS:
            brain.learn(tired, action, 1 if action == "rest" else -0.6, source="user")
            brain.learn(lively, action, 1 if action == "play" else -0.6, source="user")
    learned = snapshot()
    stages.append({"name": "opposite_context_preferences", "probabilities": learned,
                   "updates": brain.updates})

    # Reverse only the lively context. The tired association should survive.
    for _ in range(70):
        for action in ACTIONS:
            brain.learn(lively, action, 1 if action == "approach" else -0.6, source="user")
    reversed_probs = snapshot()
    stages.append({"name": "feedback_reversal", "probabilities": reversed_probs,
                   "updates": brain.updates})

    restored = FlyBrain.from_dict(json.loads(json.dumps(brain.to_dict(), allow_nan=False)))
    score_error = max(abs(a - b) for features in observed.values()
                      for a, b in zip(brain.scores(features), restored.scores(features)))
    probability_error = max(abs(a - b) for features in observed.values()
                            for a, b in zip(brain.probabilities(features), restored.probabilities(features)))
    original_actions = [brain.choose(lively) for _ in range(32)]
    restored_actions = [restored.choose(lively) for _ in range(32)]
    checks = {
        "tired_learns_rest": learned["tired"]["rest"] > .75,
        "lively_learns_play": learned["lively"]["play"] > .75,
        "lively_reverses_to_approach": reversed_probs["lively"]["approach"] > .75,
        "old_lively_preference_decreases": reversed_probs["lively"]["play"] < .15,
        "other_context_retains_rest": reversed_probs["tired"]["rest"] > .65,
        "scores_round_trip_exactly": score_error == 0,
        "probabilities_round_trip_exactly": probability_error == 0,
        "rng_continuation_matches": original_actions == restored_actions,
    }
    return {"model": "mushroom-body-inspired contextual bandit",
            "scope": "synthetic context learning only; not a brain simulation or consciousness test",
            "config": {"features": len(tired), "width": brain.width,
                       "fan_in": brain.fan_in, "k": brain.k},
            "stages": stages, "checks": checks, "passed": all(checks.values()),
            "persistence": {"max_score_error": score_error,
                            "max_probability_error": probability_error,
                            "matching_continuation_length": 32 if original_actions == restored_actions else 0},
            "updates": brain.updates, "user_updates": brain.user_updates}


if __name__ == "__main__":
    result = run_verification()
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    raise SystemExit(0 if result["passed"] else 1)
