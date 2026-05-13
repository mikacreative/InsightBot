def summarize_source_failures(failures: list[dict]) -> dict:
    return {
        "count": len(failures),
        "items": failures,
    }
