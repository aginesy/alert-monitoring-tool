from __future__ import annotations

import pytest
from services.alert_service import AlertService


def test_categorize_alerts_extracts_descriptions() -> None:
    alerts = [
        {
            "id": "1",
            "message": "**Description :** High response time on auth-service",
            "timestamp": 1700000000000,
            "created_at": "14/11/2023 10:00:00",
        },
        {
            "id": "2",
            "message": "**Description :** High response time on auth-service",
            "timestamp": 1700000010000,
            "created_at": "14/11/2023 10:00:10",
        },
    ]
    categories = AlertService.categorize_alerts(alerts)
    assert len(categories) == 1
    assert categories[0]["name"] == "High response time on auth-service"
    assert categories[0]["count"] == 2


def test_build_timeline_data_with_tracking() -> None:
    alerts = [
        {
            "id": "1",
            "message": "**Description :** Database cluster memory alert",
            "timestamp": 1700000000000,
            "created_at": "14/11/2023 10:00:00",
        }
    ]
    categories = AlertService.categorize_alerts(alerts)
    categories[0]["tracking"] = {
        "slug": "database-cluster-memory-alert",
        "status": "IN PROGRESS",
        "actions_html": "<p>Index rebuild underway</p>",
        "assignee": "Alice",
    }
    timeline = AlertService.build_timeline_data(alerts, hours=24, categories=categories)
    assert timeline["has_data"] is True
    assert len(timeline["lanes"]) == 1
    lane = timeline["lanes"][0]
    assert lane["tracking"]["status"] == "IN PROGRESS"
    assert lane["tracking"]["assignee"] == "Alice"
