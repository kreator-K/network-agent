"""Deterministic editorial planning and hook selection for content packages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


FunnelPosition = Literal["TOF", "MOF", "BOF"]


@dataclass(frozen=True)
class EditorialPillar:
    """One editorial treatment in the weekday content rotation."""

    name: str
    funnel_position: FunnelPosition
    purpose: str


@dataclass(frozen=True)
class HookArchetype:
    """Named opening pattern with an explicit editorial fit."""

    name: str
    funnel_positions: tuple[FunnelPosition, ...]
    pillars: tuple[str, ...]
    instruction: str


EDITORIAL_PILLARS: tuple[EditorialPillar, ...] = (
    EditorialPillar("Education", "TOF", "Teach one useful distinction or method."),
    EditorialPillar("Contrarian POV", "TOF", "Challenge a common assumption without forced controversy."),
    EditorialPillar("Authority", "MOF", "Demonstrate grounded judgment through analysis and evidence."),
    EditorialPillar("Story", "MOF", "Use only verified experience or a clearly attributed source narrative."),
    EditorialPillar("Offer-adjacent", "BOF", "Show a practical decision framework without a hard sell."),
)


HOOK_ARCHETYPES: tuple[HookArchetype, ...] = (
    HookArchetype(
        "Practical distinction",
        ("TOF", "MOF"),
        ("Education", "Authority"),
        "Open by separating two ideas that are often treated as equivalent.",
    ),
    HookArchetype(
        "Evidence gap",
        ("TOF", "MOF", "BOF"),
        ("Contrarian POV", "Authority", "Offer-adjacent"),
        "Open with the important evidence or decision criterion that is usually missing.",
    ),
    HookArchetype(
        "Measured counterpoint",
        ("TOF", "MOF"),
        ("Contrarian POV", "Authority"),
        "State a defensible counterpoint without exaggeration or engagement bait.",
    ),
    HookArchetype(
        "Source-led observation",
        ("TOF", "MOF"),
        ("Education", "Story", "Authority"),
        "Lead with a specific observation supported by the selected source.",
    ),
    HookArchetype(
        "Decision consequence",
        ("MOF", "BOF"),
        ("Authority", "Story", "Offer-adjacent"),
        "Open with the practical consequence of making the wrong product or strategy decision.",
    ),
    HookArchetype(
        "Practical next step",
        ("MOF", "BOF"),
        ("Authority", "Offer-adjacent"),
        "Open with the specific decision or action the evidence supports next.",
    ),
    HookArchetype(
        "Verified reflection",
        ("MOF",),
        ("Story",),
        "Use first person only when the supplied profile contains a directly supporting experience.",
    ),
)


def pillar_for_weekday(weekday: int) -> EditorialPillar:
    """Return the Monday-Friday pillar, with weekend dates rotating safely."""
    return EDITORIAL_PILLARS[weekday % len(EDITORIAL_PILLARS)]


def hooks_for_pillar(pillar: EditorialPillar, limit: int = 3) -> tuple[HookArchetype, ...]:
    """Return stable, compatible hook choices for one editorial plan."""
    exact = [hook for hook in HOOK_ARCHETYPES if pillar.name in hook.pillars]
    compatible = [
        hook
        for hook in HOOK_ARCHETYPES
        if pillar.funnel_position in hook.funnel_positions and hook not in exact
    ]
    return tuple((exact + compatible)[:limit])
