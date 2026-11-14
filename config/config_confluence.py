from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

confluence_config = {
    "url": os.getenv("CONFLUENCE_URL"),
    "token": os.getenv("CONFLUENCE_TOKEN"),
    "page_id": os.getenv("CONFLUENCE_PAGE_ID"),
    "archive_page_id": os.getenv("CONFLUENCE_ARCHIVE_PAGE_ID"),
    "stats_page_id": os.getenv("CONFLUENCE_STATS_PAGE_ID"),
    "disabled": os.getenv("CONFLUENCE_DISABLED", "false").lower() in ("true", "1", "yes"),
}
