# 🚨 Mattermost Alerting & Confluence Action Tracking

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Code Style](https://img.shields.io/badge/code%20style-pep8-orange.svg)](https://pep8.org/)

An automated production alerting pipeline designed to extract, deduplicate, categorize, and visualize Mattermost monitoring alerts while maintaining a bidirectional, persistent action item tracking registry on Atlassian Confluence Server / Data Center.

---

## ✨ Key Features

- **⏱️ Interactive Chronological Timeline**:
  - Continuous linear visualization of alert triggers (`FIRING`) and resolutions (`RESOLVED`).
  - Proportional positioning on an adaptive time axis with day markers, midnight separators, and weekly/monthly grouping.
  - Drill-down per category into months, days, and individual occurrences with direct links to Mattermost posts.
- **🧠 Smart Categorization & Normalization**:
  - Automatically strips ephemeral Kubernetes pod replica hashes (e.g., `-8578c8c7ff-wld7g`) and dynamic metric values (e.g., `(current : 91)`) to avoid category fragmentation.
  - Automatically ignores configurable status batches (e.g., `Batche(s) OK/KO`).
- **🔄 Bidirectional Confluence Action Tracking (6-State Lifecycle Machine)**:
  - **🔹 `NEW`**: First detection. Prompts root-cause investigation and team triage.
  - **⚪ `UNATTENDED`**: Unassigned alert awaiting triage. *Automatic countdown warning at 4 weeks, automatic purge after 1 month.*
  - **🔸 `IN PROGRESS`**: Action item assigned to an owner with target due date.
  - **🔺 `RECURRING`**: Automatically triggered if a previously resolved or archived alert fires again.
  - **✅ `RESOLVED`**: Team fix deployed and verified. *Automatically archived after 1 month.*
  - **🟤 `NOISE`**: Known incompressible noise, automatically isolated in a dedicated secondary table.
- **📦 Multi-Page Confluence Ecosystem**:
  - **Active Board**: Primary review register with status palette, quick copy/paste helpers, and cross-navigation.
  - **Archive Board**: Clean 6-column historical record of resolved alerts (> 1 month).
  - **Weekly Statistics**: Automated weekly metrics log with the visual HTML report attached via REST API.
- **🌟 Standalone Zero-Dependency Demo Mode (`--demo`, `--open`)**:
  - Instantly test and showcase the full workflow in under **0.5 seconds** without needing Mattermost, Confluence, or Docker.
  - Generates 4 interconnected local HTML deliverables including authentic Confluence web views with interactive anchor highlighting.
- **🛡️ Resilient & Secure**:
  - Built-in connection pooling and exponential backoff retry strategy (`urllib3.util.retry.Retry`).
  - Strict HTML sanitization via `BeautifulSoup` preventing XSS injection from Confluence tables.
  - Non-blocking design: continues generating local reports even if Confluence is temporarily unreachable.

---

## 📁 Project Structure

```text
alerting/
├── .gitlab-ci.yml              # GitLab CI/CD pipeline configuration (weekly automation)
├── main.py                     # Application CLI entrypoint
├── requirements.txt            # Required dependencies (requests, Jinja2, python-dotenv, beautifulsoup4)
├── .env.example                # Example environment configuration template
├── README.md                   # Project documentation
├── config/
│   ├── config.py               # Paths, defaults, timezone, and artifact link resolution
│   ├── config_mattermost.py    # Mattermost credentials loader
│   └── config_confluence.py    # Confluence credentials and page IDs loader
├── clients/
│   ├── mattermost_client.py    # Mattermost v4 REST API client with pagination
│   └── confluence_client.py    # Confluence Server / Data Center REST client (XHTML storage)
├── services/
│   ├── alert_service.py        # Normalization, categorization, and timeline chart data model
│   ├── tracking_service.py     # Reconciliation, Confluence XHTML storage parser/generator, state machine
│   ├── demo_service.py         # In-memory Mattermost/Confluence mocks and web view exporter for demo mode
│   └── template_renderer.py    # Jinja2 template rendering engine with caching and autoescape
├── templates/
│   └── alerting_template.html  # Standalone responsive HTML report template
├── tests/
│   ├── test_alert_service.py       # Unit tests for categorization and timeline model
│   ├── test_confluence_client.py   # Unit tests for Confluence REST API client
│   ├── test_demo_mode.py           # Unit tests for standalone demo mode and Confluence export
│   ├── test_main_args.py           # Unit tests for CLI arguments and environment variables
│   └── test_tracking_service.py    # Unit tests for normalization, reconciliation, and lifecycle
├── utils/
│   └── logger.py               # ANSI color console logger and initialization banner
└── output/                     # Generated reports directory (.gitkeep preserved)
    └── alertes.html
```

---

## ⚙️ Installation

1. Navigate to the project directory:
   ```bash
   cd alerting
   ```

2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Linux/macOS
   # or on Windows:
   .\venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

---

## 🔑 Configuration

Create a `.env` file at the root of `alerting/` (or copy `.env.example`):

```env
# Mattermost Configuration
MATTERMOST_URL=https://mattermost.yourdomain.com
MATTERMOST_TOKEN=your_bot_or_user_token
MATTERMOST_CHANNEL_ID=your_channel_id
MATTERMOST_TEAM=your_team

# General Options
EXCLUDED_ALERT_TITLES=Batche(s)
APP_TIMEZONE=Europe/Paris
MAX_DETAILED_ALERTS=200

# Confluence Review Tracking (Optional)
CONFLUENCE_URL=https://confluence.yourdomain.com
CONFLUENCE_TOKEN=your_personal_access_token
CONFLUENCE_PAGE_ID=123456789
CONFLUENCE_ARCHIVE_PAGE_ID=123456780
CONFLUENCE_STATS_PAGE_ID=123456781
CONFLUENCE_DISABLED=false
CONFLUENCE_TRACKING=false
```

---

## 🚀 Usage

### 🌟 Standalone Demo Mode (Zero Configuration Required)

Run the tool instantly **without needing access to any Mattermost or Confluence server**. Generates a realistic 7-day microservices incident dataset (40 alerts) and simulates the full Confluence lifecycle (reconciliation, recurrences, noise isolation, archiving):

```bash
python main.py --demo
```

To generate and automatically open the report in your default browser:
```bash
python main.py --demo --open
```

In demo mode, the script generates **4 interconnected local HTML files** in `output/`:
1. `output/alertes.html`: Main visual alerting report (interactive timeline, badges, KPIs, and links).
2. `output/confluence_suivi.html`: Authentic Confluence Server rendering of the **active review board** (Atlassian AUI status lozenges, copy/paste palette, secondary noise table).
3. `output/confluence_archive.html`: Confluence rendering of the **archive board** showing alerts resolved over 1 month ago.
4. `output/confluence_stats.html`: Confluence rendering of the **weekly statistics log** with the HTML report attachment.

*💡 Click on **"Edit on Confluence ↗"** from the alerting report to jump directly to the corresponding row in `confluence_suivi.html` with smooth scrolling and blue row highlighting!*

---

### 📋 Command Line Interface (CLI) Options

| Option | Type / Values | Default | Description |
| :--- | :--- | :--- | :--- |
| **`--demo`** | Flag | `false` | Runs standalone demo mode with in-memory simulated data. |
| **`--open`** | Flag | `false` | Automatically opens the generated HTML report in the default browser. |
| **`--hours`** | Strictly positive integer | `24` *(or `168` in `--demo`)* | Number of hours of history to analyze (e.g. `168` for 7 days). |
| **`--output`** | File path | `output/alertes.html` | Custom output file path for the generated HTML report. |
| **`--confluence-tracking`** | Boolean (`true`/`false`) or Flag | Env `CONFLUENCE_TRACKING` *(or `true` in `--demo`)* | Enables or disables Confluence synchronization and reconciliation. |

*Note: `--suivi-confluence` is supported as a backward-compatible alias for `--confluence-tracking`.*

---

### Standard Execution (Mattermost only, without Confluence)

```bash
python main.py
```

### Execution with Confluence Action Tracking

```bash
python main.py --hours 168 --confluence-tracking
# or explicitly with a boolean:
python main.py --hours 168 --confluence-tracking=true
python main.py --hours 168 --confluence-tracking=false
```

### Custom Time Window

```bash
python main.py --hours 48
```

### Custom Output File

```bash
python main.py --output /path/to/custom_report.html
```

### Running Automated Unit Tests

```bash
python -m pytest -v
```

---

## 🏛️ Confluence Integration Architecture

The Confluence integration centers around **3 interconnected wiki pages**:

| Confluence Page | Role | Environment Variable | Default Identifier |
| :--- | :--- | :--- | :--- |
| **1. Active Review Board** | Main qualification table, secondary noise table, copy/paste lozenge palette, review checklist. | `CONFLUENCE_PAGE_ID` | `123456789` |
| **2. Archive Board** | Permanent historical record of decisions on alerts resolved over 1 month ago (6 columns without status). | `CONFLUENCE_ARCHIVE_PAGE_ID` | `123456780` |
| **3. Statistics Log** | Weekly journal tracking 12 evolution metrics run by run with the generated HTML report attached. | `CONFLUENCE_STATS_PAGE_ID` | `123456781` |

### Active Board Columns:
1. **Status**: `<ac:structured-macro ac:name="status">` (`NEW`, `UNATTENDED`, `IN PROGRESS`, `RECURRING`, `RESOLVED`, `NOISE`)
2. **Alert Category**: Category description + `<ac:structured-macro ac:name="anchor">` for deep linking
3. **Occurrences**: Current week occurrences
4. **Last Seen in Mattermost**: Native `<time datetime="YYYY-MM-DD" />` tag + time
5. **Assignee**: Team member responsible for the action item
6. **Due Date**: Target resolution date (`<time>` or `-`)
7. **Action Items (Review Meeting)**: Team decisions, tickets, and mitigation plan

---

## 🔄 GitLab CI/CD Automation

The included `.gitlab-ci.yml` automates weekly execution:

1. **Project Variables**: Under GitLab (**Settings > CI/CD > Variables**), configure:
   - `MATTERMOST_URL`
   - `MATTERMOST_TOKEN` (Masked)
   - `MATTERMOST_CHANNEL_ID`
   - `CONFLUENCE_URL`
   - `CONFLUENCE_TOKEN` (Masked)
   - `CONFLUENCE_PAGE_ID`
   - `CONFLUENCE_ARCHIVE_PAGE_ID` (Optional)
   - `CONFLUENCE_STATS_PAGE_ID` (Optional)

2. **Schedule**: Under GitLab (**Build > Pipeline schedules**):
   - Interval Pattern: `30 10 * * 1` (Every Monday at 10:30 AM).
   - Variables: `WEEKLY_HOURS="--hours=168"`, `CONFLUENCE_TRACKING_ARG="--confluence-tracking=true"`.

3. **Artifacts**: The generated report `output/alertes.html` is automatically preserved as a job artifact.

---

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.
