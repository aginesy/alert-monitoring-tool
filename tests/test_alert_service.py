from __future__ import annotations

import pytest
from services.alert_service import AlertService


def test_categorize_alerts_extracts_descriptions() -> None:
    alerts = [
        {
            "id": "1",
            "message": "**Description :** Temps de reponse trop eleve sur auth",
            "timestamp": 1700000000000,
            "created_at": "14/11/2023 10:00:00",
        },
        {
            "id": "2",
            "message": "**Description :** Temps de reponse trop eleve sur auth",
            "timestamp": 1700000010000,
            "created_at": "14/11/2023 10:00:10",
        },
    ]
    categories = AlertService.categorize_alerts(alerts)
    assert len(categories) == 1
    assert categories[0]["name"] == "Temps de reponse trop eleve sur auth"
    assert categories[0]["count"] == 2


def test_build_timeline_data_with_tracking() -> None:
    alerts = [
        {
            "id": "1",
            "message": "**Description :** Alerte base de donnees",
            "timestamp": 1700000000000,
            "created_at": "14/11/2023 10:00:00",
        }
    ]
    categories = AlertService.categorize_alerts(alerts)
    categories[0]["tracking"] = {
        "slug": "alerte-base-de-donnees",
        "status": "EN COURS",
        "actions_html": "<p>Index en cours de reconstruction</p>",
        "assignee": "Alexandre",
    }
    timeline = AlertService.build_timeline_data(alerts, hours=24, categories=categories)
    assert timeline["has_data"] is True
    assert len(timeline["lanes"]) == 1
    lane = timeline["lanes"][0]
    assert lane["tracking"]["status"] == "EN COURS"
    assert lane["tracking"]["assignee"] == "Alexandre"
