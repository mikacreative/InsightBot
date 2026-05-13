def summarize_coverage(*, candidate_count: int, threshold: float) -> dict:
    return {
        "candidate_count": candidate_count,
        "threshold": threshold,
        "meets_threshold": candidate_count > 0,
    }
