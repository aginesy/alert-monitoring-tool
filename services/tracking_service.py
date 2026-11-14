from __future__ import annotations

import calendar
import html
import logging
import re
import unicodedata
from datetime import datetime, tzinfo
from typing import Any

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Dynamic metrics and ephemeral pod hash stripping
RE_DYNAMIC_METRIC = re.compile(r"\s*\(current\s*:[^)]*\)", re.IGNORECASE)
RE_POD_HASH = re.compile(r"(-[a-f0-9]{8,10}-[a-z0-9]{4,5})\b", re.IGNORECASE)
RE_CLEAN_SPACES = re.compile(r"\s+")
RE_NON_ALPHANUM = re.compile(r"[^a-z0-9]+")

STATUS_COLORS = {
    # Canonical English statuses
    "NEW": "Blue",
    "UNATTENDED": "Grey",
    "IN PROGRESS": "Yellow",
    "RECURRING": "Red",
    "RESOLVED": "Green",
    "NOISE": "Brown",
    # French aliases for backward compatibility with existing Confluence pages
    "NOUVELLE": "Blue",
    "PTPNEL": "Grey",
    "NOUV": "Grey",
    "EN COURS": "Yellow",
    "RÉCURRENTE": "Red",
    "RECURRENTE": "Red",
    "RÉSOLUE": "Green",
    "RESOLUE": "Green",
    "BRUIT": "Brown",
}

STATUS_RANKS = {
    "RECURRING": 1,
    "RÉCURRENTE": 1,
    "RECURRENTE": 1,
    "NEW": 2,
    "NOUVELLE": 2,
    "UNATTENDED": 2,
    "PTPNEL": 2,
    "NOUV": 2,
    "IN PROGRESS": 3,
    "EN COURS": 3,
    "RESOLVED": 4,
    "RÉSOLUE": 4,
    "RESOLUE": 4,
    "NOISE": 5,
    "BRUIT": 5,
}


class TrackingService:
    """
    Reconciliation and action tracking service for alert categories.
    Binds a persistent review history (statuses, action items, assignees)
    from Confluence to each alerting pipeline run.
    """

    @classmethod
    def normalize_category_name(cls, name: str) -> str:
        """
        Normalizes category names to avoid duplicates caused by dynamic metric values
        (e.g., '(current : 91)', ephemeral pod replica hashes '-8578c8c7ff-wld7g', multiple spaces).
        """
        if not name:
            return "Alert without description"

        text = html.unescape(name)
        # Strip dynamic metrics like (current : 91)
        text = RE_DYNAMIC_METRIC.sub("", text)
        # Strip ephemeral pod replica hashes
        text = RE_POD_HASH.sub("", text)
        # Clean extra whitespace
        text = RE_CLEAN_SPACES.sub(" ", text).strip()
        return text

    @classmethod
    def get_category_slug(cls, name: str) -> str:
        """
        Generates a stable textual identifier (slug) for the category,
        used as a Confluence anchor and reconciliation key.
        """
        normalized = cls.normalize_category_name(name).lower()
        # Strip accents (é -> e, à -> a, etc.)
        deaccented = unicodedata.normalize("NFKD", normalized).encode("ASCII", "ignore").decode("utf-8")
        slug = RE_NON_ALPHANUM.sub("-", deaccented).strip("-")
        return slug[:120] if slug else "category"

    ALLOWED_TAGS = {
        "p", "br", "ul", "ol", "li", "strong", "b", "em", "i", "code",
        "pre", "span", "a", "blockquote", "div",
    }
    ALLOWED_ATTRS = {
        "a": ["href", "title", "target", "rel"],
        "span": ["class"],
        "div": ["class"],
        "code": ["class"],
    }

    @classmethod
    def sanitize_actions_html(cls, html_str: str) -> str:
        """
        Cleans and sanitizes HTML content of action items entered in Confluence
        to prevent XSS vulnerabilities when rendered in the HTML report.
        Strips dangerous tags and attributes (script, iframe, on*, javascript:).
        """
        if not html_str:
            return ""

        soup = BeautifulSoup(html_str, "html.parser")

        # 1. Remove dangerous tags and their content
        for tag in soup.find_all(["script", "style", "iframe", "object", "embed", "applet", "form"]):
            tag.decompose()

        # 2. Clean disallowed tags and suspicious attributes
        for tag in soup.find_all(True):
            if tag.name not in cls.ALLOWED_TAGS:
                tag.unwrap()
            else:
                allowed = cls.ALLOWED_ATTRS.get(tag.name, [])
                attrs = dict(tag.attrs)
                for attr, val in attrs.items():
                    if attr.lower().startswith("on") or attr.lower() not in allowed:
                        del tag[attr]
                    elif tag.name == "a" and attr == "href":
                        if not re.match(r"^(https?://|mailto:|#|/)", str(val).strip(), re.IGNORECASE):
                            del tag["href"]
                        else:
                            tag["target"] = "_blank"
                            tag["rel"] = "noopener noreferrer"

        return str(soup).strip()

    @classmethod
    def format_confluence_date_cell(cls, val: str) -> str:
        """
        Formats date with native Confluence <time datetime="YYYY-MM-DD" /> tag
        followed by precise time (HH:mm:ss) to enable native chronological sorting in Confluence.
        Returns '-' if no valid date is provided.
        """
        if not val or val.strip() in ("-", "Previous", "Antérieure", "anterieure", "Inconnue", "Unknown"):
            return "-"
        if "<time" in val:
            return val

        # Format DD/MM/YYYY with optional time
        m_fr = re.search(r"(\d{2})/(\d{2})/(\d{4})(?:(?:\s+[àaat]\s+|\s+)(\d{2}:\d{2}(?::\d{2})?))?", val)
        if m_fr:
            day, month, year, time_part = m_fr.groups()
            time_str = f" {time_part}" if time_part else ""
            return f'<time datetime="{year}-{month}-{day}" />{time_str}'

        # Format YYYY-MM-DD with optional time
        m_iso = re.search(r"(\d{4})-(\d{2})-(\d{2})(?:(?:\s+[àaat]\s+|\s+)(\d{2}:\d{2}(?::\d{2})?))?", val)
        if m_iso:
            year, month, day, time_part = m_iso.groups()
            time_str = f" {time_part}" if time_part else ""
            return f'<time datetime="{year}-{month}-{day}" />{time_str}'

        return html.escape(val)

    @classmethod
    def _detect_column_indices(cls, headers: list[str]) -> dict[str, int]:
        """Detects column indices from header labels (supports both English and French)."""
        indices = {
            "status": -1,
            "category": 0,
            "occurrences": 1,
            "last_seen": 2,
            "assignee": 3,
            "due_date": 4,
            "actions": 5,
        }
        for idx, h in enumerate(headers):
            if any(term in h for term in ["status", "statut"]):
                indices["status"] = idx
            elif any(term in h for term in ["due", "échéance", "echeance", "deadline"]):
                indices["due_date"] = idx
            elif any(term in h for term in ["seen", "apparition", "mattermost", "last seen"]):
                indices["last_seen"] = idx
            elif any(term in h for term in ["assign", "porteur", "responsable", "owner"]):
                indices["assignee"] = idx
            elif any(term in h for term in ["action", "decision", "décision", "suivi", "item"]):
                indices["actions"] = idx
            elif any(term in h for term in ["occurrence", "count", "nombre"]):
                indices["occurrences"] = idx
            elif any(term in h for term in ["category", "catégorie", "categorie"]):
                indices["category"] = idx
            elif any(term in h for term in ["date", "detection", "détection"]):
                indices["last_seen"] = idx
        return indices

    @classmethod
    def _parse_row_entry(
        cls,
        cells: list[Any],
        col_indices: dict[str, int],
        default_status: str = "NEW",
    ) -> dict[str, Any] | None:
        """Parses a Confluence table row and extracts the category data record."""
        if len(cells) < 2:
            return None

        # 1. Category and slug
        col_cat = col_indices.get("category", 0)
        cat_cell = cells[col_cat] if col_cat < len(cells) else cells[0]

        anchor_macro = cat_cell.find("ac:structured-macro", attrs={"ac:name": "anchor"})
        anchor_slug = ""
        if anchor_macro:
            anchor_param = anchor_macro.find("ac:parameter")
            if anchor_param:
                anchor_slug = anchor_param.get_text(strip=True)
            anchor_macro.decompose()

        strong_tag = cat_cell.find("strong")
        raw_cat_name = strong_tag.get_text(strip=True) if strong_tag else cat_cell.get_text(strip=True)
        while anchor_slug and raw_cat_name.startswith(anchor_slug):
            raw_cat_name = raw_cat_name[len(anchor_slug):].strip()

        if not raw_cat_name:
            return None

        slug = anchor_slug or cls.get_category_slug(raw_cat_name)

        # 2. Status and unattended_since
        col_st = col_indices.get("status", -1)
        unattended_since = None
        if col_st >= 0 and col_st < len(cells):
            status_cell = cells[col_st]
            status_macro = status_cell.find("ac:structured-macro", attrs={"ac:name": "status"})
            if status_macro:
                param_title = status_macro.find("ac:parameter", attrs={"ac:name": "title"})
                raw_status = param_title.get_text(strip=True) if param_title else status_macro.get_text(strip=True)
            else:
                raw_status = status_cell.get_text(strip=True)
            status = cls._normalize_status(raw_status)

            if status == "UNATTENDED":
                time_tag_status = status_cell.find("time")
                if time_tag_status and time_tag_status.get("datetime"):
                    unattended_since = time_tag_status.get("datetime")
                else:
                    m_date = re.search(r"(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})", status_cell.get_text())
                    if m_date:
                        unattended_since = m_date.group(1)
        else:
            status = default_status

        # 3. Occurrences
        col_occ = col_indices.get("occurrences", -1)
        occ_cell = cells[col_occ] if 0 <= col_occ < len(cells) else None
        occ_text = occ_cell.get_text(strip=True) if occ_cell else ""
        prev_total = cls._extract_total_occurrences(occ_text)

        # 4. Decided actions (sanitized)
        col_act = col_indices.get("actions", -1)
        act_cell = cells[col_act] if 0 <= col_act < len(cells) else None
        actions_html = (
            cls.sanitize_actions_html("".join(str(c) for c in act_cell.contents).strip())
            if act_cell
            else ""
        )

        # 5. Assignee
        col_ass = col_indices.get("assignee", -1)
        ass_cell = cells[col_ass] if 0 <= col_ass < len(cells) else None
        assignee = ass_cell.get_text(strip=True) if ass_cell else ""

        # 6. Due date
        col_due = col_indices.get("due_date", -1)
        due_cell = cells[col_due] if 0 <= col_due < len(cells) else None
        due_date = "-"
        if due_cell:
            time_tag = due_cell.find("time")
            due_date = time_tag.get("datetime", "") if time_tag else due_cell.get_text(strip=True)
        if not due_date or due_date.strip() in ("", "-", "Inconnue", "Unknown"):
            due_date = "-"

        # 7. Last seen date
        col_ls = col_indices.get("last_seen", -1)
        ls_cell = cells[col_ls] if 0 <= col_ls < len(cells) else None
        last_seen = ""
        if ls_cell:
            time_tag = ls_cell.find("time")
            if time_tag:
                iso_date = time_tag.get("datetime", "")
                time_tag.decompose()
                time_str = ls_cell.get_text(strip=True)
                last_seen = f"{iso_date} {time_str}".strip() if time_str else iso_date
            else:
                last_seen = ls_cell.get_text(strip=True)

        return {
            "slug": slug,
            "name": raw_cat_name,
            "status": status,
            "occurrences_text": occ_text,
            "occurrences_display": occ_text,
            "total_occurrences": prev_total,
            "actions_html": actions_html,
            "assignee": assignee,
            "due_date": due_date,
            "last_seen": last_seen,
            "unattended_since": unattended_since,
            "ptpnel_since": unattended_since,
            "nouv_since": unattended_since,
        }

    @classmethod
    def parse_confluence_storage(cls, storage_html: str) -> dict[str, dict[str, Any]]:
        """
        Parses existing Confluence storage XHTML and extracts category records.
        Reads both the main active table and the secondary noise table.
        Preserves team decisions, assignees, and action items.
        """
        registry: dict[str, dict[str, Any]] = {}
        if not storage_html:
            return registry

        soup = BeautifulSoup(storage_html, "html.parser")
        tables = soup.find_all("table")
        if not tables:
            return registry

        for table in tables:
            rows = table.find_all("tr")
            if not rows:
                continue
            headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]
            if not any(term in " ".join(headers) for term in ["category", "catégorie", "categorie", "status", "statut", "alert", "alerte"]):
                continue

            col_indices = cls._detect_column_indices(headers)
            for row in rows[1:]:
                entry = cls._parse_row_entry(row.find_all(["td", "th"]), col_indices, default_status="NEW")
                if entry:
                    registry[entry["slug"]] = entry

        logger.info("[TRACKING] %d existing categories loaded from Confluence page.", len(registry))
        return registry

    @classmethod
    def parse_confluence_archive_storage(cls, storage_html: str) -> dict[str, dict[str, Any]]:
        """
        Parses Confluence archive storage and extracts archived category records
        (assigns default status RESOLVED).
        """
        registry: dict[str, dict[str, Any]] = {}
        if not storage_html:
            return registry

        soup = BeautifulSoup(storage_html, "html.parser")
        tables = soup.find_all("table")
        if not tables:
            return registry

        for table in tables:
            rows = table.find_all("tr")
            if not rows:
                continue
            headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]
            col_indices = cls._detect_column_indices(headers)
            for row in rows[1:]:
                entry = cls._parse_row_entry(row.find_all(["td", "th"]), col_indices, default_status="RESOLVED")
                if entry:
                    registry[entry["slug"]] = entry

        return registry

    @classmethod
    def _normalize_status(cls, raw_status: str) -> str:
        """Standardizes status labels into English canonical values."""
        upper = raw_status.upper().strip()
        if "NOISE" in upper or "BRUIT" in upper:
            return "NOISE"
        if "RECUR" in upper or "RÉCUR" in upper:
            return "RECURRING"
        if "RESOL" in upper or "RÉSOL" in upper or "CLOS" in upper or "TERM" in upper:
            return "RESOLVED"
        if "PROGRESS" in upper or "COURS" in upper:
            return "IN PROGRESS"
        if "UNATTENDED" in upper or "UNASSIGNED" in upper or "PTPNEL" in upper or "NOUV" in upper:
            return "UNATTENDED"
        return "NEW"

    @classmethod
    def _extract_total_occurrences(cls, text: str) -> int:
        """Extracts total occurrences from text like '5 this week (total: 12)' or '10 cette semaine'."""
        m_total = re.search(r"total\s*:\s*(\d+)", text, re.IGNORECASE)
        if m_total:
            return int(m_total.group(1))
        m_num = re.search(r"^(\d+)", text)
        if m_num:
            return int(m_num.group(1))
        return 0

    @classmethod
    def _is_action_effective(cls, html_or_text: str | None) -> bool:
        """Determines whether entered action item is a real, non-placeholder action."""
        if not html_or_text:
            return False
        clean = re.sub(r"<[^>]+>", " ", str(html_or_text)).strip()
        if not clean or clean in ("-", "None", "None."):
            return False
        lower = clean.lower()
        if any(term in lower for term in [
            "à définir", "a definir", "point de suivi", "en attente de qualification",
            "to be defined", "review meeting", "pending triage", "tbd",
        ]):
            return False
        return len(clean) >= 3

    @classmethod
    def has_action_taken(cls, actions_html: str | None, assignee: str | None) -> bool:
        """Returns True if the team has assigned an owner or defined an effective action item."""
        if assignee and assignee.strip() and assignee.strip() not in ("-", "None", "Inconnu", "Unknown"):
            return True
        return cls._is_action_effective(actions_html)

    @classmethod
    def reconcile(
        cls,
        categories: list[dict[str, Any]],
        existing_registry: dict[str, dict[str, Any]],
        current_date_str: str,
    ) -> list[dict[str, Any]]:
        """
        Reconciles current alerting run categories with existing Confluence registry.
        Executes the 6-state alert lifecycle state machine:
        - NEW alerts: without action -> switch to UNATTENDED next week
        - RESOLVED alerts: if recurring -> switch to RECURRING
        - UNATTENDED alerts: if action taken -> switch to IN PROGRESS
        - NOISE alerts: isolated in dedicated table
        """
        tracked_categories: list[dict[str, Any]] = []
        handled_slugs: set[str] = set()

        for cat in categories:
            cat_name = cat.get("name", "")
            norm_name = cls.normalize_category_name(cat_name)
            slug = cls.get_category_slug(norm_name)
            handled_slugs.add(slug)

            count_now = cat.get("count", 0)

            if slug in existing_registry:
                prev = existing_registry[slug]
                prev_status = prev.get("status", "NEW")
                prev_total = prev.get("total_occurrences", 0)
                new_total = prev_total + count_now

                # State machine:
                # 0. NOISE status (manually set)
                if prev_status == "NOISE":
                    new_status = "NOISE"
                # 1. Previously RESOLVED alert re-triggering -> RECURRING
                elif prev_status in ("RESOLVED", "RÉSOLUE", "RESOLUE"):
                    new_status = "RECURRING"
                    logger.info(
                        "[TRACKING] Alert '%s' recurred (%d occurrences) -> Status switched to RECURRING.",
                        norm_name[:50],
                        count_now,
                    )
                # 2. Previous NEW alert
                elif prev_status in ("NEW", "NOUVELLE"):
                    if cls.has_action_taken(prev.get("actions_html"), prev.get("assignee")):
                        new_status = "IN PROGRESS"
                    else:
                        new_status = "UNATTENDED"
                        logger.info(
                            "[TRACKING] Alert '%s' (previously NEW without action taken) -> Status switched to UNATTENDED.",
                            norm_name[:50],
                        )
                # 3. Previous UNATTENDED alert
                elif prev_status in ("UNATTENDED", "PTPNEL", "NOUV"):
                    if cls.has_action_taken(prev.get("actions_html"), prev.get("assignee")):
                        new_status = "IN PROGRESS"
                    else:
                        new_status = "UNATTENDED"
                else:
                    new_status = prev_status

                actions_html = prev.get("actions_html") or ""
                assignee = prev.get("assignee") or ""
                due_date = prev.get("due_date") or "-"

                latest_mm_date = cat.get("latest_occurrence_at")
                if not latest_mm_date:
                    occs = cat.get("occurrences") or []
                    if occs:
                        latest_mm_date = occs[0].get("created_at")
                last_seen_date = latest_mm_date or current_date_str

                if new_status == "UNATTENDED":
                    unattended_since = (
                        prev.get("unattended_since")
                        or prev.get("ptpnel_since")
                        or prev.get("nouv_since")
                        or prev.get("last_seen")
                        or current_date_str
                    )
                else:
                    unattended_since = None

                entry = {
                    "slug": slug,
                    "name": norm_name,
                    "raw_name": cat_name,
                    "status": new_status,
                    "count_this_week": count_now,
                    "total_occurrences": new_total,
                    "occurrences_display": f"{count_now} this week",
                    "actions_html": actions_html,
                    "assignee": assignee,
                    "due_date": due_date,
                    "last_seen": last_seen_date,
                    "unattended_since": unattended_since,
                    "ptpnel_since": unattended_since,
                    "nouv_since": unattended_since,
                    "is_active_now": True,
                }
            else:
                # Brand new category never encountered before
                latest_mm_date = cat.get("latest_occurrence_at")
                if not latest_mm_date:
                    occs = cat.get("occurrences") or []
                    if occs:
                        latest_mm_date = occs[0].get("created_at")
                last_seen_date = latest_mm_date or current_date_str

                entry = {
                    "slug": slug,
                    "name": norm_name,
                    "raw_name": cat_name,
                    "status": "NEW",
                    "count_this_week": count_now,
                    "total_occurrences": count_now,
                    "occurrences_display": f"{count_now} this week",
                    "actions_html": "<p><em>To be defined during review meeting</em></p>",
                    "assignee": "",
                    "due_date": "-",
                    "last_seen": last_seen_date,
                    "unattended_since": None,
                    "ptpnel_since": None,
                    "nouv_since": None,
                    "is_active_now": True,
                }

            tracked_categories.append(entry)
            cat["tracking"] = entry

        # Retain existing categories that had zero alerts this week
        for slug, prev in existing_registry.items():
            if slug not in handled_slugs:
                prev_status = prev.get("status", "IN PROGRESS")
                prev_total = prev.get("total_occurrences", 0)

                if prev_status == "NOISE":
                    curr_status = "NOISE"
                elif prev_status in ("NEW", "NOUVELLE"):
                    if cls.has_action_taken(prev.get("actions_html"), prev.get("assignee")):
                        curr_status = "IN PROGRESS"
                    else:
                        curr_status = "UNATTENDED"
                elif prev_status in ("UNATTENDED", "PTPNEL", "NOUV"):
                    if cls.has_action_taken(prev.get("actions_html"), prev.get("assignee")):
                        curr_status = "IN PROGRESS"
                    else:
                        curr_status = "UNATTENDED"
                else:
                    curr_status = prev_status

                unattended_since = (
                    prev.get("unattended_since")
                    or prev.get("ptpnel_since")
                    or prev.get("nouv_since")
                    or prev.get("last_seen")
                    or current_date_str
                    if curr_status == "UNATTENDED"
                    else None
                )

                entry = {
                    "slug": slug,
                    "name": prev.get("name", slug),
                    "raw_name": prev.get("name", slug),
                    "status": curr_status,
                    "count_this_week": 0,
                    "total_occurrences": prev_total,
                    "occurrences_display": "0 this week",
                    "actions_html": prev.get("actions_html") or "",
                    "assignee": prev.get("assignee") or "",
                    "due_date": prev.get("due_date") or "-",
                    "last_seen": prev.get("last_seen") or current_date_str,
                    "unattended_since": unattended_since,
                    "ptpnel_since": unattended_since,
                    "nouv_since": unattended_since,
                    "is_active_now": False,
                }
                tracked_categories.append(entry)

        # Sort: priority rank ascending, then occurrences descending, then name
        tracked_categories.sort(
            key=lambda e: (
                STATUS_RANKS.get(e["status"], 99),
                -e.get("count_this_week", 0),
                -e.get("total_occurrences", 0),
                e.get("name", "").lower(),
            )
        )

        stats = cls.calculate_stats(tracked_categories)
        return tracked_categories, stats

    @classmethod
    def parse_datetime(cls, val: str | None) -> datetime | None:
        """Parses a datetime from a string or Confluence <time> tag."""
        if not val or str(val).strip().lower() in ("-", "previous", "antérieure", "anterieure", "unknown", "inconnue", ""):
            return None

        val_str = str(val).strip()

        # Format Confluence <time datetime="YYYY-MM-DD" />
        m_time = re.search(r'datetime="(\d{4}-\d{2}-\d{2})"', val_str)
        if m_time:
            date_part = m_time.group(1)
            m_hms = re.search(r"(\d{2}):(\d{2})(?::(\d{2}))?", val_str)
            if m_hms:
                hh, mm, ss = m_hms.group(1), m_hms.group(2), m_hms.group(3) or "00"
                try:
                    return datetime.strptime(f"{date_part} {hh}:{mm}:{ss}", "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    pass
            try:
                return datetime.strptime(date_part, "%Y-%m-%d")
            except ValueError:
                pass

        # Format DD/MM/YYYY with optional time
        m_fr = re.search(r"(\d{2})/(\d{2})/(\d{4})(?:(?:\s+[àaat]\s+|\s+)(\d{2}):(\d{2})(?::(\d{2}))?)?", val_str)
        if m_fr:
            day, month, year, hh, mm, ss = m_fr.groups()
            hh = hh or "00"
            mm = mm or "00"
            ss = ss or "00"
            try:
                return datetime.strptime(f"{year}-{month}-{day} {hh}:{mm}:{ss}", "%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass

        # Format ISO YYYY-MM-DD with optional time
        m_iso = re.search(r"(\d{4})-(\d{2})-(\d{2})(?:(?:\s+[àaat]\s+|\s+|T)(\d{2}):(\d{2})(?::(\d{2}))?)?", val_str)
        if m_iso:
            year, month, day, hh, mm, ss = m_iso.groups()
            hh = hh or "00"
            mm = mm or "00"
            ss = ss or "00"
            try:
                return datetime.strptime(f"{year}-{month}-{day} {hh}:{mm}:{ss}", "%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass

        return None

    @staticmethod
    def _add_months(dt: datetime, delta_months: int) -> datetime:
        """Offsets datetime by delta_months calendar months (handles month boundaries)."""
        year = dt.year + (dt.month + delta_months - 1) // 12
        month = (dt.month + delta_months - 1) % 12 + 1
        max_days = calendar.monthrange(year, month)[1]
        return dt.replace(year=year, month=month, day=min(dt.day, max_days))

    @classmethod
    def is_older_than_months(
        cls,
        date_val: str | datetime | None,
        ref_dt: datetime,
        months: int = 1,
    ) -> bool:
        """Returns True if date_val is strictly older than 'months' months relative to ref_dt."""
        if not date_val:
            return False
        if isinstance(date_val, datetime):
            dt = date_val
        else:
            dt = cls.parse_datetime(str(date_val))

        if dt is None:
            return False

        ref_cmp = ref_dt.replace(tzinfo=None) if ref_dt.tzinfo is not None else ref_dt
        dt_cmp = dt.replace(tzinfo=None) if dt.tzinfo is not None else dt
        threshold = cls._add_months(ref_cmp, -months)

        return dt_cmp < threshold

    @classmethod
    def separate_archived_categories(
        cls,
        tracked_categories: list[dict[str, Any]],
        ref_dt: datetime,
        months: int = 1,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Separates active categories from those to archive:
        RESOLVED categories whose last appearance was strictly older than 1 month are moved to archive.
        """
        active: list[dict[str, Any]] = []
        to_archive: list[dict[str, Any]] = []

        for cat in tracked_categories:
            status = cat.get("status", "")
            is_resolved = status in ("RESOLVED", "RÉSOLUE", "RESOLUE")
            last_seen = cat.get("last_seen")

            if is_resolved and cls.is_older_than_months(last_seen, ref_dt, months=months):
                logger.info(
                    "[ARCHIVE] Alert '%s' resolved over %d month(s) ago (last seen: %s) -> Moved to archive.",
                    cat.get("name", "")[:50],
                    months,
                    last_seen,
                )
                to_archive.append(cat)
            else:
                active.append(cat)

        return active, to_archive

    @classmethod
    def check_unattended_duration(
        cls,
        unattended_since: str | datetime | None,
        ref_dt: datetime,
    ) -> tuple[bool, bool, int]:
        """
        Computes elapsed time in UNATTENDED status relative to ref_dt.
        Returns (should_delete, should_warn, days_left):
        - should_delete: True if in UNATTENDED status for > 1 month.
        - should_warn: True if in UNATTENDED status for >= 4 weeks (28 days) and not yet deleted.
        - days_left: remaining days before automatic purge.
        """
        if not unattended_since:
            return False, False, 30

        if isinstance(unattended_since, datetime):
            u_dt = unattended_since
        else:
            u_dt = cls.parse_datetime(str(unattended_since))

        if u_dt is None:
            return False, False, 30

        ref_cmp = ref_dt.replace(tzinfo=None) if ref_dt.tzinfo else ref_dt
        u_cmp = u_dt.replace(tzinfo=None) if u_dt.tzinfo else u_dt

        del_date = cls._add_months(u_cmp, 1)
        days_in_unattended = (ref_cmp.date() - u_cmp.date()).days
        days_left = (del_date.date() - ref_cmp.date()).days

        should_delete = ref_cmp >= del_date or days_left <= 0
        should_warn = not should_delete and days_in_unattended >= 28

        return should_delete, should_warn, max(1, days_left)

    check_ptpnel_duration = check_unattended_duration
    check_nouv_duration = check_unattended_duration

    @classmethod
    def filter_and_tag_unattended_categories(
        cls,
        tracked_categories: list[dict[str, Any]],
        ref_dt: datetime,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Filters and tags UNATTENDED alerts:
        - At 4 weeks: displays countdown warning (e.g. ⚠️ Purge in D-X).
        - At > 1 month: automatically purges line from active Confluence tracking.
        """
        active: list[dict[str, Any]] = []
        deleted: list[dict[str, Any]] = []

        for cat in tracked_categories:
            status = cat.get("status", "")
            if status in ("UNATTENDED", "PTPNEL", "NOUV"):
                u_since = cat.get("unattended_since") or cat.get("ptpnel_since") or cat.get("nouv_since")
                should_delete, should_warn, days_left = cls.check_unattended_duration(u_since, ref_dt)

                if should_delete:
                    logger.info(
                        "[PURGE] Alert '%s' remained UNATTENDED for over 1 month without action -> Purged from Confluence.",
                        cat.get("name", "")[:50],
                    )
                    deleted.append({
                        "slug": cat.get("slug", ""),
                        "name": cat.get("name", ""),
                        "deleted_at": ref_dt.strftime("%Y-%m-%d"),
                    })
                    continue

                if should_warn:
                    cat["unattended_warning"] = f"⚠️ Purge scheduled in {days_left}d"
                    cat["ptpnel_warning"] = cat["unattended_warning"]
                    cat["nouv_warning"] = cat["unattended_warning"]

            active.append(cat)

        return active, deleted

    filter_and_tag_ptpnel_categories = filter_and_tag_unattended_categories
    filter_and_tag_nouv_categories = filter_and_tag_unattended_categories

    @classmethod
    def parse_deleted_unattended_history(cls, expand_html: str) -> list[dict[str, str]]:
        """Parses deleted unattended/ptpnel history table from Confluence storage."""
        history: list[dict[str, str]] = []
        if not expand_html:
            return history
        soup = BeautifulSoup(expand_html, "html.parser")
        table = soup.find("table")
        if not table:
            return history
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) >= 2:
                name = cells[0].get_text(strip=True)
                date_str = cells[1].get_text(strip=True)
                if name:
                    history.append({"name": name, "deleted_at": date_str})
        return history

    parse_deleted_ptpnel_history = parse_deleted_unattended_history

    @classmethod
    def update_deleted_unattended_history(
        cls,
        existing: list[dict[str, str]],
        newly_deleted: list[dict[str, str]],
        ref_dt: datetime,
    ) -> list[dict[str, str]]:
        """Updates deleted history, purging entries older than 1 month."""
        combined = list(existing)
        for item in newly_deleted:
            combined.append({
                "name": item.get("name", ""),
                "deleted_at": item.get("deleted_at", ref_dt.strftime("%Y-%m-%d")),
            })
        valid: list[dict[str, str]] = []
        for item in combined:
            del_at = item.get("deleted_at", "")
            if not cls.is_older_than_months(del_at, ref_dt, months=1):
                valid.append(item)
        return valid

    update_deleted_ptpnel_history = update_deleted_unattended_history

    @classmethod
    def calculate_stats(
        cls,
        categories: list[dict[str, Any]],
        archived_count: int = 0,
        deleted_unattended_count: int = 0,
        deleted_ptpnel_count: int = 0,
    ) -> dict[str, int]:
        """Computes summary KPI metrics for active categories."""
        effective_purged = deleted_unattended_count or deleted_ptpnel_count

        stats: dict[str, int] = {
            "ACTIVE_THIS_WEEK": 0,
            "TOTAL": len(categories),
            "NEW": 0,
            "UNATTENDED": 0,
            "IN PROGRESS": 0,
            "RECURRING": 0,
            "RESOLVED": 0,
            "NOISE": 0,
            "ARCHIVED": archived_count,
            "UNATTENDED_PURGED": effective_purged,
            # Backward-compatible French aliases for existing templates/tests
            "NOUVELLE": 0,
            "PTPNEL": 0,
            "EN COURS": 0,
            "RÉCURRENTE": 0,
            "RÉSOLUE": 0,
            "BRUIT": 0,
            "PTPNEL_PURGED": effective_purged,
            "NOUV": 0,
            "SANS_ACTION": effective_purged,
        }

        for cat in categories:
            if cat.get("is_active_now") or cat.get("count_this_week", 0) > 0:
                stats["ACTIVE_THIS_WEEK"] += 1

            status = cls._normalize_status(cat.get("status", "NEW"))

            if status == "NEW":
                stats["NEW"] += 1
                stats["NOUVELLE"] += 1
            elif status == "UNATTENDED":
                stats["UNATTENDED"] += 1
                stats["PTPNEL"] += 1
                stats["NOUV"] += 1
            elif status == "IN PROGRESS":
                stats["IN PROGRESS"] += 1
                stats["EN COURS"] += 1
            elif status == "RECURRING":
                stats["RECURRING"] += 1
                stats["RÉCURRENTE"] += 1
            elif status == "RESOLVED":
                stats["RESOLVED"] += 1
                stats["RÉSOLUE"] += 1
            elif status == "NOISE":
                stats["NOISE"] += 1
                stats["BRUIT"] += 1

        return stats

    @classmethod
    def _build_status_palette_html(cls) -> str:
        """Builds quick copy/paste status lozenge palette panel for Confluence page header."""
        return (
            '<ac:structured-macro ac:name="panel">'
            '<ac:parameter ac:name="title">📋 Status Palette (Quick Copy / Paste in Edit Mode)</ac:parameter>'
            '<ac:rich-text-body>'
            '<p style="margin: 0 0 6px 0; font-size: 12px; color: #42526e;">'
            '<em>Tip: In Confluence edit mode, copy (Ctrl+C) and paste (Ctrl+V) these official badges directly into the Status column:</em>'
            '</p>'
            '<table style="border: none; border-collapse: collapse; margin: 0; font-size: 12px;">'
            '<tbody>'
            '<tr style="border: none;">'
            '<td style="border: none; padding: 4px 10px 4px 0;">'
            '<ac:structured-macro ac:name="status"><ac:parameter ac:name="title">IN PROGRESS</ac:parameter><ac:parameter ac:name="colour">Yellow</ac:parameter></ac:structured-macro>'
            '</td>'
            '<td style="border: none; padding: 4px 16px 4px 4px; color: #42526e;">Action underway + designated owner</td>'
            '<td style="border: none; padding: 4px 10px 4px 0;">'
            '<ac:structured-macro ac:name="status"><ac:parameter ac:name="title">RESOLVED</ac:parameter><ac:parameter ac:name="colour">Green</ac:parameter></ac:structured-macro>'
            '</td>'
            '<td style="border: none; padding: 4px 16px 4px 4px; color: #42526e;">Fix validated in production</td>'
            '<td style="border: none; padding: 4px 10px 4px 0;">'
            '<ac:structured-macro ac:name="status"><ac:parameter ac:name="title">NEW</ac:parameter><ac:parameter ac:name="colour">Blue</ac:parameter></ac:structured-macro>'
            '</td>'
            '<td style="border: none; padding: 4px 16px 4px 4px; color: #42526e;">First detection (script)</td>'
            '</tr>'
            '<tr style="border: none;">'
            '<td style="border: none; padding: 4px 10px 4px 0;">'
            '<ac:structured-macro ac:name="status"><ac:parameter ac:name="title">UNATTENDED</ac:parameter><ac:parameter ac:name="colour">Grey</ac:parameter></ac:structured-macro>'
            '</td>'
            '<td style="border: none; padding: 4px 16px 4px 4px; color: #42526e;">Awaiting team triage (warning at 4w)</td>'
            '<td style="border: none; padding: 4px 10px 4px 0;">'
            '<ac:structured-macro ac:name="status"><ac:parameter ac:name="title">RECURRING</ac:parameter><ac:parameter ac:name="colour">Red</ac:parameter></ac:structured-macro>'
            '</td>'
            '<td style="border: none; padding: 4px 16px 4px 4px; color: #42526e;">Resolved alert re-fired (script)</td>'
            '<td style="border: none; padding: 4px 10px 4px 0;">'
            '<span style="background-color: #795548; color: #ffffff; padding: 2px 8px; border-radius: 3px; font-weight: bold; font-size: 11px;">NOISE</span>'
            '</td>'
            '<td style="border: none; padding: 4px 16px 4px 4px; color: #42526e;">Known harmless alert (dedicated table)</td>'
            '</tr>'
            '</tbody>'
            '</table>'
            '</ac:rich-text-body>'
            '</ac:structured-macro>'
        )

    @classmethod
    def _build_confluence_row_html(cls, cat: dict[str, Any]) -> str:
        """Builds an XHTML row for Confluence active table (7 columns)."""
        slug = cat.get("slug", "category")
        name = html.escape(cat.get("name", "Alert"))
        status = cls._normalize_status(cat.get("status", "NEW"))
        color = STATUS_COLORS.get(status, "Grey")

        occurrences_display = html.escape(str(cat.get("occurrences_display") or f"{cat.get('count_this_week', 0)} this week"))
        assignee = html.escape(cat.get("assignee") or "-")

        raw_due = cat.get("due_date") or "-"
        due_date_html = cls.format_confluence_date_cell(raw_due)

        raw_last = cat.get("last_seen") or ""
        date_cell_html = cls.format_confluence_date_cell(raw_last)

        actions_html = cat.get("actions_html") or "<p><em>To be defined during review meeting</em></p>"

        if status == "NOISE":
            status_parts = [
                '<span style="background-color: #795548; color: #ffffff; padding: 2px 8px; border-radius: 3px; font-weight: bold; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; display: inline-block;">'
                'NOISE'
                '</span>'
            ]
        else:
            status_parts = [
                '<ac:structured-macro ac:name="status">',
                f'<ac:parameter ac:name="title">{html.escape(status)}</ac:parameter>',
                f'<ac:parameter ac:name="colour">{color}</ac:parameter>',
                '</ac:structured-macro>',
            ]

        if status == "UNATTENDED":
            warn = cat.get("unattended_warning") or cat.get("ptpnel_warning") or cat.get("nouv_warning")
            since = cat.get("unattended_since") or cat.get("ptpnel_since") or cat.get("nouv_since")
            if warn:
                status_parts.append(
                    f'<div style="margin-top: 4px; font-size: 11px; line-height: 1.2; color: #c0392b; font-weight: bold;">'
                    f'{html.escape(warn)}'
                    f'</div>'
                )
            if since:
                since_cell = cls.format_confluence_date_cell(since)
                status_parts.append(
                    f'<div style="margin-top: 2px; font-size: 10px; color: #7f8c8d;">'
                    f'(UNATTENDED since {since_cell})'
                    f'</div>'
                )

        return (
            f'<tr>'
            f'<td>{"".join(status_parts)}</td>'
            f'<td>'
            f'<ac:structured-macro ac:name="anchor">'
            f'<ac:parameter ac:name="">{slug}</ac:parameter>'
            f'</ac:structured-macro>'
            f'<strong>{name}</strong>'
            f'</td>'
            f'<td>{occurrences_display}</td>'
            f'<td>{date_cell_html}</td>'
            f'<td>{assignee}</td>'
            f'<td>{due_date_html}</td>'
            f'<td>{actions_html}</td>'
            f'</tr>'
        )

    @classmethod
    def _build_confluence_table_html(
        cls,
        categories: list[dict[str, Any]],
        empty_message: str = "No alerts.",
    ) -> str:
        """Builds standard Confluence alert table structure (7 columns)."""
        parts = [
            '<table class="wrapped">',
            '<colgroup>',
            '<col style="width: 120px;"/>',
            '<col style="width: 320px;"/>',
            '<col style="width: 120px;"/>',
            '<col style="width: 180px;"/>',
            '<col style="width: 130px;"/>',
            '<col style="width: 130px;"/>',
            '<col style="width: 380px;"/>',
            '</colgroup>',
            '<thead><tr>',
            '<th>Status</th>',
            '<th>Alert Category</th>',
            '<th>Occurrences</th>',
            '<th>Last Seen in Mattermost</th>',
            '<th>Assignee</th>',
            '<th>Due Date</th>',
            '<th>Action Items (Review Meeting)</th>',
            '</tr></thead>',
            '<tbody>',
        ]
        if categories:
            for cat in categories:
                parts.append(cls._build_confluence_row_html(cat))
        else:
            parts.append(f'<tr><td colspan="7"><em>{empty_message}</em></td></tr>')
        parts.append('</tbody></table>')
        return "".join(parts)

    @classmethod
    def build_confluence_storage_html(
        cls,
        tracked_categories: list[dict[str, Any]],
        stats: dict[str, int],
        sync_date_str: str,
        artifact_url: str | None = None,
        artifact_browse_url: str | None = None,
        archive_page_url: str | None = None,
        archived_count: int = 0,
        deleted_nouv_history: list[dict[str, str]] | None = None,
        stats_page_url: str | None = None,
        deleted_ptpnel_history: list[dict[str, str]] | None = None,
        deleted_unattended_history: list[dict[str, str]] | None = None,
        **kwargs: Any,
    ) -> str:
        """
        Generates Confluence storage format (XHTML storage) for the active page.
        Includes summary header banner, GitLab report links, interactive status macros,
        anchors for each category, main active table, and secondary noise table.
        """
        parts: list[str] = []

        main_categories = [cat for cat in tracked_categories if cls._normalize_status(cat.get("status", "")) != "NOISE"]
        noise_categories = [cat for cat in tracked_categories if cls._normalize_status(cat.get("status", "")) == "NOISE"]

        quick_links: list[str] = []
        if artifact_url:
            browse_part = f' (<a href="{html.escape(artifact_browse_url)}">browse 📂</a>)' if artifact_browse_url else ""
            quick_links.append(f'📊 <a href="{html.escape(artifact_url)}">Latest Visual HTML Report ↗</a>{browse_part}')
        if archive_page_url:
            count_str = f" ({archived_count})" if archived_count > 0 else ""
            quick_links.append(f'📦 <a href="{html.escape(archive_page_url)}">Archive &gt; 1 month{count_str} ↗</a>')
        if stats_page_url:
            quick_links.append(f'📈 <a href="{html.escape(stats_page_url)}">Weekly Statistics ↗</a>')

        quick_links_html = (
            f'<p style="margin: 6px 0 2px 0;"><strong>Quick Links:</strong> '
            f'{" &#160;&#8226;&#160; ".join(quick_links)}</p>'
            if quick_links
            else ""
        )

        execution_line = f'Last execution: <strong>{sync_date_str}</strong>.<br/>'

        parts.append(
            f'<ac:structured-macro ac:name="info">'
            f'<ac:rich-text-body>'
            f'<p><strong>📋 Weekly Mattermost Alert Tracking and Team Action Plan</strong></p>'
            f'<p>'
            f'{execution_line}'
            f'Active categories this week: <strong>{stats.get("ACTIVE_THIS_WEEK", 0)}</strong> &#8226; Total tracked: <strong>{stats.get("TOTAL", 0)}</strong><br/>'
            f'🔹 <strong>{stats.get("NEW", stats.get("NOUVELLE", 0))}</strong> New &#160;|&#160; '
            f'⚪ <strong>{stats.get("UNATTENDED", stats.get("PTPNEL", 0))}</strong> Unattended &#160;|&#160; '
            f'🔸 <strong>{stats.get("IN PROGRESS", stats.get("EN COURS", 0))}</strong> In Progress &#160;|&#160; '
            f'🔺 <strong>{stats.get("RECURRING", stats.get("RÉCURRENTE", 0))}</strong> Recurring &#160;|&#160; '
            f'✅ <strong>{stats.get("RESOLVED", stats.get("RÉSOLUE", 0))}</strong> Resolved &#160;|&#160; '
            f'🟤 <strong>{stats.get("NOISE", stats.get("BRUIT", 0))}</strong> Noise'
            f'</p>'
            f'{quick_links_html}'
            f'<ac:structured-macro ac:name="expand">'
            f'<ac:parameter ac:name="title">💡 Workflow Guide and Review Rules (click to expand)</ac:parameter>'
            f'<ac:rich-text-body>'
            f'<p><strong>📊 Alert Lifecycle Diagram:</strong></p>'
            f'<ac:structured-macro ac:name="code">'
            f'<ac:parameter ac:name="title">Status Workflow</ac:parameter>'
            f'<ac:plain-text-body><![CDATA['
            f'             ┌───────────────────── Initial Detection (Week W) ─────────────────────┐\n'
            f'             │                                                                      │\n'
            f'             ▼                                                                      ▼\n'
            f'       [ 🔹 NEW ]                                                            [ 🔺 RECURRING ]\n'
            f'             │                                                                      ▲\n'
            f'   ┌─────────┴───────────────────────┐                                              │\n'
            f'   │ No action taken                 │ Action defined / Assignee                    │\n'
            f'   ▼                                 ▼                                              │\n'
            f'[ ⚪ UNATTENDED ] ──────────► [ 🔸 IN PROGRESS ] ──(Fix validated)──► [ ✅ RESOLVED ]│\n'
            f'   │                                 │                                      │       │\n'
            f'   │  After 4 weeks                  │ (Manually assigned)                  │ > 1 mo│\n'
            f'   ├─► ⚠️ Warning (D-X)             ▼                                      ▼       │\n'
            f'   │                            [ 🟤 NOISE ] (Dedicated table)      [ 📦 ARCHIVE ] ─┘\n'
            f'   │  Over 1 month                                                          (Re-opens on return)\n'
            f'   ▼\n'
            f'[ 🗑️ Permanent purge ]\n'
            f']]></ac:plain-text-body>'
            f'</ac:structured-macro>'
            f'<p><strong>📋 Meeting Triage Steps:</strong></p>'
            f'<ul>'
            f'<li><strong>1. Nominal Cycle (New Issue):</strong>'
            f'<ul>'
            f'<li><ac:structured-macro ac:name="status"><ac:parameter ac:name="title">NEW</ac:parameter><ac:parameter ac:name="colour">Blue</ac:parameter></ac:structured-macro>: '
            f'First detection. Investigate root cause, document action, and assign an <strong>Owner</strong>.</li>'
            f'<li><ac:structured-macro ac:name="status"><ac:parameter ac:name="title">UNATTENDED</ac:parameter><ac:parameter ac:name="colour">Grey</ac:parameter></ac:structured-macro>: '
            f'Previous alert still awaiting triage. <em>Warning shown at 4 weeks; automatically purged after 1 month.</em></li>'
            f'<li>➔ <em>Take ownership:</em> Switch to <ac:structured-macro ac:name="status"><ac:parameter ac:name="title">IN PROGRESS</ac:parameter><ac:parameter ac:name="colour">Yellow</ac:parameter></ac:structured-macro> once action starts.</li>'
            f'<li>➔ <em>Resolution:</em> Switch to <ac:structured-macro ac:name="status"><ac:parameter ac:name="title">RESOLVED</ac:parameter><ac:parameter ac:name="colour">Green</ac:parameter></ac:structured-macro> once fix is deployed. '
            f'<em>Automatically moved to Archive page after 1 month without recurring.</em></li>'
            f'</ul>'
            f'</li>'
            f'<li><strong>2. Regression Cycle (Re-opened issue):</strong>'
            f'<ul>'
            f'<li><ac:structured-macro ac:name="status"><ac:parameter ac:name="title">RECURRING</ac:parameter><ac:parameter ac:name="colour">Red</ac:parameter></ac:structured-macro>: '
            f'<em>Automatic switch</em> if a resolved or archived alert fires again. Triage with high priority ➔ switch to <ac:structured-macro ac:name="status"><ac:parameter ac:name="title">IN PROGRESS</ac:parameter><ac:parameter ac:name="colour">Yellow</ac:parameter></ac:structured-macro>.</li>'
            f'</ul>'
            f'</li>'
            f'<li><strong>3. Observation Cycle (0 occurrences this week):</strong>'
            f'<ul>'
            f'<li>Record is preserved. Switch to <ac:structured-macro ac:name="status"><ac:parameter ac:name="title">RESOLVED</ac:parameter><ac:parameter ac:name="colour">Green</ac:parameter></ac:structured-macro> if fix confirmed, or keep IN PROGRESS for continued observation.</li>'
            f'</ul>'
            f'</li>'
            f'<li><strong>4. Noise Alerts (Known Harmless):</strong>'
            f'<ul>'
            f'<li><span style="background-color: #795548; color: #ffffff; padding: 2px 8px; border-radius: 3px; font-weight: bold; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; display: inline-block;">NOISE</span>: '
            f'Manually assigned by team. For known harmless alerts that cannot be easily silenced at the source. '
            f'<em>These alerts are automatically isolated into the secondary noise table below.</em></li>'
            f'</ul>'
            f'</li>'
            f'<li><strong>5. False Alarms / Maintenance:</strong>'
            f'<ul>'
            f'<li>Switch directly to <ac:structured-macro ac:name="status"><ac:parameter ac:name="title">RESOLVED</ac:parameter><ac:parameter ac:name="colour">Green</ac:parameter></ac:structured-macro> with note in actions column (e.g. <em>False positive - threshold adjusted</em>).</li>'
            f'</ul>'
            f'</li>'
            f'</ul>'
            f'</ac:rich-text-body>'
            f'</ac:structured-macro>'
            f'</ac:rich-text-body>'
            f'</ac:structured-macro>'
        )

        # 2. Review Meeting To-Do Checklist
        parts.append(
            '<ac:structured-macro ac:name="panel">'
            '<ac:parameter ac:name="title">📋 Review Meeting Action Checklist</ac:parameter>'
            '<ac:rich-text-body>'
            '<ul style="margin: 0; padding-left: 20px; line-height: 1.6;">'
            '<li><strong>1. Triage 🔺 Recurring:</strong> Investigate regression ➔ Assign owner ➔ <ac:structured-macro ac:name="status"><ac:parameter ac:name="title">IN PROGRESS</ac:parameter><ac:parameter ac:name="colour">Yellow</ac:parameter></ac:structured-macro></li>'
            '<li><strong>2. Triage 🔹 New:</strong> Define action + owner ➔ <ac:structured-macro ac:name="status"><ac:parameter ac:name="title">IN PROGRESS</ac:parameter><ac:parameter ac:name="colour">Yellow</ac:parameter></ac:structured-macro> <em>(or <span style="background-color: #795548; color: #ffffff; padding: 2px 8px; border-radius: 3px; font-weight: bold; font-size: 11px;">NOISE</span> if harmless)</em></li>'
            '<li><strong>3. Review ⚪ Unattended ⚠️ (D-X):</strong> Take ownership ➔ <ac:structured-macro ac:name="status"><ac:parameter ac:name="title">IN PROGRESS</ac:parameter><ac:parameter ac:name="colour">Yellow</ac:parameter></ac:structured-macro> <em>(otherwise <span style="background-color: #795548; color: #ffffff; padding: 2px 8px; border-radius: 3px; font-weight: bold; font-size: 11px;">NOISE</span> or auto-purged at 1 mo)</em></li>'
            '<li><strong>4. Close 🔸 In Progress items:</strong> Fix verified in production ➔ <ac:structured-macro ac:name="status"><ac:parameter ac:name="title">RESOLVED</ac:parameter><ac:parameter ac:name="colour">Green</ac:parameter></ac:structured-macro> <em>(auto-archived after 1 mo)</em></li>'
            '</ul>'
            '</ac:rich-text-body>'
            '</ac:structured-macro>'
        )

        # 3. Status Palette Panel
        parts.append(cls._build_status_palette_html())

        # 4. Main Active Alert Table
        parts.append('<h2>📋 Active Alert Review Register</h2>')
        parts.append(cls._build_confluence_table_html(main_categories, empty_message="No active alerts this week."))

        # 5. Secondary Noise Table
        parts.append('<h2>🟤 Known Incompressible Noise Alerts</h2>')
        parts.append(
            '<p><em>These recurring alerts have been classified as noise. '
            'They are tracked here separately to keep the main review register focused:</em></p>'
        )
        parts.append(cls._build_confluence_table_html(noise_categories, empty_message="No alerts classified as noise."))

        return "".join(parts)

    @classmethod
    def build_confluence_archive_storage_html(
        cls,
        archived_categories: list[dict[str, Any]],
        sync_date_str: str,
        main_page_url: str | None = None,
    ) -> str:
        """
        Builds Confluence storage XHTML for the historical archive page (6 columns without status).
        """
        parts: list[str] = []

        main_link_html = ""
        if main_page_url:
            main_link_html = (
                f'<p style="margin: 6px 0;">📋 <strong>Active Board:</strong> '
                f'<a href="{html.escape(main_page_url)}">View active Confluence review board ↗</a></p>'
            )

        parts.append(
            f'<ac:structured-macro ac:name="info">'
            f'<ac:rich-text-body>'
            f'<p><strong>📦 Archive of Review Decisions for Alerts Resolved &gt; 1 Month</strong></p>'
            f'<p>Last execution: <strong>{sync_date_str}</strong>.<br/>'
            f'Total archived alerts: <strong>{len(archived_categories)}</strong></p>'
            f'{main_link_html}'
            f'</ac:rich-text-body>'
            f'</ac:structured-macro>'
        )

        parts.append(
            '<table class="wrapped">'
            '<colgroup>'
            '<col style="width: 320px;"/>'
            '<col style="width: 120px;"/>'
            '<col style="width: 180px;"/>'
            '<col style="width: 130px;"/>'
            '<col style="width: 130px;"/>'
            '<col style="width: 380px;"/>'
            '</colgroup>'
            '<thead><tr>'
            '<th>Alert Category</th>'
            '<th>Occurrences</th>'
            '<th>Last Seen in Mattermost</th>'
            '<th>Assignee</th>'
            '<th>Due Date</th>'
            '<th>Action Items (Review Meeting)</th>'
            '</tr></thead>'
            '<tbody>'
        )

        if archived_categories:
            for cat in archived_categories:
                slug = cat.get("slug", "category")
                name = html.escape(cat.get("name", "Alert"))
                occurrences_display = html.escape(str(cat.get("occurrences_display") or f"{cat.get('count_this_week', 0)} this week"))
                assignee = html.escape(cat.get("assignee") or "-")
                due_date_html = cls.format_confluence_date_cell(cat.get("due_date") or "-")
                date_cell_html = cls.format_confluence_date_cell(cat.get("last_seen") or "")
                actions_html = cat.get("actions_html") or "<p><em>-</em></p>"

                parts.append(
                    f'<tr>'
                    f'<td>'
                    f'<ac:structured-macro ac:name="anchor">'
                    f'<ac:parameter ac:name="">{slug}</ac:parameter>'
                    f'</ac:structured-macro>'
                    f'<strong>{name}</strong>'
                    f'</td>'
                    f'<td>{occurrences_display}</td>'
                    f'<td>{date_cell_html}</td>'
                    f'<td>{assignee}</td>'
                    f'<td>{due_date_html}</td>'
                    f'<td>{actions_html}</td>'
                    f'</tr>'
                )
        else:
            parts.append('<tr><td colspan="6"><em>No archived alerts.</em></td></tr>')

        parts.append('</tbody></table>')
        return "".join(parts)

    @classmethod
    def append_weekly_stats_row(
        cls,
        storage_html: str,
        stats: dict[str, int],
        sync_date_str: str,
        total_alerts: int = 0,
        main_page_url: str | None = None,
        report_filename: str | None = None,
        artifact_url: str | None = None,
    ) -> str:
        """
        Appends the current week metrics and HTML report attachment into the weekly stats table.
        """
        if report_filename:
            report_cell = (
                f'<ac:link>'
                f'<ri:attachment ri:filename="{html.escape(report_filename)}" />'
                f'<ac:plain-text-link-body><![CDATA[📎 {report_filename}]]></ac:plain-text-link-body>'
                f'</ac:link>'
            )
            if artifact_url:
                report_cell += (
                    f'<br/><small><a href="{html.escape(artifact_url)}">GitLab Artifact ↗</a></small>'
                )
        elif artifact_url:
            report_cell = f'<a href="{html.escape(artifact_url)}">📊 HTML Report (Artifact) ↗</a>'
        else:
            report_cell = "-"

        row_html = (
            f'<tr>'
            f'<td>{cls.format_confluence_date_cell(sync_date_str)}</td>'
            f'<td><strong>{total_alerts}</strong></td>'
            f'<td><strong>{stats.get("ACTIVE_THIS_WEEK", 0)}</strong></td>'
            f'<td>{stats.get("TOTAL", 0)}</td>'
            f'<td><ac:structured-macro ac:name="status"><ac:parameter ac:name="title">{stats.get("NEW", stats.get("NOUVELLE", 0))}</ac:parameter><ac:parameter ac:name="colour">Blue</ac:parameter></ac:structured-macro></td>'
            f'<td><ac:structured-macro ac:name="status"><ac:parameter ac:name="title">{stats.get("UNATTENDED", stats.get("PTPNEL", 0))}</ac:parameter><ac:parameter ac:name="colour">Grey</ac:parameter></ac:structured-macro></td>'
            f'<td><ac:structured-macro ac:name="status"><ac:parameter ac:name="title">{stats.get("IN PROGRESS", stats.get("EN COURS", 0))}</ac:parameter><ac:parameter ac:name="colour">Yellow</ac:parameter></ac:structured-macro></td>'
            f'<td><ac:structured-macro ac:name="status"><ac:parameter ac:name="title">{stats.get("RECURRING", stats.get("RÉCURRENTE", 0))}</ac:parameter><ac:parameter ac:name="colour">Red</ac:parameter></ac:structured-macro></td>'
            f'<td><ac:structured-macro ac:name="status"><ac:parameter ac:name="title">{stats.get("RESOLVED", stats.get("RÉSOLUE", 0))}</ac:parameter><ac:parameter ac:name="colour">Green</ac:parameter></ac:structured-macro></td>'
            f'<td><span style="background-color: #795548; color: #ffffff; padding: 2px 8px; border-radius: 3px; font-weight: bold; font-size: 11px; display: inline-block;">{stats.get("NOISE", stats.get("BRUIT", 0))}</span></td>'
            f'<td><ac:structured-macro ac:name="status"><ac:parameter ac:name="title">{stats.get("UNATTENDED_PURGED", stats.get("PTPNEL_PURGED", 0))}</ac:parameter><ac:parameter ac:name="colour">Grey</ac:parameter></ac:structured-macro></td>'
            f'<td>{report_cell}</td>'
            f'</tr>'
        )

        soup = BeautifulSoup(storage_html or "", "html.parser")
        table = soup.find("table")

        if not table:
            main_link_html = ""
            if main_page_url:
                main_link_html = (
                    f'<p style="margin: 6px 0;">📋 <strong>Review Dashboard:</strong> '
                    f'<a href="{html.escape(main_page_url)}">View main review and tracking page ↗</a></p>'
                )

            return (
                f'<ac:structured-macro ac:name="info">'
                f'<ac:rich-text-body>'
                f'<p><strong>📊 Weekly Mattermost Alert Metrics Log</strong></p>'
                f'<p>This table is automatically updated on every weekly pipeline run to track evolution over time.</p>'
                f'{main_link_html}'
                f'</ac:rich-text-body>'
                f'</ac:structured-macro>'
                f'<table class="wrapped">'
                f'<colgroup>'
                f'<col style="width: 170px;"/>'
                f'<col style="width: 110px;"/>'
                f'<col style="width: 120px;"/>'
                f'<col style="width: 120px;"/>'
                f'<col style="width: 100px;"/>'
                f'<col style="width: 100px;"/>'
                f'<col style="width: 100px;"/>'
                f'<col style="width: 100px;"/>'
                f'<col style="width: 100px;"/>'
                f'<col style="width: 100px;"/>'
                f'<col style="width: 160px;"/>'
                f'<col style="width: 220px;"/>'
                f'</colgroup>'
                f'<thead><tr>'
                f'<th>Execution Date</th>'
                f'<th>Total Alerts</th>'
                f'<th>Active Categories</th>'
                f'<th>Total Categories</th>'
                f'<th>New (🔹)</th>'
                f'<th>Unattended (⚪)</th>'
                f'<th>In Progress (🔸)</th>'
                f'<th>Recurring (🔺)</th>'
                f'<th>Resolved (✅)</th>'
                f'<th>Noise (🟤)</th>'
                f'<th>Unattended Purged (&gt; 1 mo) (🗑️)</th>'
                f'<th>HTML Report (Attachment)</th>'
                f'</tr></thead>'
                f'<tbody>'
                f'{row_html}'
                f'</tbody></table>'
            )

        tbody = table.find("tbody")
        if tbody:
            new_row_soup = BeautifulSoup(row_html, "html.parser").find("tr")
            if new_row_soup:
                tbody.append(new_row_soup)

        return str(soup)

    @classmethod
    def synchronize_confluence(
        cls,
        confluence_config: dict[str, Any],
        categories: list[dict[str, Any]],
        alerts: list[dict[str, Any]],
        current_date_str: str,
        app_tz: tzinfo | None = None,
        gitlab_artifact_url: str | None = None,
        gitlab_artifact_browse_url: str | None = None,
        client_class: Any | None = None,
        render_html_callback: Any | None = None,
    ) -> tuple[str | None, dict[str, int]]:
        """
        Coordinates full bidirectional Confluence synchronization:
        1. Reads active tracking and archive pages.
        2. Reconciles state machine (NEW, UNATTENDED, IN PROGRESS, RECURRING, RESOLVED, NOISE).
        3. Moves resolved alerts > 1 month to archive page.
        4. Updates weekly statistics page and attaches HTML report.
        5. Updates active Confluence review board.
        """
        confluence_url = confluence_config.get("url") or ""
        confluence_token = confluence_config.get("token")
        confluence_page_id = confluence_config.get("page_id")
        confluence_archive_page_id = confluence_config.get("archive_page_id") or "123456780"
        confluence_stats_page_id = confluence_config.get("stats_page_id") or "123456781"

        if confluence_config.get("disabled"):
            logger.info(
                "[CONFLUENCE] Confluence synchronization disabled (CONFLUENCE_DISABLED=true in .env)."
            )
            return None, {}

        if not confluence_token or not confluence_page_id:
            logger.warning(
                "[CONFLUENCE] Confluence tracking enabled but CONFLUENCE_TOKEN or "
                "CONFLUENCE_PAGE_ID missing in .env. Skipping synchronization."
            )
            return None, {}

        confluence_page_url: str | None = None
        tracking_stats: dict[str, int] = {}

        try:
            if client_class is None:
                from clients.confluence_client import ConfluenceClient
                client_class = ConfluenceClient

            logger.info("[CONFLUENCE] Synchronizing with Confluence registry...")
            with client_class(
                url=confluence_url,
                token=confluence_token,
                page_id=confluence_page_id,
            ) as conf_client:
                # 1. Active tracking page
                page_data = conf_client.get_page()
                confluence_page_url = conf_client.build_page_url(page_data)
                storage_html = page_data.get("body", {}).get("storage", {}).get("value", "")
                version_num = page_data.get("version", {}).get("number", 1)
                page_title = page_data.get("title", "Alert Analysis")
                space_key = page_data.get("space", {}).get("key", "ALERTS")

                existing_registry = cls.parse_confluence_storage(storage_html)

                # 2. Archive page (resolved alerts > 1 month)
                archive_page_data = None
                archive_registry: dict[str, dict[str, Any]] = {}
                archive_page_url: str | None = None
                archive_page_title = "Archive of Review Decisions for Alerts Resolved > 1 Month"
                archive_space_key = "ALERTS"
                archive_version_num = 1

                if confluence_archive_page_id:
                    try:
                        archive_page_data = conf_client.get_page(page_id=confluence_archive_page_id)
                        archive_page_url = conf_client.build_page_url(archive_page_data)
                        archive_storage_raw = (
                            archive_page_data.get("body", {}).get("storage", {}).get("value", "")
                        )
                        archive_version_num = archive_page_data.get("version", {}).get("number", 1)
                        archive_page_title = archive_page_data.get("title", archive_page_title)
                        archive_space_key = archive_page_data.get("space", {}).get("key", "ALERTS")
                        archive_registry = cls.parse_confluence_storage(archive_storage_raw)
                        logger.info(
                            "[ARCHIVE] %d archived categories loaded from Confluence archive page.",
                            len(archive_registry),
                        )
                    except Exception as err_arch:
                        logger.warning(
                            "[ARCHIVE] Could not read archive page %s (%s). Proceeding without archive merge.",
                            confluence_archive_page_id,
                            err_arch,
                        )

                combined_registry = dict(archive_registry)
                combined_registry.update(existing_registry)

                # 3. Reconcile categories with registry
                tracked, _ = cls.reconcile(
                    categories=categories,
                    existing_registry=combined_registry,
                    current_date_str=current_date_str,
                )

                # Reference date for aging checks
                ref_dt = datetime.now(tz=app_tz)

                # 4. Lifecycle management: archiving and unattended purge
                active_categories, to_archive_categories = cls.separate_archived_categories(
                    tracked,
                    ref_dt=ref_dt,
                    months=1,
                )

                active_categories, deleted_unattended = cls.filter_and_tag_unattended_categories(
                    active_categories,
                    ref_dt=ref_dt,
                )

                tracking_stats = cls.calculate_stats(
                    active_categories,
                    archived_count=len(archive_registry) + len(to_archive_categories),
                    deleted_unattended_count=len(deleted_unattended),
                )

                # 5. Update archive page if needed
                if confluence_archive_page_id and to_archive_categories:
                    try:
                        updated_archive_dict = dict(archive_registry)
                        for cat in to_archive_categories:
                            updated_archive_dict[cat["slug"]] = cat

                        all_archived_list = list(updated_archive_dict.values())
                        all_archived_list.sort(key=lambda c: c.get("name", "").lower())

                        new_archive_storage = cls.build_confluence_archive_storage_html(
                            archived_categories=all_archived_list,
                            sync_date_str=current_date_str,
                            main_page_url=confluence_page_url,
                        )

                        conf_client.update_page(
                            page_id=confluence_archive_page_id,
                            title=archive_page_title,
                            space_key=archive_space_key,
                            storage_html=new_archive_storage,
                            next_version=archive_version_num + 1,
                        )
                        logger.info(
                            "[CONFLUENCE] Confluence archive page synchronized successfully (%d categories archived).",
                            len(all_archived_list),
                        )
                    except Exception as err_update_arch:
                        logger.warning(
                            "[ARCHIVE] Error updating archive page %s (%s). Proceeding.",
                            confluence_archive_page_id,
                            err_update_arch,
                        )

                # 6. Weekly statistics page update and HTML attachment
                stats_page_url: str | None = None
                if confluence_stats_page_id:
                    try:
                        stats_page_data = conf_client.get_page(page_id=confluence_stats_page_id)
                        stats_page_url = conf_client.build_page_url(stats_page_data)
                        stats_storage_raw = (
                            stats_page_data.get("body", {}).get("storage", {}).get("value", "")
                        )
                        stats_version_num = stats_page_data.get("version", {}).get("number", 1)
                        stats_page_title = stats_page_data.get("title", "Alert Tracking Statistics")
                        stats_space_key = stats_page_data.get("space", {}).get("key", "ALERTS")

                        report_filename: str | None = None
                        if render_html_callback:
                            try:
                                full_html_content = render_html_callback(
                                    conf_url=confluence_page_url,
                                    conf_stats=tracking_stats,
                                )
                                ts_suffix = datetime.now(tz=app_tz).strftime("%Y%m%d_%H%M%S")
                                report_filename = f"rapport_alertes_{ts_suffix}.html"

                                conf_client.attach_file(
                                    page_id=confluence_stats_page_id,
                                    filename=report_filename,
                                    content=full_html_content,
                                    content_type="text/html; charset=utf-8",
                                    comment=f"Alerting report for {current_date_str}",
                                )
                            except Exception as err_attach:
                                logger.warning(
                                    "[CONFLUENCE] Error attaching report to stats page (%s).",
                                    err_attach,
                                )
                                report_filename = None

                        updated_stats_storage = cls.append_weekly_stats_row(
                            storage_html=stats_storage_raw,
                            stats=tracking_stats,
                            sync_date_str=current_date_str,
                            total_alerts=len(alerts),
                            main_page_url=confluence_page_url,
                            report_filename=report_filename,
                            artifact_url=gitlab_artifact_url,
                        )

                        conf_client.update_page(
                            page_id=confluence_stats_page_id,
                            title=stats_page_title,
                            space_key=stats_space_key,
                            storage_html=updated_stats_storage,
                            next_version=stats_version_num + 1,
                        )
                        logger.info(
                            "[CONFLUENCE] Confluence statistics page incremented successfully (%s).",
                            current_date_str,
                        )
                    except Exception as err_stats:
                        logger.warning(
                            "[CONFLUENCE] Error updating statistics page %s (%s). Proceeding.",
                            confluence_stats_page_id,
                            err_stats,
                        )

                # 7. Update active review page
                new_storage = cls.build_confluence_storage_html(
                    tracked_categories=active_categories,
                    stats=tracking_stats,
                    sync_date_str=current_date_str,
                    artifact_url=gitlab_artifact_url,
                    artifact_browse_url=gitlab_artifact_browse_url,
                    archive_page_url=archive_page_url,
                    archived_count=len(archive_registry) + len(to_archive_categories),
                    stats_page_url=stats_page_url,
                    deleted_unattended_history=deleted_unattended,
                )

                conf_client.update_page(
                    page_id=confluence_page_id,
                    title=page_title,
                    space_key=space_key,
                    storage_html=new_storage,
                    next_version=version_num + 1,
                )
                logger.info(
                    "[CONFLUENCE] Confluence registry synchronized successfully (%d active categories, %d archived).",
                    len(active_categories),
                    len(to_archive_categories),
                )

        except Exception as e:
            logger.warning(
                "[CONFLUENCE] Error during Confluence synchronization (%s). Continuing generation without blocking.",
                e,
            )

        return confluence_page_url, tracking_stats
