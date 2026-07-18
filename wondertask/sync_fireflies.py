"""Cron entrypoint (GitHub Actions): pull recent Fireflies transcripts and let Claude
extract + allocate tasks. Safe to run repeatedly — processed transcripts are skipped."""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent / "app"))

import integrations  # noqa: E402

if __name__ == "__main__":
    result = integrations.fireflies_sync(limit=15)
    print(json.dumps(result, indent=2, default=str))
    if result.get("error"):
        sys.exit(1)
