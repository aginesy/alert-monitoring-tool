from __future__ import annotations

import pytest
from services.tracking_service import TrackingService


def test_normalize_category_name() -> None:
    # 1. Suppression de métrique dynamique
    raw_1 = "Disk space used on opmilo10d:/ARCHIVE is more than 90% (current : 91)"
    expected_1 = "Disk space used on opmilo10d:/ARCHIVE is more than 90%"
    assert TrackingService.normalize_category_name(raw_1) == expected_1

    # 2. Suppression de hash de réplica de pod kubernetes
    raw_2 = "Le pod bi-agent-8578c8c7ff-wld7g a redémarré pour la raison Error"
    expected_2 = "Le pod bi-agent a redémarré pour la raison Error"
    assert TrackingService.normalize_category_name(raw_2) == expected_2

    # 3. Entités HTML et espaces
    raw_3 = "Le nombre d&#39;erreurs   5xx du service ms-ft-facade"
    expected_3 = "Le nombre d'erreurs 5xx du service ms-ft-facade"
    assert TrackingService.normalize_category_name(raw_3) == expected_3


def test_get_category_slug() -> None:
    name = "Le temps de réponse du service api-store est supérieur à 1s"
    slug = TrackingService.get_category_slug(name)
    assert "le-temps-de-reponse-du-service-api-store" in slug
    assert not any(c in slug for c in [" ", "'", "à", "é"])


def test_parse_confluence_storage() -> None:
    sample_storage = """
    <p>Introduction</p>
    <table>
      <thead>
        <tr>
          <th>Statut</th>
          <th>Catégorie d'alerte</th>
          <th>Occurrences</th>
          <th>Date de la dernière apparition de l'alerte dans Mattermost</th>
          <th>Porteur</th>
          <th>Échéance</th>
          <th>Actions décidées (Point de suivi)</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>
            <ac:structured-macro ac:name="status">
              <ac:parameter ac:name="title">EN COURS</ac:parameter>
              <ac:parameter ac:name="colour">Yellow</ac:parameter>
            </ac:structured-macro>
          </td>
          <td>
            <ac:structured-macro ac:name="anchor">
              <ac:parameter ac:name="">api-store-latency</ac:parameter>
            </ac:structured-macro>
            <strong>Le temps de réponse du service api-store est supérieur à 1s</strong>
          </td>
          <td>50 cette semaine</td>
          <td>20/10/2026 14:00</td>
          <td>Alexandre</td>
          <td><time datetime="2026-11-05" /></td>
          <td><ul><li>Optimiser requêtes MongoDB</li></ul></td>
        </tr>
      </tbody>
    </table>
    """
    registry = TrackingService.parse_confluence_storage(sample_storage)
    assert "api-store-latency" in registry
    entry = registry["api-store-latency"]
    # Le nom doit être le libellé propre et ne doit JAMAIS contenir le slug préfixé
    assert entry["name"] == "Le temps de réponse du service api-store est supérieur à 1s"
    assert entry["status"] == "EN COURS"
    assert entry["assignee"] == "Alexandre"
    assert entry["due_date"] == "2026-11-05"
    assert "Optimiser requêtes MongoDB" in entry["actions_html"]


def test_reconciliation_new_category() -> None:
    categories = [
        {"name": "Nouvelle alerte inconnue", "count": 12}
    ]
    existing = {}
    tracked, stats = TrackingService.reconcile(categories, existing, "27/10/2026 10:00")
    
    assert len(tracked) == 1
    assert tracked[0]["status"] == "NOUVELLE"
    assert tracked[0]["count_this_week"] == 12
    assert tracked[0]["total_occurrences"] == 12
    assert stats["NOUVELLE"] == 1
    assert stats["ACTIVE_THIS_WEEK"] == 1


def test_reconciliation_nouvelle_without_action_becomes_nouv() -> None:
    categories = [{"name": "Alerte sans action", "count": 4}]
    slug = TrackingService.get_category_slug("Alerte sans action")
    existing = {
        slug: {
            "slug": slug,
            "name": "Alerte sans action",
            "status": "NOUVELLE",
            "total_occurrences": 10,
            "actions_html": "<p><em>À définir lors du point de suivi</em></p>",
            "assignee": "",
            "last_seen": "20/10/2026",
        }
    }
    tracked, _ = TrackingService.reconcile(categories, existing, "27/10/2026 10:00")
    assert tracked[0]["status"] == "PTPNEL"


def test_reconciliation_nouv_without_action_stays_nouv() -> None:
    categories = [{"name": "Alerte déjà ptpnel", "count": 2}]
    slug = TrackingService.get_category_slug("Alerte déjà ptpnel")
    existing = {
        slug: {
            "slug": slug,
            "name": "Alerte déjà ptpnel",
            "status": "PTPNEL",
            "total_occurrences": 15,
            "actions_html": "<p><em>À définir lors du point de suivi</em></p>",
            "assignee": "",
            "last_seen": "15/10/2026",
            "ptpnel_since": "2026-10-15",
        }
    }
    tracked, _ = TrackingService.reconcile(categories, existing, "27/10/2026 10:00")
    assert tracked[0]["status"] == "PTPNEL"
    assert tracked[0]["ptpnel_since"] == "2026-10-15"


def test_reconciliation_nouvelle_with_real_action_becomes_en_cours() -> None:
    categories = [{"name": "Alerte prise en charge", "count": 3}]
    slug = TrackingService.get_category_slug("Alerte prise en charge")
    existing = {
        slug: {
            "slug": slug,
            "name": "Alerte prise en charge",
            "status": "NOUVELLE",
            "total_occurrences": 10,
            "actions_html": "<ul><li>Revue de code et déploiement fix</li></ul>",
            "assignee": "Alice",
            "last_seen": "20/10/2026",
        }
    }
    tracked, _ = TrackingService.reconcile(categories, existing, "27/10/2026 10:00")
    assert tracked[0]["status"] == "EN COURS"



def test_reconciliation_resolved_becomes_recurrent() -> None:
    categories = [
        {"name": "Alerte réapparue", "count": 5}
    ]
    slug = TrackingService.get_category_slug("Alerte réapparue")
    existing = {
        slug: {
            "slug": slug,
            "name": "Alerte réapparue",
            "status": "RÉSOLUE",
            "total_occurrences": 30,
            "actions_html": "<p>Correctif déployé en v1.2</p>",
            "assignee": "Alice",
            "last_seen": "15/10/2026",
        }
    }
    tracked, stats = TrackingService.reconcile(categories, existing, "27/10/2026 10:00")

    entry = tracked[0]
    # Règle clé : si elle était RÉSOLUE mais revient, statut bascule en RÉCURRENTE
    assert entry["status"] == "RÉCURRENTE"
    assert entry["count_this_week"] == 5
    assert entry["total_occurrences"] == 35
    # Les actions saisies et le porteur sont strictement préservés
    assert "Correctif déployé en v1.2" in entry["actions_html"]
    assert entry["assignee"] == "Alice"
    assert stats["RÉCURRENTE"] == 1


def test_reconciliation_preserves_inactive_categories() -> None:
    # Aucune alerte cette semaine
    categories = []
    slug = "alerte-dormante"
    existing = {
        slug: {
            "slug": slug,
            "name": "Alerte dormante",
            "status": "EN COURS",
            "total_occurrences": 10,
            "actions_html": "<p>En attente retour support</p>",
            "assignee": "Bob",
            "last_seen": "12/10/2026",
        }
    }
    tracked, stats = TrackingService.reconcile(categories, existing, "27/10/2026 10:00")

    assert len(tracked) == 1
    entry = tracked[0]
    assert entry["slug"] == slug
    assert entry["count_this_week"] == 0
    assert entry["status"] == "EN COURS"
    assert entry["is_active_now"] is False
    assert stats["ACTIVE_THIS_WEEK"] == 0
    assert stats["TOTAL"] == 1


def test_add_months() -> None:
    from datetime import datetime

    dt = datetime(2026, 10, 28)
    assert TrackingService._add_months(dt, 1) == datetime(2026, 11, 28)
    assert TrackingService._add_months(dt, -3) == datetime(2026, 7, 28)
    assert TrackingService._add_months(datetime(2026, 1, 31), 1) == datetime(2026, 2, 28)
    assert TrackingService._add_months(datetime(2026, 3, 31), -1) == datetime(2026, 2, 28)


def test_build_confluence_storage_html() -> None:
    tracked = [
        {
            "slug": "cat-test",
            "name": "Test Alerte",
            "status": "EN COURS",
            "count_this_week": 10,
            "total_occurrences": 20,
            "occurrences_display": "10 cette semaine",
            "actions_html": "<p>Action 1</p>",
            "assignee": "Alice",
            "last_seen": "27/10/2026",
            "is_active_now": True,
        }
    ]
    stats = {"NOUVELLE": 0, "PTPNEL": 0, "EN COURS": 1, "RÉCURRENTE": 0, "RÉSOLUE": 0, "TOTAL": 1, "ACTIVE_THIS_WEEK": 1}
    artifact_url = "https://gitlab.example.com/username/alerting/-/jobs/artifacts/dev/raw/output/alertes.html"
    artifact_browse = "https://gitlab.example.com/username/alerting/-/jobs/artifacts/dev/browse/output"
    sync_date = "27/10/2026 11:00"

    html_out = TrackingService.build_confluence_storage_html(
        tracked,
        stats,
        sync_date_str=sync_date,
        artifact_url=artifact_url,
        artifact_browse_url=artifact_browse,
    )

    assert '<ac:structured-macro ac:name="info">' in html_out
    assert '⚪ <strong>0</strong> PTPNEL' in html_out
    assert '<ac:structured-macro ac:name="status">' in html_out
    assert '<ac:parameter ac:name="colour">Yellow</ac:parameter>' in html_out
    assert '<ac:parameter ac:name="title">EN COURS</ac:parameter>' in html_out
    assert '<ac:structured-macro ac:name="anchor">' in html_out
    assert 'Test Alerte' in html_out
    assert 'Alice' in html_out
    assert '<p>Action 1</p>' in html_out
    assert artifact_url in html_out
    assert artifact_browse in html_out
    assert '<ac:structured-macro ac:name="panel">' in html_out
    assert 'To-Do Point de Suivi' in html_out
    assert 'Palette de statuts' in html_out
    assert '<th>Échéance</th>' in html_out
    assert '<th>Actions décidées (Point de suivi)</th>' in html_out
    assert 'Dernier rapport visuel' in html_out
    assert f'Dernière exécution : <strong>{sync_date}</strong>' in html_out
    assert 'Période couverte' not in html_out
    assert 'dernières 66h' not in html_out


def test_sanitize_actions_html() -> None:
    # 1. Neutralisation des balises de script et événements inline
    dangerous = "<script>alert('xss')</script><p onclick='evil()'>Action normale <a href='javascript:steal()'>Lien</a></p>"
    cleaned = TrackingService.sanitize_actions_html(dangerous)
    assert "<script>" not in cleaned
    assert "onclick" not in cleaned
    assert "javascript:" not in cleaned
    assert "<p>Action normale <a>Lien</a></p>" in cleaned

    # 2. Préservation des balises de mise en forme légitimes et liens HTTPS
    safe = "<ul><li>Tâche 1</li><li>Tâche 2 sur <a href='https://jira.example.com/123'>Jira</a></li></ul>"
    cleaned_safe = TrackingService.sanitize_actions_html(safe)
    assert "<ul><li>Tâche 1</li>" in cleaned_safe
    assert "rel=\"noopener noreferrer\"" in cleaned_safe
    assert "target=\"_blank\"" in cleaned_safe


def test_reconciliation_uses_latest_occurrence_at() -> None:
    categories = [
        {
            "name": "Alerte test date",
            "count": 3,
            "latest_occurrence_at": "27/10/2026 10:21:47",
        }
    ]
    tracked, _ = TrackingService.reconcile(categories, {}, "27/10/2026 14:00:00")
    assert tracked[0]["last_seen"] == "27/10/2026 10:21:47"


def test_parse_datetime() -> None:
    from datetime import datetime

    assert TrackingService.parse_datetime("27/10/2026 10:21:47") == datetime(2026, 10, 27, 10, 21, 47)
    assert TrackingService.parse_datetime("27/10/2026 à 10:21") == datetime(2026, 10, 27, 10, 21, 0)
    assert TrackingService.parse_datetime("27/10/2026") == datetime(2026, 10, 27, 0, 0, 0)
    assert TrackingService.parse_datetime("2026-07-15 14:30:00") == datetime(2026, 7, 15, 14, 30, 0)
    assert TrackingService.parse_datetime('<time datetime="2026-06-01" /> 09:15:00') == datetime(2026, 6, 1, 9, 15, 0)
    assert TrackingService.parse_datetime("Antérieure") is None
    assert TrackingService.parse_datetime("-") is None
    assert TrackingService.parse_datetime("") is None


def test_is_older_than_months() -> None:
    from datetime import datetime

    ref_date = datetime(2026, 10, 28, 12, 0, 0)
    # Plus de 3 mois (avant le 28 juillet 2026)
    assert TrackingService.is_older_than_months("2026-07-27", ref_date, months=3) is True
    assert TrackingService.is_older_than_months("15/06/2026 10:00:00", ref_date, months=3) is True

    # Moins de 3 mois (après le 28 juillet 2026)
    assert TrackingService.is_older_than_months("2026-07-29", ref_date, months=3) is False
    assert TrackingService.is_older_than_months("01/10/2026 08:00:00", ref_date, months=3) is False

    # Date non parsable
    assert TrackingService.is_older_than_months("Antérieure", ref_date, months=3) is False


def test_separate_archived_categories() -> None:
    from datetime import datetime

    ref_date = datetime(2026, 10, 28, 12, 0, 0)
    categories = [
        # Résolue et plus de 1 mois -> à archiver
        {
            "slug": "res-old",
            "name": "Alerte résolue ancienne",
            "status": "RÉSOLUE",
            "last_seen": "15/09/2026 10:00:00",
            "is_active_now": False,
        },
        # Résolue mais récente (< 1 mois) -> reste active
        {
            "slug": "res-recent",
            "name": "Alerte résolue récente",
            "status": "RÉSOLUE",
            "last_seen": "15/10/2026 10:00:00",
            "is_active_now": False,
        },
        # En cours et ancienne (> 1 mois) -> reste active car non résolue !
        {
            "slug": "encours-old",
            "name": "Alerte en cours ancienne",
            "status": "EN COURS",
            "last_seen": "15/08/2026 10:00:00",
            "is_active_now": False,
        },
    ]

    active, to_archive = TrackingService.separate_archived_categories(categories, ref_dt=ref_date)

    assert len(to_archive) == 1
    assert to_archive[0]["slug"] == "res-old"

    assert len(active) == 2
    active_slugs = {c["slug"] for c in active}
    assert "res-recent" in active_slugs
    assert "encours-old" in active_slugs


def test_parse_confluence_archive_storage() -> None:
    sample_archive_storage = """
    <table>
      <thead>
        <tr>
          <th>Catégorie d'alerte</th>
          <th>Occurrences</th>
          <th>Date de la dernière apparition de l'alerte dans Mattermost</th>
          <th>Porteur</th>
          <th>Échéance</th>
          <th>Actions décidées</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>
            <ac:structured-macro ac:name="anchor">
              <ac:parameter ac:name="">old-alert</ac:parameter>
            </ac:structured-macro>
            <strong>Alerte ancienne archivée</strong>
          </td>
          <td>25 au total</td>
          <td><time datetime="2026-05-10" /> 14:00</td>
          <td>Bob</td>
          <td><time datetime="2026-06-01" /></td>
          <td><p>Problème résolu définitivement</p></td>
        </tr>
      </tbody>
    </table>
    """
    registry = TrackingService.parse_confluence_archive_storage(sample_archive_storage)
    assert "old-alert" in registry
    entry = registry["old-alert"]
    assert entry["name"] == "Alerte ancienne archivée"
    assert entry["status"] == "RÉSOLUE"
    assert entry["assignee"] == "Bob"
    assert entry["due_date"] == "2026-06-01"
    assert "Problème résolu définitivement" in entry["actions_html"]


def test_build_confluence_archive_storage_html() -> None:
    archived = [
        {
            "slug": "archive-cat",
            "name": "Alerte Archivée",
            "occurrences_display": "15 au total",
            "last_seen": "10/05/2026 12:00:00",
            "assignee": "Charlie",
            "due_date": "2026-05-20",
            "actions_html": "<p>Fix validé en prod</p>",
        }
    ]
    html_out = TrackingService.build_confluence_archive_storage_html(
        archived_categories=archived,
        sync_date_str="28/10/2026 à 10:00:00",
        main_page_url="https://confluence.example.com/main",
    )
    assert "Archive des décisions de suivi des alertes résolues depuis plus de 1 mois" in html_out
    assert "Alerte Archivée" in html_out
    assert "15 au total" in html_out
    assert "Charlie" in html_out
    assert "Fix validé en prod" in html_out
    assert "<th>Catégorie d'alerte</th>" in html_out
    assert "<th>Actions décidées (Point de suivi)</th>" in html_out
    assert "<th>Statut</th>" not in html_out  # La colonne Statut n'est pas dans le tableau d'archive
    assert "https://confluence.example.com/main" in html_out


def test_check_ptpnel_duration() -> None:
    from datetime import datetime

    ptpnel_date = datetime(2026, 9, 28, 10, 0, 0)

    # 1. Moins de 4 semaines (21 jours) : pas de warning, pas de suppression
    del_1, warn_1, days_1 = TrackingService.check_ptpnel_duration(ptpnel_date, datetime(2026, 10, 19, 10, 0, 0))
    assert del_1 is False
    assert warn_1 is False
    assert days_1 == 9

    # 2. Au bout de 4 semaines (28 jours) : warning avec 2 jours restants
    del_2, warn_2, days_2 = TrackingService.check_ptpnel_duration(ptpnel_date, datetime(2026, 10, 26, 10, 0, 0))
    assert del_2 is False
    assert warn_2 is True
    assert days_2 == 2

    # 3. À 29 jours : warning avec 1 jour restant
    del_3, warn_3, days_3 = TrackingService.check_ptpnel_duration(ptpnel_date, datetime(2026, 10, 27, 10, 0, 0))
    assert del_3 is False
    assert warn_3 is True
    assert days_3 == 1

    # 4. À plus de 1 mois (31 jours) : suppression requise
    del_4, warn_4, _ = TrackingService.check_ptpnel_duration(ptpnel_date, datetime(2026, 10, 29, 10, 0, 0))
    assert del_4 is True
    assert warn_4 is False


def test_filter_and_tag_ptpnel_categories() -> None:
    from datetime import datetime

    ref_date = datetime(2026, 10, 28, 12, 0, 0)
    categories = [
        # PTPNEL depuis plus de 1 mois -> à supprimer
        {
            "slug": "ptpnel-expired",
            "name": "Alerte PTPNEL expirée",
            "status": "PTPNEL",
            "ptpnel_since": "2026-09-20",
        },
        # PTPNEL à 4 semaines (28 jours) -> warning actif avec jours restants
        {
            "slug": "ptpnel-warning",
            "name": "Alerte PTPNEL 4 semaines",
            "status": "PTPNEL",
            "ptpnel_since": "2026-09-30",
        },
        # PTPNEL récent (1 semaine) -> conservé sans warning
        {
            "slug": "ptpnel-recent",
            "name": "Alerte PTPNEL récente",
            "status": "PTPNEL",
            "ptpnel_since": "2026-10-21",
        },
        # EN COURS ancienne (> 1 mois) -> conservée (seules les PTPNEL sont supprimées)
        {
            "slug": "encours-old",
            "name": "Alerte EN COURS ancienne",
            "status": "EN COURS",
            "last_seen": "2026-09-10",
        },
    ]

    remaining, deleted = TrackingService.filter_and_tag_ptpnel_categories(categories, ref_dt=ref_date)

    # 1 alerte supprimée
    assert len(deleted) == 1
    assert deleted[0]["slug"] == "ptpnel-expired"

    # 3 alertes restantes
    assert len(remaining) == 3
    slugs = {c["slug"] for c in remaining}
    assert "ptpnel-warning" in slugs
    assert "ptpnel-recent" in slugs
    assert "encours-old" in slugs

    # Vérification du warning injecté sur l'alerte à 4 semaines
    warned_cat = next(c for c in remaining if c["slug"] == "ptpnel-warning")
    assert "ptpnel_warning" in warned_cat
    assert "⚠️ Ligne supprimée prochainement" in warned_cat["ptpnel_warning"]
    assert "si le statut ne change pas" in warned_cat["ptpnel_warning"]
    assert warned_cat["ptpnel_days_left"] == 2


def test_build_confluence_storage_html_renders_ptpnel_warning() -> None:
    tracked = [
        {
            "slug": "ptpnel-cat",
            "name": "Alerte en sursis",
            "status": "PTPNEL",
            "count_this_week": 2,
            "total_occurrences": 5,
            "occurrences_display": "2 cette semaine",
            "actions_html": "<p>À définir</p>",
            "assignee": "",
            "due_date": "-",
            "last_seen": "28/10/2026",
            "ptpnel_since": "2026-09-30",
            "ptpnel_warning": "⚠️ Ligne supprimée prochainement (dans 2 jours si le statut ne change pas)",
            "is_active_now": True,
        }
    ]
    stats = {"NOUVELLE": 1, "PTPNEL": 1, "EN COURS": 0, "RÉCURRENTE": 0, "RÉSOLUE": 0, "TOTAL": 2, "ACTIVE_THIS_WEEK": 1}
    html_out = TrackingService.build_confluence_storage_html(
        tracked,
        stats,
        sync_date_str="28/10/2026 à 10:00:00",
    )
    assert "PTPNEL" in html_out
    assert "⚠️ Ligne supprimée prochainement (dans 2 jours si le statut ne change pas)" in html_out
    assert "PTPNEL depuis" in html_out


def test_parse_and_update_deleted_ptpnel_history() -> None:
    from datetime import datetime

    sample_expand_html = """
    <ac:structured-macro ac:name="expand">
      <ac:parameter ac:name="title">🗑️ Historique des alertes sans action supprimées (dernier mois : 2)</ac:parameter>
      <ac:rich-text-body>
        <table>
          <tbody>
            <tr><td>Alerte Récente</td><td><time datetime="2026-10-15" /> 10:00:00</td></tr>
            <tr><td>Alerte Trop Ancienne</td><td><time datetime="2026-08-01" /> 10:00:00</td></tr>
          </tbody>
        </table>
      </ac:rich-text-body>
    </ac:structured-macro>
    """

    parsed = TrackingService.parse_deleted_ptpnel_history(sample_expand_html)
    assert len(parsed) == 2
    assert parsed[0]["name"] == "Alerte Récente"
    assert parsed[1]["name"] == "Alerte Trop Ancienne"

    # Mise à jour avec date de référence au 28/10/2026
    ref_dt = datetime(2026, 10, 28, 12, 0, 0)
    newly_deleted = [{"name": "Nouvelle Alerte Supprimée"}]

    updated = TrackingService.update_deleted_ptpnel_history(parsed, newly_deleted, ref_dt)
    # L'alerte d'août (> 1 mois) doit être purgée, celle du 15 octobre conservée, et la nouvelle ajoutée
    assert len(updated) == 2
    names = [item["name"] for item in updated]
    assert "Alerte Récente" in names
    assert "Nouvelle Alerte Supprimée" in names
    assert "Alerte Trop Ancienne" not in names


def test_build_confluence_storage_html_renders_bruit_table() -> None:
    tracked = [
        {
            "slug": "alerte-normale",
            "name": "Alerte Normale",
            "status": "EN COURS",
            "count_this_week": 3,
            "total_occurrences": 10,
            "occurrences_display": "3 cette semaine",
            "actions_html": "<p>Action</p>",
            "assignee": "Alice",
            "due_date": "-",
            "last_seen": "28/10/2026",
            "is_active_now": True,
        },
        {
            "slug": "alerte-bruit-1",
            "name": "Alerte Bruit Incompressible",
            "status": "BRUIT",
            "count_this_week": 50,
            "total_occurrences": 200,
            "occurrences_display": "50 cette semaine",
            "actions_html": "<p>Épine dans le pied connue</p>",
            "assignee": "",
            "due_date": "-",
            "last_seen": "28/10/2026",
            "is_active_now": True,
        },
    ]
    stats = TrackingService.calculate_stats(tracked)
    assert stats["BRUIT"] == 1

    html_out = TrackingService.build_confluence_storage_html(
        tracked_categories=tracked,
        stats=stats,
        sync_date_str="28/10/2026 à 10:00:00",
    )

    # 1. Bannière et palette
    assert "🟤 <strong>1</strong> Bruit" in html_out
    assert "BRUIT" in html_out
    assert "background-color: #795548" in html_out

    # 2. Tableau principal : contient Alerte Normale, ne contient PAS Alerte Bruit
    # 3. Tableau Bruit situé en dessous : contient Alerte Bruit
    assert "🟤 Tableau des alertes de bruit (1) :" in html_out
    idx_main_cat = html_out.find("Alerte Normale")
    idx_bruit_header = html_out.find("🟤 Tableau des alertes de bruit")
    idx_bruit_cat = html_out.find("Alerte Bruit Incompressible")

    assert idx_main_cat != -1
    assert idx_bruit_header != -1
    assert idx_bruit_cat != -1
    assert idx_main_cat < idx_bruit_header < idx_bruit_cat

    # 4. L'ancienne section d'historique des alertes sans action ne doit plus exister
    assert "Historique des alertes sans action" not in html_out

    # 5. Parsing bidirectionnel : Confluence réextrait correctement l'alerte depuis le tableau de bruit
    parsed = TrackingService.parse_confluence_storage(html_out)
    assert "alerte-bruit-1" in parsed
    assert parsed["alerte-bruit-1"]["status"] == "BRUIT"
    assert parsed["alerte-normale"]["status"] == "EN COURS"


def test_reconciliation_bruit_stays_bruit() -> None:
    categories = [{"name": "Alerte Bruit Récurrente", "count": 10}]
    slug = TrackingService.get_category_slug("Alerte Bruit Récurrente")
    existing = {
        slug: {
            "slug": slug,
            "name": "Alerte Bruit Récurrente",
            "status": "BRUIT",
            "total_occurrences": 100,
            "actions_html": "<p>Épine dans le pied</p>",
            "assignee": "",
            "last_seen": "20/10/2026",
        }
    }
    tracked, stats = TrackingService.reconcile(categories, existing, "28/10/2026 10:00")
    assert tracked[0]["status"] == "BRUIT"
    assert tracked[0]["total_occurrences"] == 110
    assert stats["BRUIT"] == 1


def test_append_weekly_stats_row_new_page() -> None:
    stats = {
        "NOUVELLE": 3,
        "PTPNEL": 1,
        "EN COURS": 4,
        "RÉCURRENTE": 2,
        "RÉSOLUE": 5,
        "BRUIT": 2,
        "PTPNEL_PURGED": 1,
        "TOTAL": 17,
        "ACTIVE_THIS_WEEK": 8,
    }
    html_out = TrackingService.append_weekly_stats_row(
        storage_html="",
        stats=stats,
        sync_date_str="28/10/2026 à 10:30:00",
        total_alerts=150,
        main_page_url="https://confluence.example.com/main",
        report_filename="rapport_alertes_20261028_103000.html",
        artifact_url="https://gitlab.example.com/artifacts/alertes.html",
    )
    assert "📊 Historique hebdomadaire des métriques de suivi des alertes Mattermost" in html_out
    assert "<th>Date d'exécution</th>" in html_out
    assert "<th>Total alertes</th>" in html_out
    assert "<th>PTPNEL (⚪)</th>" in html_out
    assert "<th>Bruit (🟤)</th>" in html_out
    assert "<th>PTPNEL supprimées (&gt; 1 mois) (🗑️)</th>" in html_out
    assert "<th>Rapport HTML (PJ)</th>" in html_out
    assert "rapport_alertes_20261028_103000.html" in html_out
    assert "<ri:attachment" in html_out
    assert "<strong>150</strong>" in html_out
    assert "<strong>8</strong>" in html_out
    assert "https://confluence.example.com/main" in html_out


def test_append_weekly_stats_row_existing_table() -> None:
    existing_html = """
    <table>
      <thead><tr><th>Date d'exécution</th><th>Total alertes</th></tr></thead>
      <tbody>
        <tr><td><time datetime="2026-10-21" /></td><td>120</td></tr>
      </tbody>
    </table>
    """
    stats = {
        "NOUVELLE": 2,
        "PTPNEL": 0,
        "EN COURS": 3,
        "RÉCURRENTE": 1,
        "RÉSOLUE": 6,
        "BRUIT": 1,
        "PTPNEL_PURGED": 0,
        "TOTAL": 12,
        "ACTIVE_THIS_WEEK": 5,
    }
    updated_html = TrackingService.append_weekly_stats_row(
        storage_html=existing_html,
        stats=stats,
        sync_date_str="28/10/2026 à 10:30:00",
        total_alerts=95,
        report_filename="rapport_alertes_20261028_103000.html",
    )
    assert "95" in updated_html
    assert "120" in updated_html
    assert "<th>PTPNEL supprimées (&gt; 1 mois) (🗑️)</th>" in updated_html
    assert "<th>Rapport HTML (PJ)</th>" in updated_html
    assert "rapport_alertes_20261028_103000.html" in updated_html
    # La ligne du 28 doit être insérée avant celle du 21
    idx_28 = updated_html.find("2026-10-28")
    idx_21 = updated_html.find("2026-10-21")
    assert idx_28 != -1 and idx_21 != -1
    assert idx_28 < idx_21




