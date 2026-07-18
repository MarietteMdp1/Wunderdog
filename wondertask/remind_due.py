"""Cron entrypoint (GitHub Actions): email every member their overdue / due-within-2-days
tasks. No-op until MAIL_SENDER + MS Graph credentials are configured."""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent / "app"))

import integrations  # noqa: E402

if __name__ == "__main__":
    print(json.dumps(integrations.due_reminders(), indent=2, default=str))
