"""Tests for deterministic editorial pillar and hook planning."""

import json

from config.content_strategy import hooks_for_pillar, pillar_for_weekday
from telegram_bot.handlers import _format_content_package, _package_markup


def test_weekday_rotation_has_expected_pillar_and_funnel_contract() -> None:
    expected = [
        ("Education", "TOF"),
        ("Contrarian POV", "TOF"),
        ("Authority", "MOF"),
        ("Story", "MOF"),
        ("Offer-adjacent", "BOF"),
    ]

    assert [
        (pillar_for_weekday(day).name, pillar_for_weekday(day).funnel_position)
        for day in range(5)
    ] == expected


def test_every_pillar_has_three_compatible_hook_archetypes() -> None:
    for day in range(5):
        pillar = pillar_for_weekday(day)
        hooks = hooks_for_pillar(pillar)
        assert len(hooks) == 3
        assert all(pillar.funnel_position in hook.funnel_positions for hook in hooks)


def test_telegram_package_review_shows_plan_variants_and_experiment_notes() -> None:
    package = {
        "content_plan": {
            "editorial_pillar": "Authority",
            "topical_pillar": "AI products",
            "funnel_position": "MOF",
        },
        "selected_variant": 2,
        "variants": [
            {"hook_archetype": "Evidence gap", "post_text": "First treatment"},
            {"hook_archetype": "Practical distinction", "post_text": "Second treatment"},
            {"hook_archetype": "Decision consequence", "post_text": "Third treatment"},
        ],
        "hook_ab": {"hook_a": "Opening A", "hook_b": "Opening B"},
        "flop_adjustment": "Shorten the setup.",
    }
    rendered = _format_content_package(
        {
            "id": 7,
            "status": "draft",
            "package_version": 1,
            "draft_text": "Second treatment",
            "package_json": json.dumps(package),
            "alternative_hooks_json": "[]",
            "factual_claims_json": "[]",
            "image_source": "none",
        }
    )

    assert "Plan: Authority | AI products | MOF" in rendered
    assert "V2 [Practical distinction | selected]" in rendered
    assert "Hook A/B: Opening A | Opening B" in rendered
    assert "If it flops: Shorten the setup." in rendered
    callback_data = [button.callback_data for row in _package_markup(7).inline_keyboard for button in row]
    assert "package_variant_1:7" in callback_data
    assert "package_variant_3:7" in callback_data
