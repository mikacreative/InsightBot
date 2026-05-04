from __future__ import annotations

from copy import deepcopy


USE_CASE_TEMPLATES = {
    "client_opportunity_radar": {
        "id": "client_opportunity_radar",
        "name": "Client Opportunity Radar",
        "description": "Find client-relevant market signals, cases, trends, and pitchable ideas.",
        "default_editorial_preset_id": "client_opportunity_radar",
        "default_judgement_lens_ids": [
            "client_relevance",
            "pitch_potential",
            "case_inspiration",
            "strategic_implication",
        ],
        "recommended_source_pack_ids": [
            "marketing_comms_cn",
            "brand_marketing_global",
            "ai_martech",
        ],
        "default_schedule": {"hour": 8, "minute": 0},
    }
}


EDITORIAL_PRESETS = {
    "client_opportunity_radar": {
        "id": "client_opportunity_radar",
        "name": "Client Opportunity Radar",
        "shortlist_size": 8,
        "selection_rules": [
            "Prefer signals that can support client service, proposal development, or strategic advice.",
            "Reject generic news without a clear marketing communications implication.",
            "Prefer cases, category movement, platform changes, consumer behavior shifts, and brand actions.",
        ],
        "section_rules": {
            "Client Conversation Starters": "Signals that can be raised with a current client.",
            "Pitchable Ideas": "Signals that can become proposal angles or service ideas.",
            "Case Inspiration": "Campaigns, formats, mechanics, or examples worth saving.",
            "Watchouts": "Risks, category changes, or competitor pressure.",
        },
        "dedupe_rules": [
            "Merge multiple reports about the same event into one signal.",
        ],
        "tone": "senior, concise, judgement-led",
        "citation_style": "inline",
        "quality_checks": [
            "Each item must include why it matters.",
            "Each item must include a suggested action.",
            "Each item must cite its source.",
        ],
    }
}


JUDGEMENT_LENSES = {
    "market_movement": {
        "id": "market_movement",
        "label": "Market Movement",
        "core_question": "What changed, and is the change meaningful?",
    },
    "client_relevance": {
        "id": "client_relevance",
        "label": "Client Relevance",
        "core_question": "Which current clients may care, and why?",
    },
    "pitch_potential": {
        "id": "pitch_potential",
        "label": "Pitch Potential",
        "core_question": "Can this become a proposal angle, service idea, or BD hook?",
    },
    "case_inspiration": {
        "id": "case_inspiration",
        "label": "Case Inspiration",
        "core_question": "Does this provide a useful case, format, mechanic, or proof point?",
    },
    "strategic_implication": {
        "id": "strategic_implication",
        "label": "Strategic Implication",
        "core_question": "What larger pattern or business implication does this suggest?",
    },
    "risk_watchout": {
        "id": "risk_watchout",
        "label": "Risk / Watchout",
        "core_question": "Does this create a risk, blind spot, or competitor pressure?",
    },
}


def get_use_case_template(template_id: str) -> dict:
    return deepcopy(USE_CASE_TEMPLATES[template_id])


def list_use_case_templates() -> list[dict]:
    return [deepcopy(item) for item in USE_CASE_TEMPLATES.values()]


def get_editorial_preset(preset_id: str) -> dict:
    return deepcopy(EDITORIAL_PRESETS[preset_id])


def list_editorial_presets() -> list[dict]:
    return [deepcopy(item) for item in EDITORIAL_PRESETS.values()]


def get_judgement_lens(lens_id: str) -> dict:
    return deepcopy(JUDGEMENT_LENSES[lens_id])


def get_judgement_lenses(lens_ids: list[str]) -> list[dict]:
    return [get_judgement_lens(lens_id) for lens_id in lens_ids]


def list_judgement_lenses() -> list[dict]:
    return [deepcopy(item) for item in JUDGEMENT_LENSES.values()]
