"""Signal Desk product-layer helpers."""

from .patterns import IntentContract, PatternContract, QualityGateContract
from .routing import (
    DEFAULT_OUTPUT_INTENT,
    DEFAULT_PATTERN_ID,
    DEFAULT_RESULT_MODE,
    DEFAULT_TIME_WINDOW,
    SignalDeskAccessRequest,
    SignalDeskRoute,
    normalize_output_intent,
    normalize_pattern_id,
    normalize_result_mode,
    normalize_time_window,
    resolve_signal_desk_route,
    route_to_intent_contract,
)

__all__ = [
    "DEFAULT_OUTPUT_INTENT",
    "DEFAULT_PATTERN_ID",
    "DEFAULT_RESULT_MODE",
    "DEFAULT_TIME_WINDOW",
    "IntentContract",
    "PatternContract",
    "QualityGateContract",
    "SignalDeskAccessRequest",
    "SignalDeskRoute",
    "normalize_output_intent",
    "normalize_pattern_id",
    "normalize_result_mode",
    "normalize_time_window",
    "resolve_signal_desk_route",
    "route_to_intent_contract",
]
