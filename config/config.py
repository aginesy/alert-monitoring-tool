import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables if not already loaded
load_dotenv()

# Template and report paths
BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_HOURS = 24
TEMPLATE_FILE = "alerting_template.html"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_FILE = OUTPUT_DIR / "alertes.html"

# Timezone for report formatting
TIMEZONE = os.getenv("APP_TIMEZONE", "Europe/Paris")

# Confluence tracking default flag (supports CONFLUENCE_TRACKING with SUIVI_CONFLUENCE fallback)
CONFLUENCE_TRACKING = (
    os.getenv("CONFLUENCE_TRACKING") or os.getenv("SUIVI_CONFLUENCE", "false")
).lower() in ("true", "1", "yes")

# Maximum number of detailed alerts displayed in the final section to keep the DOM responsive
# Set to 0 or negative to disable the limit
try:
    MAX_DETAILED_ALERTS = int(os.getenv("MAX_DETAILED_ALERTS", "200"))
except ValueError:
    MAX_DETAILED_ALERTS = 200

# Alert titles to exclude from the HTML report (case-insensitive)
_default_excluded = ["Batche(s)"]
_env_excluded = os.getenv("EXCLUDED_ALERT_TITLES")
if _env_excluded:
    EXCLUDED_ALERT_TITLES = [item.strip() for item in _env_excluded.split(",") if item.strip()]
else:
    EXCLUDED_ALERT_TITLES = _default_excluded

# GitLab CI/CD artifact link configuration
GITLAB_PROJECT_URL = os.getenv(
    "CI_PROJECT_URL", "https://gitlab.example.com/username/alerting"
)
GITLAB_BRANCH = os.getenv("CI_COMMIT_REF_NAME", "dev")
GITLAB_JOB_NAME = os.getenv("CI_JOB_NAME", "generate_alerting_report")
GITLAB_JOB_ID = os.getenv("CI_JOB_ID")

_env_artifact_url = os.getenv("GITLAB_ARTIFACT_URL")
if _env_artifact_url:
    GITLAB_ARTIFACT_URL = _env_artifact_url
elif GITLAB_JOB_ID:
    GITLAB_ARTIFACT_URL = f"{GITLAB_PROJECT_URL}/-/jobs/{GITLAB_JOB_ID}/artifacts/raw/output/alertes.html"
else:
    GITLAB_ARTIFACT_URL = (
        f"{GITLAB_PROJECT_URL}/-/jobs/artifacts/{GITLAB_BRANCH}/raw/output/alertes.html"
        f"?job={GITLAB_JOB_NAME}"
    )

if GITLAB_JOB_ID:
    GITLAB_ARTIFACT_BROWSE_URL = f"{GITLAB_PROJECT_URL}/-/jobs/{GITLAB_JOB_ID}/artifacts/browse/output"
else:
    GITLAB_ARTIFACT_BROWSE_URL = (
        f"{GITLAB_PROJECT_URL}/-/jobs/artifacts/{GITLAB_BRANCH}/browse/output"
        f"?job={GITLAB_JOB_NAME}"
    )
