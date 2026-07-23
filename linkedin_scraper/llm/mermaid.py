"""Renders a list of WorkflowStep objects into Mermaid sequenceDiagram syntax.

Kept separate from LLM output: the LLM only proposes ordered, evidence-cited
steps (actor/action pairs); this module deterministically emits valid Mermaid
syntax so a malformed/creative LLM response can never produce broken diagram
markup.
"""

import re
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from ..models.ai_insights import WorkflowStep

_SANITIZE_RE = re.compile(r"[^A-Za-z0-9_]")


def _participant_id(actor: str) -> str:
    sanitized = _SANITIZE_RE.sub("_", actor.strip()) or "Actor"
    return sanitized


def render_sequence_diagram(steps: "List[WorkflowStep]") -> str:
    if not steps:
        return ""

    ordered = sorted(steps, key=lambda s: s.step_order)

    participants = []
    seen = set()
    for step in ordered:
        if step.actor not in seen:
            participants.append(step.actor)
            seen.add(step.actor)

    lines = ["sequenceDiagram"]
    for actor in participants:
        lines.append(f"    participant {_participant_id(actor)} as {actor}")

    for i, step in enumerate(ordered):
        source = _participant_id(step.actor)
        target = _participant_id(ordered[i + 1].actor) if i + 1 < len(ordered) else source
        action = step.action.replace("\n", " ").strip()
        lines.append(f"    {source}->>{target}: {step.step_order}. {action}")

    return "\n".join(lines)
