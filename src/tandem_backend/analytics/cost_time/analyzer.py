"""Cost/time composition entry point; resource measurements retain their scope."""

from .activity import activity
from .durations import summarize_durations
from .features import usage
from .tokens import normalize_token_buckets, token_total


def analyze_cost_time(sessions, events, calls, model_calls, main_ids, scope, records_complete=True, intervals=None):
    return {"grain": "request/call/session", "display_timezone": scope.display_timezone,
            "usage": usage(model_calls, events or [], sessions, scope, records_complete),
            "durations": summarize_durations(calls, events, intervals),
            "activity_rhythm": activity(sessions, events or [], calls, model_calls, main_ids, scope) if events is not None else None,
            "deferred": ["actual_cost_analysis", "estimated_cost_analysis", "time_to_first_acceptance", "human_work_duration"]}


__all__ = ['activity', 'analyze_cost_time', 'normalize_token_buckets', 'summarize_durations', 'token_total', 'usage']
