from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, tzinfo
from typing import Any

# Pre-compiled regular expressions
RE_HTML_TAGS = re.compile(r"<[^>]+>")
RE_SEVERITY_STARS = re.compile(r"[\*`]")
RE_STATUS_BRACKET = re.compile(r"\[\s*(FIRING(?::\d+)?|RESOLVED)", re.IGNORECASE)
RE_STATUS_RESOLVED = re.compile(r"\bresolved\b", re.IGNORECASE)
RE_STATUS_FIRING = re.compile(r"\bfiring\b", re.IGNORECASE)
RE_DESC_FIELD = re.compile(r"\*\*Description\s*:\*\*\s*([^\n]+)", re.IGNORECASE)
RE_ALERT_FIELD = re.compile(r"\*\*Alert\s*:\*\*\s*([^\n]+)", re.IGNORECASE)
RE_SEVERITY_PREFIX = re.compile(r"^(?:CRITICAL|MAJOR|WARNING|INFO)\s*-\s*", re.IGNORECASE)

DAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DAYS_EN_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS_EN = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]


class AlertService:
    """
    Service for processing, categorizing, and aggregating alerts.
    An alert's category corresponds to the description extracted from each alert attachment.
    """

    @staticmethod
    def _clean_text(text: str) -> str:
        """
        Cleans text by stripping HTML tags, decoding HTML entities,
        removing Markdown bold markers, and trimming extra whitespace.
        """
        if not text:
            return ""
        # Remove HTML tags
        clean = RE_HTML_TAGS.sub("", text)
        # Decode HTML entities (&lt;, &gt;, &#39;, &amp;, etc.)
        clean = html.unescape(clean)
        # Remove markdown stars/ticks from severity labels
        clean = RE_SEVERITY_STARS.sub("", clean)
        return clean.strip()

    @staticmethod
    def extract_status(message: str, titles: list[str] | None = None) -> str:
        """
        Extracts the alert status (RESOLVED, FIRING:N, etc.).
        """
        if not message and not titles:
            return "INFO"

        # 1. Search attachment titles with highest priority
        candidates = list(titles) if titles else []
        candidates.extend(message.splitlines())

        for line in candidates:
            m = RE_STATUS_BRACKET.search(line)
            if m:
                return m.group(1).upper()

        # 2. Word boundary search across full message
        if RE_STATUS_RESOLVED.search(message):
            return "RESOLVED"
        if RE_STATUS_FIRING.search(message):
            return "FIRING"

        return "INFO"

    @classmethod
    def extract_descriptions(cls, alert: dict[str, Any]) -> list[str]:
        """
        Extracts the list of attachment descriptions for a given alert.
        Each description serves as an alert category.
        """
        descriptions: list[str] = []

        # 1. Extract from structured attachments list if available
        attachments = alert.get("attachments") or []
        for att in attachments:
            desc = att.get("description", "").strip()
            if desc:
                cleaned = cls._clean_text(desc)
                if cleaned and cleaned not in descriptions:
                    descriptions.append(cleaned)

        # 2. If no attachment description found, parse message body
        if not descriptions:
            msg = alert.get("message", "")
            matches = RE_DESC_FIELD.findall(msg)
            for m in matches:
                cleaned = cls._clean_text(m)
                if cleaned and cleaned not in descriptions:
                    descriptions.append(cleaned)

        # 3. If still no description, look for **Alert :** pattern
        if not descriptions:
            alert_match = RE_ALERT_FIELD.search(alert.get("message", ""))
            if alert_match:
                cleaned = cls._clean_text(alert_match.group(1))
                # Remove optional severity prefix
                cleaned = RE_SEVERITY_PREFIX.sub("", cleaned).strip()
                if cleaned:
                    descriptions.append(cleaned)

        # 4. Ultimate fallback: first line of message or generic title
        if not descriptions:
            raw_msg = alert.get("message", "").strip()
            first_line = raw_msg.splitlines()[0] if raw_msg else ""
            if first_line:
                descriptions.append(cls._clean_text(first_line)[:80])
            else:
                descriptions.append("Alert without description")

        return descriptions

    @classmethod
    def categorize_alerts(
        cls,
        alerts: list[dict[str, Any]],
        tz: tzinfo | None = None,
    ) -> list[dict[str, Any]]:
        """
        Groups alerts by category (where category = description of each attachment),
        computes the number of occurrences over the selected time window,
        and provides timestamps for each occurrence.
        Optimized with date formatting caches.
        """
        groups: dict[str, list[dict[str, Any]]] = {}

        for index, alert in enumerate(alerts, 1):
            msg = alert.get("message", "")
            titles = alert.get("titles") or []
            created_at = alert.get("created_at", "")
            timestamp = alert.get("timestamp", 0)
            alert_id = alert.get("id", str(index))

            status = cls.extract_status(msg, titles)
            descriptions = cls.extract_descriptions(alert)
            permalink = alert.get("permalink", "")

            # Enrich alert object for detailed view rendering
            alert["index"] = index
            alert["status"] = status
            alert["category"] = descriptions[0] if descriptions else ""
            alert["categories"] = descriptions
            alert["permalink"] = permalink

            # Each attachment description counts as an occurrence for that category
            for desc in descriptions:
                occurrence = {
                    "index": index,
                    "id": alert_id,
                    "created_at": created_at,
                    "timestamp": timestamp,
                    "status": status,
                    "category": desc,
                    "permalink": permalink,
                }
                groups.setdefault(desc, []).append(occurrence)

        categories_summary = []

        # Date formatting caches to avoid tens of thousands of strftime calls
        day_cache: dict[tuple[int, int, int], tuple[str, str]] = {}
        month_cache: dict[tuple[int, int], tuple[str, str]] = {}

        for cat_name, occurrences in groups.items():
            sorted_occurrences = sorted(
                occurrences,
                key=lambda o: o.get("timestamp", 0),
                reverse=True,
            )

            # Group occurrences by month and day within this category
            month_groups: dict[str, dict[str, Any]] = {}

            for occ in sorted_occurrences:
                ts = occ.get("timestamp", 0)
                if ts:
                    dt = datetime.fromtimestamp(ts / 1000.0, tz=tz)
                    m_tuple = (dt.year, dt.month)
                    if m_tuple not in month_cache:
                        month_cache[m_tuple] = (
                            f"{dt.year:04d}-{dt.month:02d}",
                            f"{MONTHS_EN[dt.month - 1]} {dt.year}",
                        )
                    month_key, month_label = month_cache[m_tuple]

                    d_tuple = (dt.year, dt.month, dt.day)
                    if d_tuple not in day_cache:
                        day_cache[d_tuple] = (
                            f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d}",
                            f"{DAYS_EN[dt.weekday()]} {dt.day:02d}/{dt.month:02d}/{dt.year:04d}",
                        )
                    date_key, date_label = day_cache[d_tuple]
                    time_str = f"{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}"
                else:
                    created_at = occ.get("created_at", "")
                    try:
                        dt = datetime.strptime(created_at, "%d/%m/%Y %H:%M:%S")
                        month_key = f"{dt.year:04d}-{dt.month:02d}"
                        month_label = f"{MONTHS_EN[dt.month - 1]} {dt.year}"
                        date_key = f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d}"
                        date_label = f"{DAYS_EN[dt.weekday()]} {dt.day:02d}/{dt.month:02d}/{dt.year:04d}"
                        time_str = f"{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}"
                    except Exception:
                        month_key = "0000-00"
                        month_label = "Unknown Month"
                        date_key = "0000-00-00"
                        date_label = "Unknown Date"
                        time_str = created_at

                occ["time"] = time_str
                occ["date_label"] = date_label
                occ["month_label"] = month_label

                # Hierarchical grouping: month -> days
                if month_key not in month_groups:
                    month_groups[month_key] = {
                        "month_key": month_key,
                        "month_label": month_label,
                        "days_map": {},
                        "count": 0,
                    }
                m_grp = month_groups[month_key]
                m_grp["count"] += 1

                if date_key not in m_grp["days_map"]:
                    m_grp["days_map"][date_key] = {
                        "date_key": date_key,
                        "date_label": date_label,
                        "occurrences": [],
                        "count": 0,
                    }
                m_grp["days_map"][date_key]["occurrences"].append(occ)
                m_grp["days_map"][date_key]["count"] += 1

            sorted_months = []
            for m_k in sorted(month_groups.keys(), reverse=True):
                m_info = month_groups[m_k]
                sorted_days_in_m = sorted(
                    m_info["days_map"].values(),
                    key=lambda d: d["date_key"],
                    reverse=True,
                )
                sorted_months.append({
                    "month_key": m_info["month_key"],
                    "month_label": m_info["month_label"],
                    "count": m_info["count"],
                    "days": sorted_days_in_m,
                })

            categories_summary.append({
                "name": cat_name,
                "count": len(occurrences),
                "occurrences": sorted_occurrences,
                "months": sorted_months,
                "latest_timestamp": sorted_occurrences[0].get("timestamp", 0) if sorted_occurrences else 0,
                "latest_occurrence_at": sorted_occurrences[0].get("created_at", "") if sorted_occurrences else "",
            })

        # Sort categories by occurrence count descending, then by latest timestamp descending
        categories_summary.sort(
            key=lambda c: (c["count"], c["latest_timestamp"]),
            reverse=True,
        )

        return categories_summary

    @classmethod
    def build_timeline_data(
        cls,
        alerts: list[dict[str, Any]],
        hours: int | None = None,
        categories: list[dict[str, Any]] | None = None,
        tz: tzinfo | None = None,
    ) -> dict[str, Any]:
        """
        Builds the data model for the interactive timeline chart:
        - Determines the time window [t_start, t_end].
        - Computes regular time graduations (ticks) along the X axis.
        - Positions each alert proportionally as a percentage (0% to 100%).
        - Organizes alerts into horizontal lanes per category.
        - Integrates drill-down hierarchy (months, days, occurrences).
        - Computes daily partitions and midnight boundaries adjusted to timezone.
        """
        empty_result = {
            "has_data": False,
            "start_label": "",
            "end_label": "",
            "duration_hours": hours or 24,
            "ticks": [],
            "days": [],
            "day_separators": [],
            "periods": [],
            "period_title": "",
            "lanes": [],
        }

        if not alerts:
            return empty_result

        timestamps = [a.get("timestamp", 0) for a in alerts if a.get("timestamp")]
        if not timestamps:
            return empty_result

        min_ts = min(timestamps)
        max_ts = max(timestamps)

        # If span is under 15 minutes, add padding for comfortable visibility
        if max_ts - min_ts < 15 * 60 * 1000:
            t_start = min_ts - 30 * 60 * 1000
            t_end = max_ts + 30 * 60 * 1000
        else:
            padding = int((max_ts - min_ts) * 0.02)
            t_start = min_ts - padding
            t_end = max_ts + padding

        total_span = max(t_end - t_start, 1)

        # Generate 6 regular time graduations along the X axis
        num_ticks = 6
        ticks = []
        for i in range(num_ticks):
            frac = i / (num_ticks - 1)
            tick_ts = t_start + frac * total_span
            dt = datetime.fromtimestamp(tick_ts / 1000.0, tz=tz)
            ticks.append({
                "pct": round(frac * 100, 2),
                "label": dt.strftime("%d/%m %H:%M"),
                "time": dt.strftime("%H:%M"),
                "date": dt.strftime("%d/%m"),
            })

        # Group alerts into lanes by category
        groups: dict[str, list[dict[str, Any]]] = {}
        for a in alerts:
            ts = a.get("timestamp", 0)
            if not ts:
                continue
            pct = max(0.0, min(100.0, (ts - t_start) / total_span * 100))
            status = a.get("status", "INFO")
            status_lower = status.lower()
            if "resolved" in status_lower:
                status_type = "resolved"
            elif "firing" in status_lower:
                status_type = "firing"
            else:
                status_type = "info"

            point = {
                "index": a.get("index"),
                "created_at": a.get("created_at"),
                "timestamp": ts,
                "pct": round(pct, 2),
                "status": status,
                "status_type": status_type,
                "permalink": a.get("permalink", ""),
            }

            cats = a.get("categories") or [a.get("category", "Other alerts")]
            for cat_name in cats:
                cat_key = cat_name if cat_name else "Other alerts"
                groups.setdefault(cat_key, []).append(point)

        # Associate detailed category data
        if categories is None:
            categories = cls.categorize_alerts(alerts, tz=tz)
        cat_map = {c["name"]: c for c in categories}

        # Sort lanes by alert count descending
        lanes = []
        for cat_name, points in sorted(groups.items(), key=lambda x: len(x[1]), reverse=True):
            points_sorted = sorted(points, key=lambda p: p["timestamp"])
            cat_info = cat_map.get(cat_name, {})
            lanes.append({
                "category_name": cat_name,
                "count": cat_info.get("count", len(points)),
                "points": points_sorted,
                "months": cat_info.get("months", []),
                "occurrences": cat_info.get("occurrences", []),
                "tracking": cat_info.get("tracking"),
            })

        dt_start = datetime.fromtimestamp(t_start / 1000.0, tz=tz)
        dt_end = datetime.fromtimestamp(t_end / 1000.0, tz=tz)
        duration_hours = round(total_span / (3600 * 1000), 1)

        current_date = dt_start.date()
        end_date = dt_end.date()

        timeline_days = []
        day_separators = []
        day_idx = 0

        while current_date <= end_date:
            day_start_dt = datetime(current_date.year, current_date.month, current_date.day, 0, 0, 0, tzinfo=tz)
            day_start_ts = day_start_dt.timestamp() * 1000.0

            next_day_start_dt = day_start_dt + timedelta(days=1)
            next_day_start_ts = next_day_start_dt.timestamp() * 1000.0

            effective_start_ts = max(day_start_ts, t_start)
            effective_end_ts = min(next_day_start_ts, t_end)

            if effective_end_ts > effective_start_ts:
                start_pct = (effective_start_ts - t_start) / total_span * 100.0
                end_pct = (effective_end_ts - t_start) / total_span * 100.0
                width_pct = max(0.0, end_pct - start_pct)

                day_name = DAYS_EN_SHORT[current_date.weekday()]
                full_name = DAYS_EN[current_date.weekday()]
                d_str = current_date.strftime("%d/%m")

                timeline_days.append({
                    "date_key": current_date.strftime("%Y-%m-%d"),
                    "date_label": f"{day_name} {d_str}",
                    "full_label": f"{full_name} {current_date.strftime('%d/%m/%Y')}",
                    "day_name": day_name,
                    "date_str": d_str,
                    "start_pct": round(start_pct, 2),
                    "end_pct": round(end_pct, 2),
                    "width_pct": round(width_pct, 2),
                    "is_even": day_idx % 2 == 0,
                })

                if day_start_ts > t_start:
                    sep_pct = (day_start_ts - t_start) / total_span * 100.0
                    day_separators.append({
                        "pct": round(sep_pct, 2),
                        "date_label": d_str,
                        "day_name": day_name,
                    })
                day_idx += 1

            current_date += timedelta(days=1)

        # Higher level grouping by months or weeks for extended time windows
        periods = []
        period_title = ""

        if duration_hours > 24 * 21:  # Over 3 weeks -> Group by month
            period_title = "🗓️ Months"
            m_curr = dt_start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            while m_curr <= dt_end:
                m_start_ts = m_curr.timestamp() * 1000.0
                if m_curr.month == 12:
                    m_next = m_curr.replace(year=m_curr.year + 1, month=1)
                else:
                    m_next = m_curr.replace(month=m_curr.month + 1)
                m_end_ts = m_next.timestamp() * 1000.0

                eff_start = max(m_start_ts, t_start)
                eff_end = min(m_end_ts, t_end)

                if eff_end > eff_start:
                    start_pct = (eff_start - t_start) / total_span * 100.0
                    end_pct = (eff_end - t_start) / total_span * 100.0
                    periods.append({
                        "label": f"🗓️ {MONTHS_EN[m_curr.month - 1]} {m_curr.year}",
                        "start_pct": round(start_pct, 2),
                        "width_pct": round(max(0.0, end_pct - start_pct), 2),
                    })
                m_curr = m_next

        elif duration_hours > 24 * 5:  # Between 5 days and 3 weeks -> Group by week
            period_title = "📅 Weeks"
            w_curr = dt_start - timedelta(days=dt_start.weekday())
            w_curr = w_curr.replace(hour=0, minute=0, second=0, microsecond=0)
            while w_curr <= dt_end:
                w_start_ts = w_curr.timestamp() * 1000.0
                w_next = w_curr + timedelta(days=7)
                w_end_ts = w_next.timestamp() * 1000.0

                eff_start = max(w_start_ts, t_start)
                eff_end = min(w_end_ts, t_end)

                if eff_end > eff_start:
                    start_pct = (eff_start - t_start) / total_span * 100.0
                    end_pct = (eff_end - t_start) / total_span * 100.0
                    w_num = w_curr.isocalendar()[1]
                    w_end_day = w_next - timedelta(days=1)
                    periods.append({
                        "label": f"Week {w_num} ({w_curr.strftime('%d/%m')} - {w_end_day.strftime('%d/%m')})",
                        "start_pct": round(start_pct, 2),
                        "width_pct": round(max(0.0, end_pct - start_pct), 2),
                    })
                w_curr = w_next

        return {
            "has_data": True,
            "start_label": dt_start.strftime("%d/%m/%Y %H:%M"),
            "end_label": dt_end.strftime("%d/%m/%Y %H:%M"),
            "duration_hours": duration_hours,
            "ticks": ticks,
            "days": timeline_days,
            "day_separators": day_separators,
            "periods": periods,
            "period_title": period_title,
            "lanes": lanes,
        }
