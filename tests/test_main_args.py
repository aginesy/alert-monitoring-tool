from __future__ import annotations

import argparse
import os
import pytest
from main import parse_arguments, str_to_bool


def test_str_to_bool() -> None:
    assert str_to_bool(True) is True
    assert str_to_bool(False) is False
    assert str_to_bool("true") is True
    assert str_to_bool("True") is True
    assert str_to_bool("TRUE") is True
    assert str_to_bool("1") is True
    assert str_to_bool("yes") is True
    assert str_to_bool("vrai") is True
    assert str_to_bool("false") is False
    assert str_to_bool("False") is False
    assert str_to_bool("FALSE") is False
    assert str_to_bool("0") is False
    assert str_to_bool("no") is False
    assert str_to_bool("faux") is False

    with pytest.raises(argparse.ArgumentTypeError):
        str_to_bool("invalide")


def test_parse_arguments_default_confluence_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUIVI_CONFLUENCE", raising=False)
    monkeypatch.setattr("sys.argv", ["main.py", "--hours", "24"])
    args = parse_arguments()
    assert args.suivi_confluence is False
    assert args.hours == 24


def test_parse_arguments_with_suivi_confluence_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUIVI_CONFLUENCE", raising=False)
    monkeypatch.setattr("sys.argv", ["main.py", "--hours", "48", "--suivi-confluence"])
    args = parse_arguments()
    assert args.suivi_confluence is True
    assert args.hours == 48


@pytest.mark.parametrize(
    "arg_value,expected",
    [
        ("--suivi-confluence=true", True),
        ("--suivi-confluence=True", True),
        ("--suivi-confluence=1", True),
        ("--suivi-confluence=false", False),
        ("--suivi-confluence=False", False),
        ("--suivi-confluence=0", False),
    ],
)
def test_parse_arguments_with_suivi_confluence_equals_value(
    monkeypatch: pytest.MonkeyPatch, arg_value: str, expected: bool
) -> None:
    monkeypatch.delenv("SUIVI_CONFLUENCE", raising=False)
    monkeypatch.setattr("sys.argv", ["main.py", arg_value])
    args = parse_arguments()
    assert args.suivi_confluence is expected


def test_parse_arguments_with_suivi_confluence_separate_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUIVI_CONFLUENCE", raising=False)
    monkeypatch.setattr("sys.argv", ["main.py", "--suivi-confluence", "false"])
    args = parse_arguments()
    assert args.suivi_confluence is False

    monkeypatch.setattr("sys.argv", ["main.py", "--suivi-confluence", "true"])
    args = parse_arguments()
    assert args.suivi_confluence is True


def test_parse_arguments_with_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUIVI_CONFLUENCE", "true")
    monkeypatch.setattr("sys.argv", ["main.py"])
    args = parse_arguments()
    assert args.suivi_confluence is True


def test_parse_arguments_cli_overrides_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    # L'argument CLI =false doit écraser la variable d'environnement active
    monkeypatch.setenv("SUIVI_CONFLUENCE", "true")
    monkeypatch.setattr("sys.argv", ["main.py", "--suivi-confluence=false"])
    args = parse_arguments()
    assert args.suivi_confluence is False

    # L'argument CLI =true doit écraser la variable d'environnement désactivée
    monkeypatch.setenv("SUIVI_CONFLUENCE", "false")
    monkeypatch.setattr("sys.argv", ["main.py", "--suivi-confluence=true"])
    args = parse_arguments()
    assert args.suivi_confluence is True


def test_parse_arguments_invalid_suivi_confluence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["main.py", "--suivi-confluence=notabool"])
    with pytest.raises(SystemExit):
        parse_arguments()


def test_main_execution_with_suivi_confluence_false(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import MagicMock, patch
    from main import main

    monkeypatch.setattr("sys.argv", ["main.py", "--suivi-confluence=false"])
    monkeypatch.setattr(
        "config.config_mattermost.mattermost_client_config",
        {
            "url": "https://mattermost.test",
            "token": "test_token",
            "channel_id": "test_channel",
            "team": "test_team",
        },
    )

    sample_alert = {
        "id": "post_1",
        "category": "Alerte test",
        "title": "Alerte test",
        "message": "**Alert :** Alerte test",
        "created_at": "28/10/2026 à 10:00:00",
        "timestamp": 1793181600000,
        "status": "FIRING",
        "status_type": "firing",
        "permalink": "https://mattermost.test/post_1",
    }

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.fetch_messages.return_value = [sample_alert]

    with patch("main.MattermostClient", return_value=mock_client), patch("main.save_report") as mock_save:
        exit_code = main()

    assert exit_code == 0
    assert mock_save.called
    saved_html, _ = mock_save.call_args[0]
    assert "Rapport d'Alerting" in saved_html
    assert "Généré le :" in saved_html

    # Vérification stricte : aucun élément Confluence ne doit apparaître dans le DOM rendu
    assert "📋 Suivi Confluence ↗" not in saved_html
    assert '<div class="confluence-kpi-bar">' not in saved_html
    assert '<div class="confluence-tracking-card">' not in saved_html
    assert 'class="tracking-pill' not in saved_html
    assert "Actions décidées :" not in saved_html
    assert "Porteur :" not in saved_html


def test_main_execution_with_suivi_confluence_true_missing_confluence_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import MagicMock, patch
    from main import main

    monkeypatch.setattr("sys.argv", ["main.py", "--suivi-confluence=true"])
    monkeypatch.setattr(
        "config.config_mattermost.mattermost_client_config",
        {
            "url": "https://mattermost.test",
            "token": "test_token",
            "channel_id": "test_channel",
            "team": "test_team",
        },
    )
    monkeypatch.setattr(
        "config.config_confluence.confluence_config",
        {"url": "", "token": "", "page_id": ""},
    )

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.fetch_messages.return_value = []

    with patch("main.MattermostClient", return_value=mock_client), patch("main.save_report") as mock_save:
        exit_code = main()

    assert exit_code == 0
    assert mock_save.called
    saved_html, _ = mock_save.call_args[0]
    assert "Rapport d'Alerting" in saved_html
    assert "Généré le :" in saved_html


def test_main_execution_with_suivi_confluence_true_and_archive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import MagicMock, patch
    from main import main

    monkeypatch.setattr("sys.argv", ["main.py", "--suivi-confluence=true"])
    monkeypatch.setattr(
        "config.config_mattermost.mattermost_client_config",
        {
            "url": "https://mattermost.test",
            "token": "test_token",
            "channel_id": "test_channel",
            "team": "test_team",
        },
    )
    monkeypatch.setattr(
        "config.config_confluence.confluence_config",
        {
            "url": "https://confluence.test",
            "token": "conf_token",
            "page_id": "123456789",
            "archive_page_id": "123456780",
            "stats_page_id": "123456781",
        },
    )

    mock_mm_client = MagicMock()
    mock_mm_client.__enter__.return_value = mock_mm_client
    mock_mm_client.fetch_messages.return_value = []

    mock_conf_client = MagicMock()
    mock_conf_client.__enter__.return_value = mock_conf_client
    mock_conf_client.build_page_url.side_effect = lambda data: f"https://confluence.test/pages/{data.get('id', '0')}"

    # Simulation : La page principale contient une alerte résolue ancienne (10/05/2026, > 3 mois)
    main_page_storage = """
    <table>
      <thead>
        <tr>
          <th>Statut</th><th>Catégorie d'alerte</th><th>Occurrences</th>
          <th>Date de la dernière apparition de l'alerte dans Mattermost</th>
          <th>Porteur</th><th>Échéance</th><th>Actions décidées (Point de suivi)</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><ac:structured-macro ac:name="status"><ac:parameter ac:name="title">RÉSOLUE</ac:parameter></ac:structured-macro></td>
          <td><strong>Ancienne alerte à archiver</strong></td>
          <td>10 cette semaine</td>
          <td>10/05/2026 14:00:00</td>
          <td>Alice</td><td>-</td><td><p>Problème résolu</p></td>
        </tr>
      </tbody>
    </table>
    """

    def mock_get_page(page_id=None):
        if page_id == "123456780":
            return {
                "id": "123456780",
                "title": "Archive des décisions de suivi des alertes résolues depuis plus de 1 mois",
                "space": {"key": "ALERTS"},
                "version": {"number": 1},
                "body": {"storage": {"value": "<table></table>"}},
            }
        elif page_id == "123456781":
            return {
                "id": "123456781",
                "title": "Statistiques du suivi des alertes",
                "space": {"key": "ALERTS"},
                "version": {"number": 2},
                "body": {"storage": {"value": "<table><thead><tr><th>Date d'exécution</th></tr></thead><tbody></tbody></table>"}},
            }
        return {
            "id": "123456789",
            "title": "Analyse des alertes",
            "space": {"key": "ALERTS"},
            "version": {"number": 3},
            "body": {"storage": {"value": main_page_storage}},
        }

    mock_conf_client.get_page.side_effect = mock_get_page

    with patch("main.MattermostClient", return_value=mock_mm_client), \
         patch("main.ConfluenceClient", return_value=mock_conf_client), \
         patch("main.save_report"):
        exit_code = main()

    assert exit_code == 0
    # Vérifier que update_page a été appelé pour l'archive, les statistiques et la page principale
    assert mock_conf_client.update_page.call_count == 3
    calls = mock_conf_client.update_page.call_args_list

    # Appel 1 : Page d'archive mise à jour avec l'alerte résolue ancienne
    archive_call = calls[0].kwargs
    assert archive_call["page_id"] == "123456780"
    assert "Ancienne alerte à archiver" in archive_call["storage_html"]
    assert "<th>Actions décidées (Point de suivi)</th>" in archive_call["storage_html"]

    # Appel 2 : Page de statistiques incrémentée avec les métriques de la semaine et la pièce jointe
    stats_call = calls[1].kwargs
    assert stats_call["page_id"] == "123456781"
    assert "<tbody><tr>" in stats_call["storage_html"]
    assert "<th>Rapport HTML (PJ)</th>" in stats_call["storage_html"]
    assert "<ri:attachment" in stats_call["storage_html"]

    # Vérification que le fichier a bien été attaché via l'API Confluence
    assert mock_conf_client.attach_file.called
    attach_call = mock_conf_client.attach_file.call_args.kwargs
    assert attach_call["page_id"] == "123456781"
    assert attach_call["filename"].startswith("rapport_alertes_")

    # Appel 3 : Page active mise à jour (l'alerte résolue ancienne en a été retirée)
    main_call = calls[2].kwargs
    assert main_call["page_id"] == "123456789"
    assert "Ancienne alerte à archiver" not in main_call["storage_html"]
    assert "https://confluence.test/pages/123456780" in main_call["storage_html"]
    assert "https://confluence.test/pages/123456781" in main_call["storage_html"]


def test_main_report_html_contains_confluence_tracking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import MagicMock, patch
    from main import main

    monkeypatch.setattr("sys.argv", ["main.py", "--suivi-confluence=true"])
    monkeypatch.setattr(
        "config.config_mattermost.mattermost_client_config",
        {
            "url": "https://mattermost.test",
            "token": "test_token",
            "channel_id": "test_channel",
            "team": "test_team",
        },
    )
    monkeypatch.setattr(
        "config.config_confluence.confluence_config",
        {
            "url": "https://confluence.test",
            "token": "conf_token",
            "page_id": "123456789",
            "archive_page_id": "",
            "stats_page_id": "",
        },
    )

    sample_alert = {
        "id": "post_1",
        "category": "Alerte suivie en cours",
        "title": "Alerte suivie en cours",
        "message": "**Alert :** Alerte suivie en cours",
        "created_at": "28/10/2026 à 10:00:00",
        "timestamp": 1793181600000,
        "status": "FIRING",
        "status_type": "firing",
        "permalink": "https://mattermost.test/post_1",
    }

    mock_mm_client = MagicMock()
    mock_mm_client.__enter__.return_value = mock_mm_client
    mock_mm_client.fetch_messages.return_value = [sample_alert]

    mock_conf_client = MagicMock()
    mock_conf_client.__enter__.return_value = mock_conf_client
    mock_conf_client.build_page_url.return_value = "https://confluence.test/pages/123456789"

    main_page_storage = """
    <table>
      <thead>
        <tr>
          <th>Statut</th><th>Catégorie d'alerte</th><th>Occurrences</th>
          <th>Date de la dernière apparition de l'alerte dans Mattermost</th>
          <th>Porteur</th><th>Échéance</th><th>Actions décidées (Point de suivi)</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><ac:structured-macro ac:name="status"><ac:parameter ac:name="title">EN COURS</ac:parameter><ac:parameter ac:name="colour">Yellow</ac:parameter></ac:structured-macro></td>
          <td><strong>Alerte suivie en cours</strong></td>
          <td>5 cette semaine</td>
          <td>28/10/2026 10:00:00</td>
          <td>Alexandre</td><td>15/11/2026</td>
          <td><ul><li>Optimisation index MongoDB</li></ul></td>
        </tr>
      </tbody>
    </table>
    """

    mock_conf_client.get_page.return_value = {
        "id": "123456789",
        "title": "Analyse des alertes",
        "space": {"key": "ALERTS"},
        "version": {"number": 1},
        "body": {"storage": {"value": main_page_storage}},
    }

    with patch("main.MattermostClient", return_value=mock_mm_client), \
         patch("main.ConfluenceClient", return_value=mock_conf_client), \
         patch("main.save_report") as mock_save:
        exit_code = main()

    assert exit_code == 0
    assert mock_save.called
    saved_html, _ = mock_save.call_args[0]

    # Vérification que le statut, le porteur et l'action Confluence apparaissent bien dans le rapport HTML
    assert "status-en-cours" in saved_html
    assert "Alexandre" in saved_html
    assert "Optimisation index MongoDB" in saved_html
    assert "confluence-tracking-card" in saved_html




