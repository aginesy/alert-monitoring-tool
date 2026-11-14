from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest
from clients.confluence_client import ConfluenceClient


def test_confluence_client_build_url() -> None:
    client = ConfluenceClient(url="https://confluence.example.com", token="fake_token", page_id="12345")
    page_data = {
        "id": "12345",
        "title": "Analyse des alertes",
        "space": {"key": "ALERTS"},
        "_links": {"webui": "/spaces/ALERTS/pages/12345/Analyse+des+alertes"},
    }
    url = client.build_page_url(page_data)
    assert url == "https://confluence.example.com/spaces/ALERTS/pages/12345/Analyse+des+alertes"


def test_confluence_client_get_page_success() -> None:
    client = ConfluenceClient(url="https://confluence.example.com", token="fake_token", page_id="12345")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": "12345", "title": "Page Test"}

    with patch.object(client.session, "get", return_value=mock_resp) as mock_get:
        data = client.get_page("12345")
        assert data["id"] == "12345"
        mock_get.assert_called_once()


def test_confluence_client_update_page_success() -> None:
    client = ConfluenceClient(url="https://confluence.example.com", token="fake_token", page_id="12345")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": "12345", "version": {"number": 2}}

    with patch.object(client.session, "put", return_value=mock_resp) as mock_put:
        data = client.update_page(
            page_id="12345",
            title="Page Test",
            space_key="ALERTS",
            storage_html="<p>Test</p>",
            next_version=2,
        )
        assert data["version"]["number"] == 2
        mock_put.assert_called_once()
