"""Cron entrypoint (GitHub Actions): analyze new messages in the configured Teams channel.
Cursor-tracked — each run only looks at messages newer than the last run."""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent / "app"))

import integrations  # noqa: E402

if __name__ == "__main__":
    result = integrations.teams_sync()
    print(json.dumps(result, indent=2, default=str))
    if result.get("error"):
        sys.exit(1)
