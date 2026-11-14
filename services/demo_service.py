from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def generate_demo_alerts(hours: int = 168, tz: tzinfo | None = None) -> list[dict[str, Any]]:
    """
    Génère un jeu d'alertes Mattermost réaliste et horodaté sur la période demandée.
    Couvre plusieurs microservices, sévérités et statuts pour illustrer
    l'ensemble des capacités de l'outil d'alerting et de sa machine à états.
    """
    tz_to_use = tz or timezone.utc
    now = datetime.now(tz=tz_to_use)

    # Scénarios d'alertes avec profil de fréquence et sévérité
    scenarios = [
        {
            "category": "Latence P99 supérieure à 1.5s sur api-gateway",
            "service": "api-gateway",
            "title": "Alerte Latence API",
            "status": "FIRING",
            "severity": "MAJOR",
            "offsets_hours": [2, 5, 8, 14, 22, 28, 35, 42, 50, 70, 92, 110, 134, 150, 160],
            "description": "Le temps de réponse P99 du service api-gateway dépasse le seuil critique de 1.5s.",
        },
        {
            "category": "Taux d'erreurs 5xx supérieur à 2% sur payment-service",
            "service": "payment-service",
            "title": "Erreurs HTTP 5xx Passerelle de Paiement",
            "status": "FIRING:2",
            "severity": "CRITICAL",
            "offsets_hours": [1, 3, 6, 12, 18, 24, 48, 72, 96],
            "description": "Le pourcentage d'erreurs 5xx sur payment-service a atteint 3.8% suite à un timeout PSP.",
        },
        {
            "category": "Consommation mémoire > 85% sur database-cluster",
            "service": "database-cluster",
            "title": "Saturation Mémoire PostgreSQL",
            "status": "FIRING",
            "severity": "WARNING",
            "offsets_hours": [4, 10, 26, 32, 55],
            "description": "La consommation RAM du pod database-cluster-primary dépasse le seuil d'avertissement (88%).",
        },
        {
            "category": "Redémarrage intempestif du conteneur bi-agent",
            "service": "bi-agent",
            "title": "CrashLoopBackOff Conteneur",
            "status": "FIRING",
            "severity": "WARNING",
            "offsets_hours": [7, 19, 31, 43, 67, 89, 120, 142],
            "description": "Le pod bi-agent a redémarré avec le code de sortie 137 (OOMKilled).",
        },
        {
            "category": "Timeout de synchronisation batch comptable",
            "service": "batch-engine",
            "title": "Dépassement SLA Traitement Nocturne",
            "status": "RESOLVED",
            "severity": "INFO",
            "offsets_hours": [20, 44, 68],
            "description": "Le batch nocturne de synchronisation des écritures a excédé la fenêtre de tir de 45 minutes.",
        },
    ]

    alerts: list[dict[str, Any]] = []
    alert_counter = 1

    for sc in scenarios:
        for offset in sc["offsets_hours"]:
            if offset > hours:
                continue

            alert_time = now - timedelta(hours=offset)
            timestamp_ms = int(alert_time.timestamp() * 1000)
            created_at_str = alert_time.strftime("%d/%m/%Y %H:%M:%S")
            post_id = f"demo_post_{alert_counter:04d}"

            msg = (
                f"[{sc['status']}] {sc['severity']} - {sc['title']}\n"
                f"**Service :** `{sc['service']}`\n"
                f"**Description :** {sc['category']}\n"
                f"{sc['description']}"
            )

            alerts.append({
                "id": post_id,
                "message": msg,
                "created_at": created_at_str,
                "timestamp": timestamp_ms,
                "titles": [sc["title"]],
                "attachments": [
                    {
                        "title": sc["title"],
                        "text": sc["description"],
                        "description": sc["category"],
                    }
                ],
                "permalink": f"https://mattermost.example.com/demo/pl/{post_id}",
            })
            alert_counter += 1

    # Tri chronologique décroissant (du plus récent au plus ancien, conforme à l'API Mattermost)
    alerts.sort(key=lambda a: a["timestamp"], reverse=True)
    logger.info("[DÉMO] %d alertes simulées générées sur les dernières %dh.", len(alerts), hours)
    return alerts


def convert_confluence_storage_to_html(xhtml: str) -> str:
    """
    Convertit le format de stockage propriétaire Atlassian XHTML (macros <ac:*>, <ri:*>)
    en HTML stylisé fidèle à l'interface de Confluence Server / Data Center.
    """
    if not xhtml:
        return "<p><em>Aucun contenu.</em></p>"

    out = xhtml

    # 1. Macro Statut Atlassian : <ac:structured-macro ac:name="status">...
    def replace_status(m: re.Match) -> str:
        body = m.group(1)
        title_m = re.search(r'<ac:parameter ac:name="title">([^<]+)</ac:parameter>', body)
        colour_m = re.search(r'<ac:parameter ac:name="colour">([^<]+)</ac:parameter>', body)
        title = title_m.group(1).strip() if title_m else "STATUT"
        colour = colour_m.group(1).strip().lower() if colour_m else "grey"
        return f'<span class="aui-lozenge status-{colour}">{html.escape(title)}</span>'

    out = re.sub(
        r'<ac:structured-macro ac:name="status">(.*?)</ac:structured-macro>',
        replace_status,
        out,
        flags=re.DOTALL,
    )

    # 2. Macro Panneau d'information : <ac:structured-macro ac:name="panel">...
    def replace_panel(m: re.Match) -> str:
        body = m.group(1)
        title_m = re.search(r'<ac:parameter ac:name="title">([^<]+)</ac:parameter>', body)
        content_m = re.search(r'<ac:rich-text-body>(.*?)</ac:rich-text-body>', body, flags=re.DOTALL)
        title = title_m.group(1).strip() if title_m else ""
        content = content_m.group(1).strip() if content_m else ""
        header_html = f'<div class="panel-header">{html.escape(title)}</div>' if title else ""
        return f'<div class="confluence-panel">{header_html}<div class="panel-body">{content}</div></div>'

    out = re.sub(
        r'<ac:structured-macro ac:name="panel">(.*?)</ac:structured-macro>',
        replace_panel,
        out,
        flags=re.DOTALL,
    )

    # 3. Macro Ancre : <ac:structured-macro ac:name="anchor">...
    def replace_anchor(m: re.Match) -> str:
        body = m.group(1)
        slug_m = re.search(r'<ac:parameter ac:name="">([^<]+)</ac:parameter>', body)
        slug = slug_m.group(1).strip() if slug_m else ""
        return f'<a id="{slug}" class="confluence-anchor" name="{slug}"></a>'

    out = re.sub(
        r'<ac:structured-macro ac:name="anchor">(.*?)</ac:structured-macro>',
        replace_anchor,
        out,
        flags=re.DOTALL,
    )

    # 4. Balises <time datetime="AAAA-MM-JJ" />
    def replace_time(m: re.Match) -> str:
        dt_val = m.group(1)
        parts = dt_val.split("-")
        label = f"{parts[2]}/{parts[1]}/{parts[0]}" if len(parts) == 3 else dt_val
        return f'<time class="confluence-time" datetime="{dt_val}">{label}</time>'

    out = re.sub(r'<time datetime="([^"]+)"\s*/>', replace_time, out)

    # 5. Pièce jointe Confluence : <ri:attachment ri:filename="..." />
    def replace_attachment(m: re.Match) -> str:
        fname = m.group(1)
        return f'<a href="alertes.html" class="confluence-attachment-link" title="Ouvrir le rapport HTML attaché">📎 {html.escape(fname)}</a>'

    out = re.sub(r'<ri:attachment ri:filename="([^"]+)"\s*/>', replace_attachment, out)

    # 6. Styliser les tableaux et lignes
    out = out.replace("<table>", '<table class="confluenceTable">')
    out = out.replace("<th>", '<th class="confluenceTh">')
    out = out.replace("<td>", '<td class="confluenceTd">')

    # Nettoyer d'éventuelles balises Atlassian orphelines
    out = re.sub(r'</?ac:[^>]+>', '', out)
    out = re.sub(r'</?ri:[^>]+>', '', out)

    return out


def render_confluence_page_html(
    title: str,
    storage_xhtml: str,
    active_page_id: str,
    sync_date_str: str,
) -> str:
    """
    Génère une page web complète au rendu fidèle à Atlassian Confluence Server / Data Center.
    """
    body_html = convert_confluence_storage_to_html(storage_xhtml)

    pages_nav = [
        ("suivi", "confluence_suivi.html", "📋 1. Point de suivi actif"),
        ("archive", "confluence_archive.html", "🗄️ 2. Archive (> 1 mois)"),
        ("stats", "confluence_stats.html", "📈 3. Statistiques hebdomadaires"),
    ]

    nav_tabs_html = []
    for pid, url, label in pages_nav:
        active_class = " nav-tab-active" if pid == active_page_id else ""
        nav_tabs_html.append(f'<a href="{url}" class="nav-tab{active_class}">{label}</a>')

    tabs_str = "\n".join(nav_tabs_html)

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <title>{html.escape(title)} - Confluence (Simulation Démo)</title>
    <style>
        * {{
            box-sizing: border-box;
        }}
        html {{
            scroll-behavior: smooth;
        }}
        body {{
            margin: 0;
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans", Ubuntu, "Droid Sans", "Helvetica Neue", sans-serif;
            color: #172b4d;
            background-color: #f4f5f7;
            font-size: 14px;
            line-height: 1.42857;
        }}

        /* Barre d'en-tête Atlassian Confluence */
        .atlassian-header {{
            height: 44px;
            background-color: #0052cc;
            color: #ffffff;
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 16px;
            font-size: 14px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.12);
        }}
        .header-brand {{
            display: flex;
            align-items: center;
            gap: 12px;
            font-weight: 700;
            letter-spacing: 0.3px;
        }}
        .header-brand svg {{
            fill: #ffffff;
            width: 22px;
            height: 22px;
        }}
        .header-nav {{
            display: flex;
            align-items: center;
            gap: 16px;
            font-size: 13px;
            font-weight: 500;
        }}
        .header-nav a {{
            color: #deebff;
            text-decoration: none;
            padding: 4px 8px;
            border-radius: 3px;
        }}
        .header-nav a:hover {{
            background-color: rgba(255,255,255,0.15);
            color: #ffffff;
        }}

        /* Bannière du mode démo */
        .demo-callout {{
            background-color: #ebecf0;
            border-bottom: 1px solid #dfe1e6;
            padding: 8px 24px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 10px;
            font-size: 12px;
            color: #42526e;
        }}
        .demo-callout strong {{
            color: #0052cc;
        }}
        .demo-back-btn {{
            background-color: #0052cc;
            color: #ffffff !important;
            padding: 4px 12px;
            border-radius: 3px;
            text-decoration: none;
            font-weight: 600;
            transition: background 0.15s ease;
        }}
        .demo-back-btn:hover {{
            background-color: #0747a6;
        }}

        /* Navigation entre les pages Confluence du suivi */
        .demo-tabs-bar {{
            background-color: #ffffff;
            border-bottom: 2px solid #dfe1e6;
            padding: 0 24px;
            display: flex;
            gap: 4px;
            overflow-x: auto;
        }}
        .nav-tab {{
            display: inline-block;
            padding: 10px 16px;
            color: #42526e;
            text-decoration: none;
            font-weight: 600;
            font-size: 13px;
            border-bottom: 2px solid transparent;
            margin-bottom: -2px;
            transition: all 0.15s ease;
        }}
        .nav-tab:hover {{
            color: #0052cc;
        }}
        .nav-tab-active {{
            color: #0052cc;
            border-bottom-color: #0052cc;
            background-color: #f4f8ff;
        }}

        /* Conteneur principal de la page Confluence */
        .page-wrapper {{
            max-width: 1400px;
            margin: 20px auto 40px auto;
            background: #ffffff;
            border: 1px solid #dfe1e6;
            border-radius: 4px;
            box-shadow: 0 1px 3px rgba(9, 30, 66, 0.08);
            padding: 32px 40px;
        }}

        /* Fil d'ariane */
        .breadcrumbs {{
            font-size: 12px;
            color: #6b778c;
            margin-bottom: 12px;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .breadcrumbs a {{
            color: #6b778c;
            text-decoration: none;
        }}
        .breadcrumbs a:hover {{
            text-decoration: underline;
        }}

        /* Titre de page */
        h1.page-title {{
            font-size: 28px;
            font-weight: 600;
            color: #172b4d;
            margin: 0 0 8px 0;
            line-height: 1.25;
        }}
        .page-meta {{
            font-size: 12px;
            color: #6b778c;
            margin-bottom: 24px;
            display: flex;
            align-items: center;
            gap: 12px;
            border-bottom: 1px solid #ebecf0;
            padding-bottom: 12px;
        }}
        .meta-avatar {{
            width: 22px;
            height: 22px;
            border-radius: 50%;
            background-color: #0052cc;
            color: #ffffff;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            font-size: 11px;
            font-weight: 700;
        }}

        /* Corps de la page et macros Confluence */
        .page-content {{
            font-size: 14px;
            color: #172b4d;
            line-height: 1.5;
        }}
        .page-content h2 {{
            font-size: 20px;
            font-weight: 600;
            margin-top: 24px;
            border-bottom: 1px solid #ebecf0;
            padding-bottom: 6px;
        }}

        /* Tableaux Confluence */
        table.confluenceTable {{
            width: 100%;
            border-collapse: collapse;
            margin: 16px 0 24px 0;
            font-size: 13px;
        }}
        th.confluenceTh {{
            background-color: #f4f5f7;
            color: #172b4d;
            font-weight: 600;
            text-align: left;
            padding: 8px 10px;
            border: 1px solid #dfe1e6;
            vertical-align: middle;
            font-size: 12px;
        }}
        td.confluenceTd {{
            padding: 8px 10px;
            border: 1px solid #dfe1e6;
            vertical-align: top;
            line-height: 1.45;
        }}
        table.confluenceTable tr:hover {{
            background-color: #fafbfc;
        }}

        /* Mise en valeur au scroll vers l'ancre */
        tr:has(a:target), tr.target-highlight {{
            background-color: #deebff !important;
            outline: 2px solid #2684ff;
            transition: all 0.5s ease;
        }}

        /* Pastilles de statuts Confluence (AUI Lozenges) */
        .aui-lozenge {{
            display: inline-block;
            font-size: 11px;
            font-weight: 700;
            line-height: 1;
            padding: 3px 6px;
            border-radius: 3px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            vertical-align: baseline;
            white-space: nowrap;
        }}
        .status-yellow {{
            background: #fff0b3;
            color: #172b4d;
            border: 1px solid #ffe380;
        }}
        .status-green {{
            background: #e3fcef;
            color: #006644;
            border: 1px solid #abf5d1;
        }}
        .status-red {{
            background: #ffebe6;
            color: #bf2600;
            border: 1px solid #ffbdad;
        }}
        .status-blue {{
            background: #deebff;
            color: #0747a6;
            border: 1px solid #b3d4ff;
        }}
        .status-grey {{
            background: #f4f5f7;
            color: #42526e;
            border: 1px solid #dfe1e6;
        }}
        .status-brown {{
            background: #795548;
            color: #ffffff;
            border: 1px solid #5d4037;
        }}

        /* Panneaux d'information Confluence */
        .confluence-panel {{
            border: 1px solid #b3d4ff;
            background-color: #f4f8ff;
            border-radius: 4px;
            margin: 16px 0;
            overflow: hidden;
        }}
        .panel-header {{
            background-color: #deebff;
            color: #0747a6;
            font-weight: 600;
            padding: 8px 12px;
            font-size: 13px;
        }}
        .panel-body {{
            padding: 10px 14px;
            font-size: 13px;
            line-height: 1.5;
            color: #172b4d;
        }}
        .panel-body p, .panel-body ul {{
            margin: 4px 0;
        }}

        /* Date time pill */
        time.confluence-time {{
            background-color: #ebecf0;
            color: #172b4d;
            padding: 1px 5px;
            border-radius: 3px;
            font-size: 12px;
            font-family: inherit;
        }}

        .confluence-attachment-link {{
            color: #0052cc;
            text-decoration: none;
            font-weight: 500;
        }}
        .confluence-attachment-link:hover {{
            text-decoration: underline;
        }}

        /* Pied de page */
        .page-footer {{
            margin-top: 40px;
            padding-top: 16px;
            border-top: 1px solid #ebecf0;
            font-size: 12px;
            color: #6b778c;
            text-align: center;
        }}
    </style>
</head>
<body>

    <!-- Barre d'en-tête Confluence -->
    <header class="atlassian-header">
        <div class="header-brand">
            <svg viewBox="0 0 24 24"><path d="M2.5 12.5C2.5 6.98 6.98 2.5 12.5 2.5s10 4.48 10 10-4.48 10-10 10S2.5 18.02 2.5 12.5zm6.8 4.2c.4 0 .7-.3.7-.7V8c0-.4-.3-.7-.7-.7s-.7.3-.7.7v8c0 .4.3.7.7.7zm5.4 0c.4 0 .7-.3.7-.7V8c0-.4-.3-.7-.7-.7s-.7.3-.7.7v8c0 .4.3.7.7.7z"/></svg>
            <span>Confluence Server</span>
        </div>
        <div class="header-nav">
            <a href="#">Espaces</a>
            <a href="#">Personnes</a>
            <a href="#">Calendriers</a>
            <a href="#" style="background: rgba(255,255,255,0.2); font-weight: 700;">Créer</a>
        </div>
    </header>

    <!-- Bandeau Mode Démonstration -->
    <div class="demo-callout">
        <div>
            💡 <strong>MODE DÉMONSTRATION AUTONOME</strong> : Rendu web fidèle généré par le script à partir du stockage Confluence XHTML.
        </div>
        <div>
            <a href="alertes.html" class="demo-back-btn">📊 Revenir au rapport visuel d'alerting</a>
        </div>
    </div>

    <!-- Navigation par onglets entre les 3 pages Confluence -->
    <nav class="demo-tabs-bar">
        {tabs_str}
    </nav>

    <!-- Conteneur Confluence -->
    <main class="page-wrapper">
        <nav class="breadcrumbs">
            <a href="#">Espaces</a> &gt;
            <a href="#">ALERTS</a> &gt;
            <a href="#">Pages</a> &gt;
            <span>{html.escape(title)}</span>
        </nav>

        <h1 class="page-title">{html.escape(title)}</h1>

        <div class="page-meta">
            <span class="meta-avatar">BA</span>
            <span>Mis à jour automatiquement par <strong>Bot Alerting</strong> le {sync_date_str or 'aujourd’hui'}</span>
            <span>• Espace : <strong>ALERTS</strong></span>
        </div>

        <article class="page-content">
            {body_html}
        </article>

        <footer class="page-footer">
            Confluence 8.5 Data Center • Démonstration générée automatiquement pour le projet d'alerting
        </footer>
    </main>

    <script>
        // Effet de mise en valeur de la ligne cible lorsqu'une ancre est présente dans l'URL
        function highlightTargetRow() {{
            const hash = window.location.hash;
            if (hash) {{
                const target = document.querySelector(hash);
                if (target) {{
                    const row = target.closest('tr');
                    if (row) {{
                        document.querySelectorAll('tr.target-highlight').forEach(r => r.classList.remove('target-highlight'));
                        row.classList.add('target-highlight');
                        row.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
                    }}
                }}
            }}
        }}
        window.addEventListener('load', highlightTargetRow);
        window.addEventListener('hashchange', highlightTargetRow);
    </script>
</body>
</html>
"""


class MockConfluenceClient:
    """
    Client Confluence simulé en mémoire pour le mode démonstration.
    Représente un registre d'équipe pré-rempli pour tester l'ensemble
    du cycle de vie et de la réconciliation (NOUVELLE, RÉCURRENTE, PTPNEL, BRUIT, archivage).
    Gère également l'exportation des 3 pages au format HTML réaliste dans output/.
    """

    def __init__(
        self,
        url: str = "https://confluence.example.com",
        token: str = "demo_token",
        page_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.page_id = page_id or "123456789"
        self.archive_page_id = "123456780"
        self.stats_page_id = "123456781"
        self.space_key = "ALERTS"

        # État initial de la page principale de suivi (simulant un registre existant)
        main_storage = """
        <p>Registre de suivi des alertes de production de l'équipe.</p>
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
                  <ac:parameter ac:name="">latence-p99-superieure-a-1-5s-sur-api-gateway</ac:parameter>
                </ac:structured-macro>
                <strong>Latence P99 supérieure à 1.5s sur api-gateway</strong>
              </td>
              <td>35 cette semaine</td>
              <td><time datetime="2026-11-08" /> 14:00:00</td>
              <td>Alice</td>
              <td><time datetime="2026-11-18" /></td>
              <td><ul><li>Optimisation du pool de connexions Redis</li><li>Augmentation des replicas HPA</li></ul></td>
            </tr>
            <tr>
              <td>
                <ac:structured-macro ac:name="status">
                  <ac:parameter ac:name="title">RÉSOLUE</ac:parameter>
                  <ac:parameter ac:name="colour">Green</ac:parameter>
                </ac:structured-macro>
              </td>
              <td>
                <ac:structured-macro ac:name="anchor">
                  <ac:parameter ac:name="">taux-d-erreurs-5xx-superieur-a-2-sur-payment-service</ac:parameter>
                </ac:structured-macro>
                <strong>Taux d'erreurs 5xx supérieur à 2% sur payment-service</strong>
              </td>
              <td>-</td>
              <td><time datetime="2026-11-01" /> 09:30:00</td>
              <td>Bob</td>
              <td>-</td>
              <td><p>Patch v2.4.1 déployé pour gérer les retries PSP</p></td>
            </tr>
            <tr>
              <td>
                <ac:structured-macro ac:name="status">
                  <ac:parameter ac:name="title">PTPNEL</ac:parameter>
                  <ac:parameter ac:name="colour">Grey</ac:parameter>
                </ac:structured-macro>
              </td>
              <td>
                <ac:structured-macro ac:name="anchor">
                  <ac:parameter ac:name="">timeout-de-synchronisation-batch-comptable</ac:parameter>
                </ac:structured-macro>
                <strong>Timeout de synchronisation batch comptable</strong>
              </td>
              <td>2 cette semaine</td>
              <td><time datetime="2026-10-12" /> 04:00:00</td>
              <td>-</td>
              <td>-</td>
              <td><p>Anomalie sans impact client direct, en attente d'arbitrage</p></td>
            </tr>
            <tr>
              <td>
                <ac:structured-macro ac:name="status">
                  <ac:parameter ac:name="title">RÉSOLUE</ac:parameter>
                  <ac:parameter ac:name="colour">Green</ac:parameter>
                </ac:structured-macro>
              </td>
              <td>
                <ac:structured-macro ac:name="anchor">
                  <ac:parameter ac:name="">panne-temporaire-dns-sur-auth-service</ac:parameter>
                </ac:structured-macro>
                <strong>Panne temporaire DNS sur auth-service</strong>
              </td>
              <td>-</td>
              <td><time datetime="2026-09-15" /> 11:20:00</td>
              <td>Charlie</td>
              <td>-</td>
              <td><p>Bascule effectuée vers le résolveur CoreDNS haute disponibilité</p></td>
            </tr>
            <tr>
              <td>
                <span style="background-color: #795548; color: #ffffff; padding: 2px 8px; border-radius: 3px; font-weight: bold; font-size: 11px;">BRUIT</span>
              </td>
              <td>
                <ac:structured-macro ac:name="anchor">
                  <ac:parameter ac:name="">redemarrage-intempestif-du-conteneur-bi-agent</ac:parameter>
                </ac:structured-macro>
                <strong>Redémarrage intempestif du conteneur bi-agent</strong>
              </td>
              <td>12 cette semaine</td>
              <td><time datetime="2026-11-09" /> 16:15:00</td>
              <td>-</td>
              <td>-</td>
              <td><p>Comportement périodique du ramasse-miettes, sans impact métier</p></td>
            </tr>
          </tbody>
        </table>
        """

        archive_storage = """
        <p>Historique des alertes résolues depuis plus de 1 mois.</p>
        <table>
          <thead>
            <tr>
              <th>Catégorie d'alerte</th>
              <th>Occurrences lors du suivi</th>
              <th>Dernière apparition</th>
              <th>Porteur</th>
              <th>Échéance</th>
              <th>Actions décidées (Point de suivi)</th>
            </tr>
          </thead>
          <tbody></tbody>
        </table>
        """

        stats_storage = """
        <p>Statistiques hebdomadaires du suivi des alertes.</p>
        <table>
          <thead>
            <tr>
              <th>Date d'exécution</th>
              <th>Total alertes</th>
              <th>Catégories</th>
              <th>Actives</th>
              <th>Nouvelles</th>
              <th>En cours</th>
              <th>Récurrentes</th>
              <th>PTPNEL</th>
              <th>Résolues</th>
              <th>Bruit</th>
              <th>Archivées</th>
              <th>Rapport HTML (PJ)</th>
            </tr>
          </thead>
          <tbody></tbody>
        </table>
        """

        self._pages: dict[str, dict[str, Any]] = {
            self.page_id: {
                "id": self.page_id,
                "title": "Point de suivi hebdomadaire des alertes",
                "space": {"key": self.space_key},
                "version": {"number": 1},
                "body": {"storage": {"value": main_storage}},
            },
            self.archive_page_id: {
                "id": self.archive_page_id,
                "title": "Archive des décisions de suivi des alertes résolues depuis plus de 1 mois",
                "space": {"key": self.space_key},
                "version": {"number": 1},
                "body": {"storage": {"value": archive_storage}},
            },
            self.stats_page_id: {
                "id": self.stats_page_id,
                "title": "Statistiques d'évolution de l'alerting",
                "space": {"key": self.space_key},
                "version": {"number": 1},
                "body": {"storage": {"value": stats_storage}},
            },
        }

        self.attached_files: list[dict[str, Any]] = []

    def __enter__(self) -> MockConfluenceClient:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def close(self) -> None:
        pass

    def get_page(self, page_id: str | None = None) -> dict[str, Any]:
        target_id = page_id or self.page_id
        if target_id not in self._pages:
            raise ValueError(f"Page Confluence simulée introuvable : {target_id}")
        return self._pages[target_id]

    def update_page(
        self,
        page_id: str | None,
        title: str,
        space_key: str,
        storage_html: str,
        next_version: int,
    ) -> dict[str, Any]:
        target_id = page_id or self.page_id
        if target_id not in self._pages:
            self._pages[target_id] = {
                "id": target_id,
                "title": title,
                "space": {"key": space_key},
                "version": {"number": next_version},
                "body": {"storage": {"value": storage_html}},
            }
        else:
            self._pages[target_id]["title"] = title
            self._pages[target_id]["version"]["number"] = next_version
            self._pages[target_id]["body"]["storage"]["value"] = storage_html

        logger.info("[DÉMO CONFLUENCE] Mise à jour simulée de la page '%s' (v%d).", title, next_version)
        return self._pages[target_id]

    def attach_file(
        self,
        page_id: str | None,
        filename: str,
        content: bytes | str,
        content_type: str = "text/html; charset=utf-8",
        comment: str | None = None,
    ) -> dict[str, Any]:
        target_id = page_id or self.page_id
        record = {
            "page_id": target_id,
            "filename": filename,
            "size": len(content) if isinstance(content, (bytes, str)) else 0,
            "comment": comment,
        }
        self.attached_files.append(record)
        logger.info("[DÉMO CONFLUENCE] Pièce jointe simulée '%s' attachée à la page %s.", filename, target_id)
        return {"id": "demo_att_1", "title": filename}

    def build_page_url(self, page_data: dict[str, Any] | None = None) -> str:
        """
        En mode démo, les URLs de pages pointent vers les fichiers HTML locaux générés
        pour garantir une navigation interconnectée fluide dans le navigateur.
        """
        target_id = (page_data.get("id") if page_data else None) or self.page_id
        if target_id == self.archive_page_id:
            return "confluence_archive.html"
        elif target_id == self.stats_page_id:
            return "confluence_stats.html"
        return "confluence_suivi.html"

    def export_html_pages(self, output_dir: Path, sync_date_str: str = "") -> dict[str, Path]:
        """
        Exporte les 3 pages Confluence simulées sous forme de fichiers HTML stylisés
        dans le répertoire de sortie pour permettre une démonstration visuelle complète.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        date_label = sync_date_str or datetime.now().strftime("%d/%m/%Y à %H:%M:%S")

        pages_to_export = [
            (self.page_id, "confluence_suivi.html", "suivi"),
            (self.archive_page_id, "confluence_archive.html", "archive"),
            (self.stats_page_id, "confluence_stats.html", "stats"),
        ]

        generated_files: dict[str, Path] = {}

        for page_id, filename, active_id in pages_to_export:
            page_data = self._pages.get(page_id, {})
            title = page_data.get("title", "Page Confluence")
            storage_xhtml = page_data.get("body", {}).get("storage", {}).get("value", "")

            full_html = render_confluence_page_html(
                title=title,
                storage_xhtml=storage_xhtml,
                active_page_id=active_id,
                sync_date_str=date_label,
            )

            file_path = output_dir / filename
            file_path.write_text(full_html, encoding="utf-8")
            generated_files[active_id] = file_path
            logger.info("[DÉMO] Écran Confluence généré : %s", file_path.resolve())

        return generated_files


class MockMattermostClient:
    """
    Client Mattermost simulé en mémoire pour le mode démonstration.
    """

    def __init__(
        self,
        hours: int = 168,
        tz: tzinfo | None = None,
        **kwargs: Any,
    ) -> None:
        self.hours = hours
        self.tz = tz

    def __enter__(self) -> MockMattermostClient:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass

    def close(self) -> None:
        pass

    def fetch_messages(self) -> list[dict[str, Any]]:
        return generate_demo_alerts(hours=self.hours, tz=self.tz)
