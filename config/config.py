import os
from pathlib import Path
from dotenv import load_dotenv

# Charger les variables d'environnement si non chargées
load_dotenv()

# Chemins des templates et des rapports
BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_HOURS = 24
TEMPLATE_FILE = "alerting_template.html"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_FILE = OUTPUT_DIR / "alertes.html"

# Fuseau horaire pour la restitution temporelle des rapports
TIMEZONE = os.getenv("APP_TIMEZONE", "Europe/Paris")

# Nombre maximal d'alertes détaillées affichées dans la section finale pour préserver la réactivité du DOM
# 0 ou négatif pour désactiver la limite
try:
    MAX_DETAILED_ALERTS = int(os.getenv("MAX_DETAILED_ALERTS", "200"))
except ValueError:
    MAX_DETAILED_ALERTS = 200

# Titres d'alertes à exclure du rapport HTML (insensible à la casse)
_default_excluded = ["Batche(s)"]
_env_excluded = os.getenv("EXCLUDED_ALERT_TITLES")
if _env_excluded:
    EXCLUDED_ALERT_TITLES = [item.strip() for item in _env_excluded.split(",") if item.strip()]
else:
    EXCLUDED_ALERT_TITLES = _default_excluded

# Configuration des liens d'artefacts GitLab
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


