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

# Nettoyage des métriques dynamiques et des identifiants éphémères de pods
RE_DYNAMIC_METRIC = re.compile(r"\s*\(current\s*:[^)]*\)", re.IGNORECASE)
RE_POD_HASH = re.compile(r"(-[a-f0-9]{8,10}-[a-z0-9]{4,5})\b", re.IGNORECASE)
RE_CLEAN_SPACES = re.compile(r"\s+")
RE_NON_ALPHANUM = re.compile(r"[^a-z0-9]+")

STATUS_COLORS = {
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
    "RÉCURRENTE": 1,
    "RECURRENTE": 1,
    "NOUVELLE": 2,
    "PTPNEL": 2,
    "NOUV": 2,
    "EN COURS": 3,
    "RÉSOLUE": 4,
    "RESOLUE": 4,
    "BRUIT": 5,
}


class TrackingService:
    """
    Service de réconciliation et de suivi des actions sur les catégories d'alertes.
    Permet d'associer un historique pérenne (statuts, actions décidées, porteurs)
    issu de Confluence à chaque cycle d'analyse d'alerting.
    """

    @classmethod
    def normalize_category_name(cls, name: str) -> str:
        """
        Normalise le nom de la catégorie pour éviter les doublons dus aux valeurs dynamiques
        (ex: '(current : 91)', suffixes de réplicas de pods '-8578c8c7ff-wld7g', espaces multiples).
        """
        if not name:
            return "Alerte sans description"

        text = html.unescape(name)
        # Supprimer les métriques dynamiques comme (current : 91)
        text = RE_DYNAMIC_METRIC.sub("", text)
        # Supprimer les identifiants éphémères de réplicas de pods
        text = RE_POD_HASH.sub("", text)
        # Nettoyer les espaces
        text = RE_CLEAN_SPACES.sub(" ", text).strip()
        return text

    @classmethod
    def get_category_slug(cls, name: str) -> str:
        """
        Génère un identifiant textuel stable (slug) pour la catégorie,
        utilisé comme ancre Confluence et clé de réconciliation.
        """
        normalized = cls.normalize_category_name(name).lower()
        # Supprimer les accents (é -> e, à -> a, etc.)
        deaccented = unicodedata.normalize("NFKD", normalized).encode("ASCII", "ignore").decode("utf-8")
        slug = RE_NON_ALPHANUM.sub("-", deaccented).strip("-")
        return slug[:120] if slug else "categorie"

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
        Nettoie et sanétise le contenu HTML des actions saisies dans Confluence
        pour prévenir toute faille XSS lors du rendu dans le rapport HTML.
        Supprime les balises et attributs dangereux (script, iframe, on*, javascript:).
        """
        if not html_str:
            return ""

        soup = BeautifulSoup(html_str, "html.parser")

        # 1. Supprimer les balises dangereuses et leur contenu
        for tag in soup.find_all(["script", "style", "iframe", "object", "embed", "applet", "form"]):
            tag.decompose()

        # 2. Nettoyer les balises non autorisées et attributs suspects
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
        Formate la date avec la balise native Confluence <time datetime="AAAA-MM-JJ" />
        suivie de l'heure précise (HH:mm:ss) pour permettre le tri chronologique natif dans Confluence.
        Retourne '-' si aucune date valide n'est renseignée.
        """
        if not val or val.strip() in ("-", "Antérieure", "anterieure", "Inconnue"):
            return "-"
        if "<time" in val:
            return val

        # Format JJ/MM/AAAA avec heure optionnelle
        m_fr = re.search(r"(\d{2})/(\d{2})/(\d{4})(?:(?:\s+[àa]\s+|\s+)(\d{2}:\d{2}(?::\d{2})?))?", val)
        if m_fr:
            day, month, year, time_part = m_fr.groups()
            time_str = f" {time_part}" if time_part else ""
            return f'<time datetime="{year}-{month}-{day}" />{time_str}'

        # Format AAAA-MM-JJ avec heure optionnelle
        m_iso = re.search(r"(\d{4})-(\d{2})-(\d{2})(?:(?:\s+[àa]\s+|\s+)(\d{2}:\d{2}(?::\d{2})?))?", val)
        if m_iso:
            year, month, day, time_part = m_iso.groups()
            time_str = f" {time_part}" if time_part else ""
            return f'<time datetime="{year}-{month}-{day}" />{time_str}'

        return html.escape(val)

    @classmethod
    def _detect_column_indices(cls, headers: list[str]) -> dict[str, int]:
        """Détecte les index des colonnes à partir des libellés d'en-têtes."""
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
            if any(term in h for term in ["statut", "status"]):
                indices["status"] = idx
            elif any(term in h for term in ["apparition", "mattermost", "date", "détection", "detection"]):
                indices["last_seen"] = idx
            elif any(term in h for term in ["catégorie", "categorie"]):
                indices["category"] = idx
            elif any(term in h for term in ["occurrence", "nombre"]):
                indices["occurrences"] = idx
            elif any(term in h for term in ["échéance", "echeance", "due"]):
                indices["due_date"] = idx
            elif any(term in h for term in ["action", "décision", "suivi"]):
                indices["actions"] = idx
            elif any(term in h for term in ["porteur", "responsable", "assign"]):
                indices["assignee"] = idx
        return indices

    @classmethod
    def _parse_row_entry(
        cls,
        cells: list[Any],
        col_indices: dict[str, int],
        default_status: str = "NOUVELLE",
    ) -> dict[str, Any] | None:
        """Parse une ligne de tableau Confluence (principale ou archive) et extrait la fiche catégorie."""
        if len(cells) < 2:
            return None

        # 1. Catégorie et slug
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

        # 2. Statut et nouv_since
        col_st = col_indices.get("status", -1)
        nouv_since = None
        if col_st >= 0 and col_st < len(cells):
            status_cell = cells[col_st]
            status_macro = status_cell.find("ac:structured-macro", attrs={"ac:name": "status"})
            if status_macro:
                param_title = status_macro.find("ac:parameter", attrs={"ac:name": "title"})
                raw_status = param_title.get_text(strip=True) if param_title else status_macro.get_text(strip=True)
            else:
                raw_status = status_cell.get_text(strip=True)
            status = cls._normalize_status(raw_status)

            if status in ("PTPNEL", "NOUV"):
                status = "PTPNEL"
                time_tag_status = status_cell.find("time")
                if time_tag_status and time_tag_status.get("datetime"):
                    nouv_since = time_tag_status.get("datetime")
                else:
                    m_date = re.search(r"(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})", status_cell.get_text())
                    if m_date:
                        nouv_since = m_date.group(1)
        else:
            status = default_status

        # 3. Occurrences
        col_occ = col_indices.get("occurrences", -1)
        occ_cell = cells[col_occ] if 0 <= col_occ < len(cells) else None
        occ_text = occ_cell.get_text(strip=True) if occ_cell else ""
        prev_total = cls._extract_total_occurrences(occ_text)

        # 4. Actions décidées (sanétisées)
        col_act = col_indices.get("actions", -1)
        act_cell = cells[col_act] if 0 <= col_act < len(cells) else None
        actions_html = (
            cls.sanitize_actions_html("".join(str(c) for c in act_cell.contents).strip())
            if act_cell
            else ""
        )

        # 5. Porteur
        col_ass = col_indices.get("assignee", -1)
        ass_cell = cells[col_ass] if 0 <= col_ass < len(cells) else None
        assignee = ass_cell.get_text(strip=True) if ass_cell else ""

        # 6. Échéance
        col_due = col_indices.get("due_date", -1)
        due_cell = cells[col_due] if 0 <= col_due < len(cells) else None
        due_date = "-"
        if due_cell:
            time_tag = due_cell.find("time")
            due_date = time_tag.get("datetime", "") if time_tag else due_cell.get_text(strip=True)
        if not due_date or due_date.strip() in ("", "-", "Inconnue"):
            due_date = "-"

        # 7. Date dernière apparition
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
            "ptpnel_since": nouv_since,
            "nouv_since": nouv_since,
        }

    @classmethod
    def parse_confluence_storage(cls, storage_html: str) -> dict[str, dict[str, Any]]:
        """
        Analyse le contenu XHTML Confluence existant et extrait les fiches de catégories.
        Parcourt le tableau principal et le tableau des alertes de bruit.
        Préserve fidèlement les actions saisies et les porteurs définis par l'équipe.
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
            # Vérifier qu'il s'agit bien d'un tableau d'alertes (principal ou bruit)
            if not any(term in " ".join(headers) for term in ["catégorie", "categorie", "statut", "status", "alerte"]):
                continue

            col_indices = cls._detect_column_indices(headers)
            for row in rows[1:]:
                entry = cls._parse_row_entry(row.find_all(["td", "th"]), col_indices, default_status="NOUVELLE")
                if entry:
                    registry[entry["slug"]] = entry

        logger.info("[SUIVI] %d catégories existantes lues depuis la page Confluence.", len(registry))
        return registry

    @classmethod
    def _normalize_status(cls, raw_status: str) -> str:
        """Standardise les libellés de statut."""
        upper = raw_status.upper().strip()
        if "BRUIT" in upper or "NOISE" in upper:
            return "BRUIT"
        if "RECUR" in upper or "RÉCUR" in upper:
            return "RÉCURRENTE"
        if "RESOL" in upper or "RÉSOL" in upper or "CLOS" in upper or "TERM" in upper:
            return "RÉSOLUE"
        if "COURS" in upper or "IN PROGRESS" in upper:
            return "EN COURS"
        if "PTPNEL" in upper:
            return "PTPNEL"
        if upper in ("NOUV", "NOUV.", "NOUVEAU") or (upper.startswith("NOUV") and not upper.startswith("NOUVELLE")):
            return "PTPNEL"
        if "NOUVELLE" in upper or "NEW" in upper:
            return "NOUVELLE"
        return upper if upper else "NOUVELLE"

    @classmethod
    def has_action_taken(cls, actions_html: str | None, assignee: str | None = None) -> bool:
        """
        Détermine si une réelle action ou un porteur a été renseigné par l'équipe.
        Retourne False si le champ est vide ou s'il s'agit uniquement du texte indicatif par défaut.
        """
        if assignee and assignee.strip() and assignee.strip() not in ("-", "À définir", "a definir"):
            return True

        if not actions_html:
            return False

        # Supprimer le balisage HTML pour inspecter le texte brut
        soup = BeautifulSoup(actions_html, "html.parser")
        text = soup.get_text(strip=True).lower()
        if not text:
            return False

        # Liste des placeholders indicatifs par défaut
        placeholders = [
            "-",
            "à définir",
            "a definir",
            "à définir lors du point de suivi",
            "a definir lors du point de suivi",
            "en attente",
            "aucun",
            "aucune",
        ]
        if text in placeholders:
            return False

        return True

    @classmethod
    def _extract_total_occurrences(cls, text: str) -> int:
        """Extrait le nombre d'occurrences depuis le texte de la cellule."""
        match_first = re.search(r"\b(\d+)\b", text)
        if match_first:
            try:
                return int(match_first.group(1))
            except ValueError:
                pass
        return 0

    @classmethod
    def reconcile(
        cls,
        categories: list[dict[str, Any]],
        existing_registry: dict[str, dict[str, Any]],
        current_date_str: str,
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        """
        Réconcilie la liste des catégories d'alertes détectées sur la période courante
        avec le registre existant issu de Confluence.

        Applique la machine à états :
        - NOUVELLE : première apparition
        - PTPNEL : était NOUVELLE lors d'une exécution précédente mais sans prise en charge
        - EN COURS : prise en charge (action ou porteur renseigné)
        - RÉSOLUE : précédemment résolue
        - RÉCURRENTE : était résolue, mais de nouvelles occurrences réapparaissent !
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
                prev_status = prev.get("status", "NOUVELLE")
                prev_total = prev.get("total_occurrences", 0)
                new_total = prev_total + count_now

                # Machine à états :
                # 0. Alerte au statut BRUIT (positionné manuellement) :
                if prev_status == "BRUIT":
                    new_status = "BRUIT"
                # 1. Alerte précédemment RÉSOLUE qui réapparaît -> RÉCURRENTE
                elif prev_status in ("RÉSOLUE", "RESOLUE"):
                    new_status = "RÉCURRENTE"
                    logger.info(
                        "[SUIVI] Alerte '%s' réapparue (%d occurrences) -> Statut basculé en RÉCURRENTE.",
                        norm_name[:50],
                        count_now,
                    )
                # 2. Alerte NOUVELLE de la semaine précédente :
                elif prev_status == "NOUVELLE":
                    # Si une vraie action a été saisie par l'équipe -> EN COURS
                    if cls.has_action_taken(prev.get("actions_html"), prev.get("assignee")):
                        new_status = "EN COURS"
                    else:
                        # Pas d'action prise -> bascule au statut PTPNEL (pas traitée, pas nouvelle, encore là)
                        new_status = "PTPNEL"
                        logger.info(
                            "[SUIVI] Alerte '%s' (précédemment NOUVELLE sans action prise) -> Statut basculé en PTPNEL.",
                            norm_name[:50],
                        )
                # 3. Alerte déjà au statut PTPNEL / NOUV :
                elif prev_status in ("PTPNEL", "NOUV"):
                    # Si une action a été saisie entre-temps -> EN COURS
                    if cls.has_action_taken(prev.get("actions_html"), prev.get("assignee")):
                        new_status = "EN COURS"
                    else:
                        # Conserve impérativement le statut PTPNEL
                        new_status = "PTPNEL"
                else:
                    new_status = prev_status

                # Conserver les actions décidées, le porteur et l'échéance
                actions_html = prev.get("actions_html") or ""
                assignee = prev.get("assignee") or ""
                due_date = prev.get("due_date") or "-"

                # Date de la dernière apparition de l'alerte dans Mattermost
                latest_mm_date = cat.get("latest_occurrence_at")
                if not latest_mm_date:
                    occs = cat.get("occurrences") or []
                    if occs:
                        latest_mm_date = occs[0].get("created_at")
                last_seen_date = latest_mm_date or current_date_str

                # Suivi de la date d'entrée au statut PTPNEL
                if new_status == "PTPNEL":
                    ptpnel_since = (
                        prev.get("ptpnel_since")
                        or prev.get("nouv_since")
                        or prev.get("last_seen")
                        or current_date_str
                    )
                else:
                    ptpnel_since = None

                entry = {
                    "slug": slug,
                    "name": norm_name,
                    "raw_name": cat_name,
                    "status": new_status,
                    "count_this_week": count_now,
                    "total_occurrences": new_total,
                    "occurrences_display": f"{count_now} cette semaine",
                    "actions_html": actions_html,
                    "assignee": assignee,
                    "due_date": due_date,
                    "last_seen": last_seen_date,
                    "ptpnel_since": ptpnel_since,
                    "nouv_since": ptpnel_since,
                    "is_active_now": True,
                }
            else:
                # Nouvelle catégorie d'alerte jamais rencontrée
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
                    "status": "NOUVELLE",
                    "count_this_week": count_now,
                    "total_occurrences": count_now,
                    "occurrences_display": f"{count_now} cette semaine",
                    "actions_html": "<p><em>À définir lors du point de suivi</em></p>",
                    "assignee": "",
                    "due_date": "-",
                    "last_seen": last_seen_date,
                    "ptpnel_since": None,
                    "nouv_since": None,
                    "is_active_now": True,
                }

            tracked_categories.append(entry)
            # Enrichir directement l'objet catégorie d'origine pour affichage dans le template HTML
            cat["tracking"] = entry

        # Intégrer également les catégories existantes qui n'ont pas eu d'alertes cette semaine
        for slug, prev in existing_registry.items():
            if slug not in handled_slugs:
                prev_status = prev.get("status", "EN COURS")
                prev_total = prev.get("total_occurrences", 0)

                # Si l'alerte est BRUIT, elle reste BRUIT
                if prev_status == "BRUIT":
                    curr_status = "BRUIT"
                # Si une alerte était NOUVELLE sans action prise, elle bascule en PTPNEL
                elif prev_status == "NOUVELLE":
                    if cls.has_action_taken(prev.get("actions_html"), prev.get("assignee")):
                        curr_status = "EN COURS"
                    else:
                        curr_status = "PTPNEL"
                elif prev_status in ("PTPNEL", "NOUV"):
                    if cls.has_action_taken(prev.get("actions_html"), prev.get("assignee")):
                        curr_status = "EN COURS"
                    else:
                        curr_status = "PTPNEL"
                else:
                    curr_status = prev_status

                ptpnel_since = (
                    prev.get("ptpnel_since")
                    or prev.get("nouv_since")
                    or prev.get("last_seen")
                    or current_date_str
                    if curr_status == "PTPNEL"
                    else None
                )

                entry = {
                    "slug": slug,
                    "name": prev.get("name", slug),
                    "raw_name": prev.get("name", slug),
                    "status": curr_status,
                    "count_this_week": 0,
                    "total_occurrences": prev_total,
                    "occurrences_display": "0 cette semaine",
                    "actions_html": prev.get("actions_html") or "",
                    "assignee": prev.get("assignee") or "",
                    "due_date": prev.get("due_date") or "-",
                    "last_seen": prev.get("last_seen") or "Antérieure",
                    "ptpnel_since": ptpnel_since,
                    "nouv_since": ptpnel_since,
                    "is_active_now": False,
                }
                tracked_categories.append(entry)

        # Calcul des statistiques globales
        stats = cls.calculate_stats(tracked_categories)

        # Tri logique pour Confluence :
        # 1. Par statut (RÉCURRENTE > NOUVELLE > PTPNEL > EN COURS > RÉSOLUE > BRUIT)
        # 2. Par occurrences sur la semaine courante (décroissant)
        # 3. Par total d'occurrences (décroissant)
        tracked_categories.sort(
            key=lambda e: (
                STATUS_RANKS.get(e["status"], 99),
                -e["count_this_week"],
                -e["total_occurrences"],
            )
        )

        return tracked_categories, stats

    @classmethod
    def calculate_stats(
        cls,
        tracked_categories: list[dict[str, Any]],
        deleted_ptpnel_count: int = 0,
        deleted_nouv_count: int | None = None,
    ) -> dict[str, int]:
        """Calcule les statistiques globales pour une liste de catégories suivies."""
        del_count = deleted_nouv_count if deleted_nouv_count is not None else deleted_ptpnel_count
        ptpnel_count = sum(1 for e in tracked_categories if e.get("status") in ("PTPNEL", "NOUV"))
        return {
            "NOUVELLE": sum(1 for e in tracked_categories if e.get("status") == "NOUVELLE"),
            "PTPNEL": ptpnel_count,
            "NOUV": ptpnel_count,  # alias rétrocompatible
            "EN COURS": sum(1 for e in tracked_categories if e.get("status") == "EN COURS"),
            "RÉCURRENTE": sum(1 for e in tracked_categories if e.get("status") in ("RÉCURRENTE", "RECURRENTE")),
            "RÉSOLUE": sum(1 for e in tracked_categories if e.get("status") in ("RÉSOLUE", "RESOLUE")),
            "BRUIT": sum(1 for e in tracked_categories if e.get("status") == "BRUIT"),
            "PTPNEL_PURGED": del_count,
            "PTPNEL_DELETED": del_count,
            "SANS_ACTION": del_count,
            "PTPNEL_DELETED_LAST_MONTH": del_count,
            "NOUV_DELETED_LAST_MONTH": del_count,  # alias rétrocompatible
            "TOTAL": len(tracked_categories),
            "ACTIVE_THIS_WEEK": sum(1 for e in tracked_categories if e.get("is_active_now")),
        }

    @classmethod
    def parse_deleted_ptpnel_history(cls, storage_html: str) -> list[dict[str, str]]:
        """
        Extrait l'historique des alertes PTPNEL supprimées sans action depuis la macro expand Confluence.
        """
        history: list[dict[str, str]] = []
        if not storage_html:
            return history

        soup = BeautifulSoup(storage_html, "html.parser")
        for expand in soup.find_all("ac:structured-macro", attrs={"ac:name": "expand"}):
            param = expand.find("ac:parameter", attrs={"ac:name": "title"})
            title_text = param.get_text(strip=True).lower() if param else ""
            if "sans action" in title_text or "supprim" in title_text:
                for tr in expand.find_all("tr"):
                    if tr.find("th"):
                        continue
                    tds = tr.find_all("td")
                    if len(tds) >= 2:
                        cat_name = tds[0].get_text(strip=True)
                        time_tag = tds[1].find("time")
                        if time_tag and time_tag.get("datetime"):
                            del_date = time_tag.get("datetime")
                        else:
                            del_date = tds[1].get_text(strip=True)
                        if cat_name and "aucune alerte" not in cat_name.lower():
                            history.append({"name": cat_name, "deleted_at": del_date})
        return history

    parse_deleted_nouv_history = parse_deleted_ptpnel_history  # alias

    @classmethod
    def update_deleted_ptpnel_history(
        cls,
        existing_history: list[dict[str, str]],
        newly_deleted: list[dict[str, Any]],
        ref_dt: datetime,
    ) -> list[dict[str, str]]:
        """
        Met à jour l'historique des alertes sans action :
        - Conserve uniquement les suppressions vieilles de moins de 1 mois par rapport à ref_dt.
        - Ajoute les alertes nouvellement supprimées horodatées à ref_dt.
        """
        updated: list[dict[str, str]] = []
        seen_names = set()

        # 1. Conserver les suppressions existantes vieilles de moins de 1 mois
        for item in existing_history:
            del_date = item.get("deleted_at")
            if not cls.is_older_than_months(del_date, ref_dt, months=1):
                updated.append(item)
                seen_names.add(item.get("name"))

        # 2. Ajouter les nouvelles suppressions
        ref_iso = ref_dt.strftime("%Y-%m-%d %H:%M:%S")
        for cat in newly_deleted:
            name = cat.get("name") or cat.get("raw_name") or "Alerte"
            if name not in seen_names:
                updated.append({"name": name, "deleted_at": ref_iso})
                seen_names.add(name)

        return updated

    update_deleted_nouv_history = update_deleted_ptpnel_history  # alias

    @classmethod
    def build_deleted_ptpnel_expand_html(cls, deleted_history: list[dict[str, str]]) -> str:
        """Génère la macro Confluence expand listant les alertes sans action supprimées sur le dernier mois."""
        count = len(deleted_history)
        rows_html = []
        for item in deleted_history:
            name = html.escape(item.get("name", "Alerte"))
            date_cell = cls.format_confluence_date_cell(item.get("deleted_at", ""))
            rows_html.append(f'<tr><td>{name}</td><td>{date_cell}</td></tr>')

        tbody = (
            "".join(rows_html)
            if rows_html
            else '<tr><td colspan="2"><em>Aucune alerte PTPNEL supprimée sur les 30 derniers jours.</em></td></tr>'
        )

        return (
            f'<ac:structured-macro ac:name="expand">'
            f'<ac:parameter ac:name="title">🗑️ Historique des alertes sans action supprimées (dernier mois : {count})</ac:parameter>'
            f'<ac:rich-text-body>'
            f'<p><em>Ce tableau recense les alertes restées plus de 1 mois au statut PTPNEL sans prise en charge par l\'équipe et purgées sur les 30 derniers jours :</em></p>'
            f'<table class="wrapped">'
            f'<thead><tr><th>Catégorie d\'alerte</th><th>Date de suppression</th></tr></thead>'
            f'<tbody>{tbody}</tbody>'
            f'</table>'
            f'</ac:rich-text-body>'
            f'</ac:structured-macro>'
        )

    build_deleted_nouv_expand_html = build_deleted_ptpnel_expand_html  # alias

    @classmethod
    def parse_datetime(cls, val: str | None) -> datetime | None:
        """
        Extrait et parse une date depuis une chaîne texte ou balise Confluence <time>.
        Gère les formats JJ/MM/AAAA [HH:MM[:SS]], AAAA-MM-JJ [HH:MM[:SS]] et ISO.
        """
        if not val or str(val).strip().lower() in ("-", "antérieure", "anterieure", "inconnue", ""):
            return None

        val_str = str(val).strip()

        # Format Confluence <time datetime="AAAA-MM-JJ" />
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

        # Format français JJ/MM/AAAA avec heure optionnelle
        m_fr = re.search(r"(\d{2})/(\d{2})/(\d{4})(?:(?:\s+[àa]\s+|\s+)(\d{2}):(\d{2})(?::(\d{2}))?)?", val_str)
        if m_fr:
            day, month, year, hh, mm, ss = m_fr.groups()
            hh = hh or "00"
            mm = mm or "00"
            ss = ss or "00"
            try:
                return datetime.strptime(f"{year}-{month}-{day} {hh}:{mm}:{ss}", "%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass

        # Format ISO AAAA-MM-JJ avec heure optionnelle
        m_iso = re.search(r"(\d{4})-(\d{2})-(\d{2})(?:(?:\s+[àa]\s+|\s+|T)(\d{2}):(\d{2})(?::(\d{2}))?)?", val_str)
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
        """Décale une date de delta_months mois calendaires (gère les limites de mois et bissextiles)."""
        year = dt.year + (dt.month + delta_months - 1) // 12
        month = (dt.month + delta_months - 1) % 12 + 1
        max_days = calendar.monthrange(year, month)[1]
        return dt.replace(year=year, month=month, day=min(dt.day, max_days))

    @classmethod
    def is_older_than_months(
        cls,
        date_val: str | datetime | None,
        ref_dt: datetime,
        months: int = 3,
    ) -> bool:
        """
        Détermine si la date fournie est strictement antérieure à 'months' mois par rapport à ref_dt.
        """
        if not date_val:
            return False
        if isinstance(date_val, datetime):
            dt = date_val
        else:
            dt = cls.parse_datetime(str(date_val))

        if dt is None:
            return False

        # Harmonisation des fuseaux horaires (comparaison en datetime naïf)
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
        Sépare les catégories d'alertes actives de celles à archiver :
        Sont déplacées dans l'archive les catégories ayant le statut RÉSOLUE
        dont la date de dernière apparition dans Mattermost est strictement antérieure à 1 mois (months).
        """
        active: list[dict[str, Any]] = []
        to_archive: list[dict[str, Any]] = []

        for cat in tracked_categories:
            status = cat.get("status", "")
            is_resolved = status in ("RÉSOLUE", "RESOLUE")
            last_seen = cat.get("last_seen")

            if is_resolved and cls.is_older_than_months(last_seen, ref_dt, months=months):
                logger.info(
                    "[ARCHIVAGE] Alerte '%s' résolue depuis plus de %d mois (dernière apparition: %s) -> Déplacement vers l'archive.",
                    cat.get("name", "")[:50],
                    months,
                    last_seen,
                )
                to_archive.append(cat)
            else:
                active.append(cat)

        return active, to_archive

    @classmethod
    def check_ptpnel_duration(
        cls,
        ptpnel_since: str | datetime | None,
        ref_dt: datetime,
    ) -> tuple[bool, bool, int]:
        """
        Calcule la durée passée au statut PTPNEL par rapport à ref_dt.
        Retourne (should_delete, should_warn, days_left):
        - should_delete: True si resté au statut PTPNEL depuis plus de 1 mois.
        - should_warn: True si resté au statut PTPNEL depuis au moins 4 semaines (28 jours) et pas encore supprimé.
        - days_left: nombre de jours restants avant suppression (au moins 1 si should_warn est True).
        """
        if not ptpnel_since:
            return False, False, 30

        if isinstance(ptpnel_since, datetime):
            ptpnel_dt = ptpnel_since
        else:
            ptpnel_dt = cls.parse_datetime(str(ptpnel_since))

        if ptpnel_dt is None:
            return False, False, 30

        ref_cmp = ref_dt.replace(tzinfo=None) if ref_dt.tzinfo else ref_dt
        ptpnel_cmp = ptpnel_dt.replace(tzinfo=None) if ptpnel_dt.tzinfo else ptpnel_dt

        del_date = cls._add_months(ptpnel_cmp, 1)
        days_in_ptpnel = (ref_cmp.date() - ptpnel_cmp.date()).days
        days_left = (del_date.date() - ref_cmp.date()).days

        # Plus de 1 mois -> suppression
        should_delete = ref_cmp >= del_date or days_left <= 0
        # Au bout de 4 semaines (28 jours) et pas encore supprimé -> avertissement
        should_warn = not should_delete and days_in_ptpnel >= 28

        return should_delete, should_warn, max(1, days_left)

    check_nouv_duration = check_ptpnel_duration  # alias rétrocompatible

    @classmethod
    def filter_and_tag_ptpnel_categories(
        cls,
        tracked_categories: list[dict[str, Any]],
        ref_dt: datetime,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Filtre et étiquette les alertes au statut PTPNEL :
        - Supprime du tableau les alertes au statut PTPNEL depuis plus de 1 mois.
        - Ajoute un warning pour celles restées au statut PTPNEL depuis au moins 4 semaines,
          avec le nombre de jours restants avant suppression.
        """
        remaining: list[dict[str, Any]] = []
        deleted: list[dict[str, Any]] = []

        for cat in tracked_categories:
            status = cat.get("status", "")
            if status in ("PTPNEL", "NOUV"):
                since_date = cat.get("ptpnel_since") or cat.get("nouv_since") or cat.get("last_seen")
                should_delete, should_warn, days_left = cls.check_ptpnel_duration(since_date, ref_dt)

                if should_delete:
                    logger.info(
                        "[SUIVI] Alerte PTPNEL '%s' au statut PTPNEL depuis plus de 1 mois (depuis %s) "
                        "-> Suppression définitive du tableau Confluence.",
                        cat.get("name", "")[:50],
                        since_date,
                    )
                    deleted.append(cat)
                    continue

                if should_warn:
                    days_text = f"{days_left} jour" if days_left == 1 else f"{days_left} jours"
                    warn_msg = f"⚠️ Ligne supprimée prochainement (dans {days_text} si le statut ne change pas)"
                    cat["ptpnel_warning"] = warn_msg
                    cat["nouv_warning"] = warn_msg  # alias
                    cat["ptpnel_days_left"] = days_left
                    cat["nouv_days_left"] = days_left

            remaining.append(cat)

        return remaining, deleted

    filter_and_tag_nouv_categories = filter_and_tag_ptpnel_categories  # alias rétrocompatible

    @classmethod
    def parse_confluence_archive_storage(cls, storage_html: str) -> dict[str, dict[str, Any]]:
        """
        Analyse le contenu XHTML Confluence de la page d'archive et extrait les fiches archivées.
        Colonnes attendues : Catégorie d'alerte, Occurrences, Date de dernière apparition, Porteur, Échéance, Actions décidées.
        """
        registry: dict[str, dict[str, Any]] = {}
        if not storage_html:
            return registry

        soup = BeautifulSoup(storage_html, "html.parser")
        tables = soup.find_all("table")
        if not tables or not tables[0].find_all("tr"):
            return registry

        rows = tables[0].find_all("tr")
        headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]
        col_indices = cls._detect_column_indices(headers)

        for row in rows[1:]:
            entry = cls._parse_row_entry(row.find_all(["td", "th"]), col_indices, default_status="RÉSOLUE")
            if entry:
                registry[entry["slug"]] = entry

        logger.info("[ARCHIVAGE] %d catégories archivées lues depuis la page d'archive Confluence.", len(registry))
        return registry

    @classmethod
    def build_confluence_archive_storage_html(
        cls,
        archived_categories: list[dict[str, Any]],
        sync_date_str: str,
        main_page_url: str | None = None,
    ) -> str:
        """
        Génère le format XHTML Confluence pour la page d'archive des alertes résolues depuis plus de 1 mois.
        Colonnes : Catégorie d'alerte, Occurrences, Date de la dernière apparition de l'alerte dans Mattermost, Porteur, Échéance, Actions décidées.
        """
        parts: list[str] = []

        main_link_html = ""
        if main_page_url:
            main_link_html = (
                f'<p style="margin: 6px 0;">📋 <strong>Page active :</strong> '
                f'<a href="{html.escape(main_page_url)}">Consulter le tableau de suivi actif Confluence ↗</a></p>'
            )

        parts.append(
            f'<ac:structured-macro ac:name="info">'
            f'<ac:rich-text-body>'
            f'<p><strong>📦 Archive des décisions de suivi des alertes résolues depuis plus de 1 mois</strong></p>'
            f'<p>Dernière exécution : <strong>{sync_date_str}</strong>.<br/>'
            f'Total des alertes archivées : <strong>{len(archived_categories)}</strong></p>'
            f'{main_link_html}'
            f'</ac:rich-text-body>'
            f'</ac:structured-macro>'
        )

        parts.append('<table class="wrapped">')
        parts.append('<colgroup>')
        parts.append('<col style="width: 320px;"/>')
        parts.append('<col style="width: 120px;"/>')
        parts.append('<col style="width: 180px;"/>')
        parts.append('<col style="width: 130px;"/>')
        parts.append('<col style="width: 130px;"/>')
        parts.append('<col style="width: 380px;"/>')
        parts.append('</colgroup>')

        parts.append('<thead><tr>')
        parts.append('<th>Catégorie d\'alerte</th>')
        parts.append('<th>Occurrences</th>')
        parts.append('<th>Date de la dernière apparition de l\'alerte dans Mattermost</th>')
        parts.append('<th>Porteur</th>')
        parts.append('<th>Échéance</th>')
        parts.append('<th>Actions décidées (Point de suivi)</th>')
        parts.append('</tr></thead>')

        parts.append('<tbody>')
        for cat in archived_categories:
            slug = cat.get("slug", "")
            name = html.escape(cat.get("name", ""))
            occurrences_display = html.escape(
                cat.get("occurrences_display") or f"{cat.get('total_occurrences', 0)} au total"
            )
            assignee = html.escape(cat.get("assignee", ""))
            due_date = cat.get("due_date", "-")
            due_date_html = cls.format_confluence_date_cell(due_date) if due_date != "-" else "-"
            actions_html = cat.get("actions_html") or "<p><em>-</em></p>"
            date_cell_html = cls.format_confluence_date_cell(cat.get("last_seen", ""))

            parts.append('<tr>')
            # 1. Catégorie avec ancre
            parts.append(
                f'<td>'
                f'<ac:structured-macro ac:name="anchor">'
                f'<ac:parameter ac:name="">{slug}</ac:parameter>'
                f'</ac:structured-macro>'
                f'<strong>{name}</strong>'
                f'</td>'
            )
            # 2. Occurrences
            parts.append(f'<td>{occurrences_display}</td>')
            # 3. Date dernière apparition
            parts.append(f'<td>{date_cell_html}</td>')
            # 4. Porteur
            parts.append(f'<td>{assignee}</td>')
            # 5. Échéance
            parts.append(f'<td>{due_date_html}</td>')
            # 6. Actions décidées
            parts.append(f'<td>{actions_html}</td>')
            parts.append('</tr>')

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
        Incrémente le tableau de la page des statistiques Confluence avec les métriques de la semaine courante
        et le rapport HTML de l'exécution en pièce jointe.
        Si la page ou le tableau n'existe pas encore, initialise la structure complète.
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
                    f'<br/><small><a href="{html.escape(artifact_url)}">Artefact GitLab ↗</a></small>'
                )
        elif artifact_url:
            report_cell = f'<a href="{html.escape(artifact_url)}">📊 Rapport HTML (Artefact) ↗</a>'
        else:
            report_cell = "-"

        row_html = (
            f'<tr>'
            f'<td>{cls.format_confluence_date_cell(sync_date_str)}</td>'
            f'<td><strong>{total_alerts}</strong></td>'
            f'<td><strong>{stats.get("ACTIVE_THIS_WEEK", 0)}</strong></td>'
            f'<td>{stats.get("TOTAL", 0)}</td>'
            f'<td><ac:structured-macro ac:name="status"><ac:parameter ac:name="title">{stats.get("NOUVELLE", 0)}</ac:parameter><ac:parameter ac:name="colour">Blue</ac:parameter></ac:structured-macro></td>'
            f'<td><ac:structured-macro ac:name="status"><ac:parameter ac:name="title">{stats.get("PTPNEL", stats.get("NOUV", 0))}</ac:parameter><ac:parameter ac:name="colour">Grey</ac:parameter></ac:structured-macro></td>'
            f'<td><ac:structured-macro ac:name="status"><ac:parameter ac:name="title">{stats.get("EN COURS", 0)}</ac:parameter><ac:parameter ac:name="colour">Yellow</ac:parameter></ac:structured-macro></td>'
            f'<td><ac:structured-macro ac:name="status"><ac:parameter ac:name="title">{stats.get("RÉCURRENTE", 0)}</ac:parameter><ac:parameter ac:name="colour">Red</ac:parameter></ac:structured-macro></td>'
            f'<td><ac:structured-macro ac:name="status"><ac:parameter ac:name="title">{stats.get("RÉSOLUE", 0)}</ac:parameter><ac:parameter ac:name="colour">Green</ac:parameter></ac:structured-macro></td>'
            f'<td><span style="background-color: #795548; color: #ffffff; padding: 2px 8px; border-radius: 3px; font-weight: bold; font-size: 11px; display: inline-block;">{stats.get("BRUIT", 0)}</span></td>'
            f'<td><ac:structured-macro ac:name="status"><ac:parameter ac:name="title">{stats.get("PTPNEL_PURGED", stats.get("SANS_ACTION", 0))}</ac:parameter><ac:parameter ac:name="colour">Grey</ac:parameter></ac:structured-macro></td>'
            f'<td>{report_cell}</td>'
            f'</tr>'
        )

        soup = BeautifulSoup(storage_html or "", "html.parser")
        table = soup.find("table")

        if not table:
            main_link_html = ""
            if main_page_url:
                main_link_html = (
                    f'<p style="margin: 6px 0;">📋 <strong>Tableau de bord :</strong> '
                    f'<a href="{html.escape(main_page_url)}">Consulter la page principale d\'analyse et de suivi ↗</a></p>'
                )

            return (
                f'<ac:structured-macro ac:name="info">'
                f'<ac:rich-text-body>'
                f'<p><strong>📊 Historique hebdomadaire des métriques de suivi des alertes Mattermost</strong></p>'
                f'<p>Ce tableau est incrémenté automatiquement à chaque exécution hebdomadaire de la pipeline pour suivre l\'évolution dans le temps.</p>'
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
                f'<th>Date d\'exécution</th>'
                f'<th>Total alertes</th>'
                f'<th>Catégories actives</th>'
                f'<th>Total catégories</th>'
                f'<th>Nouvelles (🔹)</th>'
                f'<th>PTPNEL (⚪)</th>'
                f'<th>En cours (🔸)</th>'
                f'<th>Récurrentes (🔺)</th>'
                f'<th>Résolues (✅)</th>'
                f'<th>Bruit (🟤)</th>'
                f'<th>PTPNEL supprimées (&gt; 1 mois) (🗑️)</th>'
                f'<th>Rapport HTML (PJ)</th>'
                f'</tr></thead>'
                f'<tbody>'
                f'{row_html}'
                f'</tbody></table>'
            )

        # Vérifier si l'en-tête thead contient déjà les colonnes PTPNEL supprimées et Rapport HTML
        thead = table.find("thead")
        if thead:
            tr_head = thead.find("tr")
            if tr_head:
                for th in tr_head.find_all(["th", "td"]):
                    txt = th.get_text(strip=True).lower()
                    if "nouvelle" in txt:
                        th.string = "Nouvelles (🔹)"
                    elif "nouv" in txt:
                        th.string = "PTPNEL (⚪)"

                has_report_col = any(
                    "rapport" in th.get_text(strip=True).lower() for th in tr_head.find_all(["th", "td"])
                )

                has_purged_col = any(
                    "supprim" in th.get_text(strip=True).lower() or "purg" in th.get_text(strip=True).lower()
                    for th in tr_head.find_all(["th", "td"])
                )

                if not has_purged_col:
                    new_th_purged = soup.new_tag("th")
                    new_th_purged.string = "PTPNEL supprimées (> 1 mois) (🗑️)"
                    if has_report_col:
                        for th in tr_head.find_all(["th", "td"]):
                            if "rapport" in th.get_text(strip=True).lower():
                                th.insert_before(new_th_purged)
                                break
                    else:
                        tr_head.append(new_th_purged)

                    # Ajuster les lignes existantes dans tbody en insérant une cellule statut '0'
                    for tbody_tag in table.find_all("tbody"):
                        for row in tbody_tag.find_all("tr"):
                            cells = row.find_all(["td", "th"])
                            if cells:
                                td_tag = soup.new_tag("td")
                                status_tag = soup.new_tag("ac:structured-macro", attrs={"ac:name": "status"})
                                p_title = soup.new_tag("ac:parameter", attrs={"ac:name": "title"})
                                p_title.string = "0"
                                p_color = soup.new_tag("ac:parameter", attrs={"ac:name": "colour"})
                                p_color.string = "Grey"
                                status_tag.append(p_title)
                                status_tag.append(p_color)
                                td_tag.append(status_tag)

                                if has_report_col and len(cells) >= 1:
                                    cells[-1].insert_before(td_tag)
                                else:
                                    row.append(td_tag)

                if not has_report_col:
                    new_th = soup.new_tag("th")
                    new_th.string = "Rapport HTML (PJ)"
                    tr_head.append(new_th)

        # Vérifier colgroup
        colgroup = table.find("colgroup")
        if colgroup:
            while len(colgroup.find_all("col")) < 12:
                new_col = soup.new_tag("col", style="width: 160px;")
                colgroup.append(new_col)

        tbody = table.find("tbody")
        if not tbody:
            tbody = soup.new_tag("tbody")
            table.append(tbody)

        new_tr = BeautifulSoup(row_html, "html.parser").find("tr")
        if new_tr:
            tbody.insert(0, new_tr)

        return str(soup)

    @classmethod
    def _build_confluence_row_html(cls, cat: dict[str, Any]) -> str:
        """Génère le code XHTML Confluence pour une ligne de tableau de suivi."""
        status = cat.get("status", "NOUVELLE")
        color = STATUS_COLORS.get(status, "Grey")
        slug = cat.get("slug", "")
        name = html.escape(cat.get("name", ""))
        occurrences_display = html.escape(cat.get("occurrences_display", ""))
        assignee = html.escape(cat.get("assignee", ""))
        due_date = cat.get("due_date", "-")
        due_date_html = cls.format_confluence_date_cell(due_date) if due_date != "-" else "-"
        actions_html = cat.get("actions_html") or "<p><em>À définir</em></p>"
        date_cell_html = cls.format_confluence_date_cell(cat.get("last_seen", ""))

        if status == "BRUIT":
            status_parts = [
                f'<span style="background-color: #795548; color: #ffffff; padding: 2px 8px; border-radius: 3px; font-weight: bold; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; display: inline-block;">'
                f'BRUIT'
                f'</span>'
            ]
        else:
            status_parts = [
                f'<ac:structured-macro ac:name="status">',
                f'<ac:parameter ac:name="title">{html.escape(status)}</ac:parameter>',
                f'<ac:parameter ac:name="colour">{color}</ac:parameter>',
                f'</ac:structured-macro>',
            ]

        if status in ("PTPNEL", "NOUV"):
            warn = cat.get("ptpnel_warning") or cat.get("nouv_warning")
            since = cat.get("ptpnel_since") or cat.get("nouv_since")
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
                    f'(PTPNEL depuis {since_cell})'
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
        empty_message: str = "Aucune alerte.",
    ) -> str:
        """Génère la structure XHTML standard d'un tableau d'alertes Confluence (7 colonnes)."""
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
            '<th>Statut</th>',
            '<th>Catégorie d\'alerte</th>',
            '<th>Occurrences</th>',
            '<th>Date de la dernière apparition de l\'alerte dans Mattermost</th>',
            '<th>Porteur</th>',
            '<th>Échéance</th>',
            '<th>Actions décidées (Point de suivi)</th>',
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
    ) -> str:
        """
        Génère le format de stockage Confluence (XHTML Confluence) pour la page.
        Comprend une bannière de synthèse avec la date de dernière exécution,
        le lien vers le dernier artefact GitLab, des macros de statut interactives,
        des ancres pour chaque catégorie, le tableau principal et le tableau des alertes de bruit.
        """
        parts: list[str] = []

        # Séparation des alertes nominales et des alertes de bruit
        main_categories = [cat for cat in tracked_categories if cat.get("status") != "BRUIT"]
        bruit_categories = [cat for cat in tracked_categories if cat.get("status") == "BRUIT"]

        # Construction des accès rapides groupés
        quick_links: list[str] = []
        if artifact_url:
            browse_part = f' (<a href="{html.escape(artifact_browse_url)}">parcourir 📂</a>)' if artifact_browse_url else ""
            quick_links.append(f'📊 <a href="{html.escape(artifact_url)}">Dernier rapport visuel HTML ↗</a>{browse_part}')
        if archive_page_url:
            count_str = f" ({archived_count})" if archived_count > 0 else ""
            quick_links.append(f'📦 <a href="{html.escape(archive_page_url)}">Archive &gt; 1 mois{count_str} ↗</a>')
        if stats_page_url:
            quick_links.append(f'📈 <a href="{html.escape(stats_page_url)}">Statistiques hebdo ↗</a>')

        quick_links_html = (
            f'<p style="margin: 6px 0 2px 0;"><strong>Accès rapides :</strong> '
            f'{" &#160;&#8226;&#160; ".join(quick_links)}</p>'
            if quick_links
            else ""
        )

        # Ligne de date de dernière exécution
        execution_line = f'Dernière exécution : <strong>{sync_date_str}</strong>.<br/>'

        # 1. Macro Panneau d'information Confluence (Synthèse & Liens)
        parts.append(
            f'<ac:structured-macro ac:name="info">'
            f'<ac:rich-text-body>'
            f'<p><strong>📋 Suivi hebdomadaire des alertes Mattermost et plan d\'action d\'équipe</strong></p>'
            f'<p>'
            f'{execution_line}'
            f'Catégories actives cette semaine : <strong>{stats.get("ACTIVE_THIS_WEEK", 0)}</strong> &#8226; Total suivi : <strong>{stats.get("TOTAL", 0)}</strong><br/>'
            f'🔹 <strong>{stats.get("NOUVELLE", 0)}</strong> Nouvelles &#160;|&#160; '
            f'⚪ <strong>{stats.get("PTPNEL", stats.get("NOUV", 0))}</strong> PTPNEL &#160;|&#160; '
            f'🔸 <strong>{stats.get("EN COURS", 0)}</strong> En cours &#160;|&#160; '
            f'🔺 <strong>{stats.get("RÉCURRENTE", 0)}</strong> Récurrentes &#160;|&#160; '
            f'✅ <strong>{stats.get("RÉSOLUE", 0)}</strong> Résolues &#160;|&#160; '
            f'🟤 <strong>{stats.get("BRUIT", 0)}</strong> Bruit'
            f'</p>'
            f'{quick_links_html}'
            f'<ac:structured-macro ac:name="expand">'
            f'<ac:parameter ac:name="title">💡 Guide des workflows et règles de qualification (cliquer pour dérouler)</ac:parameter>'
            f'<ac:rich-text-body>'
            f'<p><strong>📊 Schéma du cycle de vie des alertes :</strong></p>'
            f'<ac:structured-macro ac:name="code">'
            f'<ac:parameter ac:name="title">Workflow des statuts</ac:parameter>'
            f'<ac:plain-text-body><![CDATA['
            f'             ┌─────────────────── Détection initiale (Semaine S) ───────────────────┐\n'
            f'             │                                                                      │\n'
            f'             ▼                                                                      ▼\n'
            f'    [ 🔹 NOUVELLE ]                                                       [ 🔺 RÉCURRENTE ]\n'
            f'             │                                                                      ▲\n'
            f'   ┌─────────┴───────────────────────┐                                              │\n'
            f'   │ Aucune action prise             │ Action définie / Porteur                     │\n'
            f'   ▼                                 ▼                                              │\n'
            f'[ ⚪ PTPNEL ] ────────────► [ 🔸 EN COURS ] ──(Fix validé)──► [ ✅ RÉSOLUE ]        │\n'
            f'   │                                 │                              │               │\n'
            f'   │  Au bout de 4 sem.              │ (Positionné manuellement)    │ > 1 mois      │\n'
            f'   ├─► ⚠️ Avertissement (J-X)        ▼                              ▼               │\n'
            f'   │                           [ 🟤 BRUIT ] (Tableau dédié)   [ 📦 ARCHIVE ] ───────┘\n'
            f'   │  Plus de 1 mois                                                (Rechute si retour)\n'
            f'   ▼\n'
            f'[ 🗑️ Purge définitive ]\n'
            f']]></ac:plain-text-body>'
            f'</ac:structured-macro>'
            f'<p><strong>📋 Détail des étapes de qualification en réunion :</strong></p>'
            f'<ul>'
            f'<li><strong>1. Cycle nominal (Nouveau problème) :</strong>'
            f'<ul>'
            f'<li><ac:structured-macro ac:name="status"><ac:parameter ac:name="title">NOUVELLE</ac:parameter><ac:parameter ac:name="colour">Blue</ac:parameter></ac:structured-macro> : '
            f'Première détection. Qualifier l\'origine, consigner l\'action et désigner un <strong>Porteur</strong>.</li>'
            f'<li><ac:structured-macro ac:name="status"><ac:parameter ac:name="title">PTPNEL</ac:parameter><ac:parameter ac:name="colour">Grey</ac:parameter></ac:structured-macro> : '
            f'Alerte antérieure toujours en attente de prise en charge par l\'équipe (pas traitée, pas nouvelle, encore là). '
            f'<em>Avertissement affiché sous le statut à 4 semaines ; purge automatique au-delà de 1 mois.</em></li>'
            f'<li>➔ <em>Prise en charge :</em> Passer en <ac:structured-macro ac:name="status"><ac:parameter ac:name="title">EN COURS</ac:parameter><ac:parameter ac:name="colour">Yellow</ac:parameter></ac:structured-macro> dès qu\'un plan d\'action est engagé.</li>'
            f'<li>➔ <em>Résolution :</em> Passer en <ac:structured-macro ac:name="status"><ac:parameter ac:name="title">RÉSOLUE</ac:parameter><ac:parameter ac:name="colour">Green</ac:parameter></ac:structured-macro> une fois le correctif validé. '
            f'<em>Transfert automatique vers l\'archive après 1 mois sans réapparition.</em></li>'
            f'</ul>'
            f'</li>'
            f'<li><strong>2. Cycle de régression (Rechute post-résolution) :</strong>'
            f'<ul>'
            f'<li><ac:structured-macro ac:name="status"><ac:parameter ac:name="title">RÉCURRENTE</ac:parameter><ac:parameter ac:name="colour">Red</ac:parameter></ac:structured-macro> : '
            f'<em>Bascule automatique</em> si une alerte résolue/archivée se redéclenche. Traiter en priorité ➔ repasser en <ac:structured-macro ac:name="status"><ac:parameter ac:name="title">EN COURS</ac:parameter><ac:parameter ac:name="colour">Yellow</ac:parameter></ac:structured-macro>.</li>'
            f'</ul>'
            f'</li>'
            f'<li><strong>3. Cycle d\'observation (0 occurrence cette semaine) :</strong>'
            f'<ul>'
            f'<li>La fiche est conservée. Passer en <ac:structured-macro ac:name="status"><ac:parameter ac:name="title">RÉSOLUE</ac:parameter><ac:parameter ac:name="colour">Green</ac:parameter></ac:structured-macro> si le fix est confirmé, sinon maintenir en observation.</li>'
            f'</ul>'
            f'</li>'
            f'<li><strong>4. Alertes de bruit (incompressibles) :</strong>'
            f'<ul>'
            f'<li><span style="background-color: #795548; color: #ffffff; padding: 2px 8px; border-radius: 3px; font-weight: bold; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; display: inline-block;">BRUIT</span> : '
            f'Positionné manuellement par l\'équipe. Concerne les alertes récurrentes connues dont l\'origine est identifiée mais qui ne peuvent pas être désactivées (épine dans le pied). '
            f'<em>Ces alertes sont automatiquement isolées dans le tableau secondaire situé sous le tableau principal.</em></li>'
            f'</ul>'
            f'</li>'
            f'<li><strong>5. Fausse alerte / maintenance :</strong>'
            f'<ul>'
            f'<li>Passer directement en <ac:structured-macro ac:name="status"><ac:parameter ac:name="title">RÉSOLUE</ac:parameter><ac:parameter ac:name="colour">Green</ac:parameter></ac:structured-macro> en précisant le motif dans la colonne actions (ex: <em>Faux positif</em>).</li>'
            f'</ul>'
            f'</li>'
            f'</ul>'
            f'</ac:rich-text-body>'
            f'</ac:structured-macro>'
            f'</ac:rich-text-body>'
            f'</ac:structured-macro>'
        )

        # 2. Encart To-Do Point de Suivi
        parts.append(
            '<ac:structured-macro ac:name="panel">'
            '<ac:parameter ac:name="title">📋 To-Do Point de Suivi</ac:parameter>'
            '<ac:rich-text-body>'
            '<ul style="margin: 0; padding-left: 20px; line-height: 1.6;">'
            '<li><strong>1. Traiter les 🔺 Récurrentes :</strong> Comprendre la rechute ➔ Nommer un porteur ➔ <ac:structured-macro ac:name="status"><ac:parameter ac:name="title">EN COURS</ac:parameter><ac:parameter ac:name="colour">Yellow</ac:parameter></ac:structured-macro></li>'
            '<li><strong>2. Qualifier les 🔹 Nouvelles :</strong> Définir l\'action + porteur ➔ <ac:structured-macro ac:name="status"><ac:parameter ac:name="title">EN COURS</ac:parameter><ac:parameter ac:name="colour">Yellow</ac:parameter></ac:structured-macro> <em>(ou <span style="background-color: #795548; color: #ffffff; padding: 2px 8px; border-radius: 3px; font-weight: bold; font-size: 11px;">BRUIT</span> si incompressible)</em></li>'
            '<li><strong>3. Arbitrer les ⚪ PTPNEL ⚠️ (J-X) :</strong> Prendre en charge ➔ <ac:structured-macro ac:name="status"><ac:parameter ac:name="title">EN COURS</ac:parameter><ac:parameter ac:name="colour">Yellow</ac:parameter></ac:structured-macro> <em>(sinon <span style="background-color: #795548; color: #ffffff; padding: 2px 8px; border-radius: 3px; font-weight: bold; font-size: 11px;">BRUIT</span> ou purge auto à 1 mois)</em></li>'
            '<li><strong>4. Clôturer les 🔸 En cours terminées :</strong> Fix validé en prod ➔ <ac:structured-macro ac:name="status"><ac:parameter ac:name="title">RÉSOLUE</ac:parameter><ac:parameter ac:name="colour">Green</ac:parameter></ac:structured-macro> <em>(archivage auto après 1 mois)</em></li>'
            '</ul>'
            '</ac:rich-text-body>'
            '</ac:structured-macro>'
        )

        # 3. Encart Palette de statuts (Copier / Coller rapide en édition)
        parts.append(
            '<ac:structured-macro ac:name="panel">'
            '<ac:parameter ac:name="title">📋 Palette de statuts (Copier / Coller rapide)</ac:parameter>'
            '<ac:rich-text-body>'
            '<p style="margin: 0 0 4px 0;"><em>💡 Sélectionnez une pastille (<code>Ctrl+C</code>) et collez-la (<code>Ctrl+V</code>) dans la colonne <strong>Statut</strong> :</em></p>'
            '<p style="margin: 0;">'
            '<ac:structured-macro ac:name="status"><ac:parameter ac:name="title">NOUVELLE</ac:parameter><ac:parameter ac:name="colour">Blue</ac:parameter></ac:structured-macro> &#160;'
            '<ac:structured-macro ac:name="status"><ac:parameter ac:name="title">PTPNEL</ac:parameter><ac:parameter ac:name="colour">Grey</ac:parameter></ac:structured-macro> &#160;'
            '<ac:structured-macro ac:name="status"><ac:parameter ac:name="title">EN COURS</ac:parameter><ac:parameter ac:name="colour">Yellow</ac:parameter></ac:structured-macro> &#160;'
            '<ac:structured-macro ac:name="status"><ac:parameter ac:name="title">RÉSOLUE</ac:parameter><ac:parameter ac:name="colour">Green</ac:parameter></ac:structured-macro> &#160;'
            '<ac:structured-macro ac:name="status"><ac:parameter ac:name="title">RÉCURRENTE</ac:parameter><ac:parameter ac:name="colour">Red</ac:parameter></ac:structured-macro> &#160;'
            '<span style="background-color: #795548; color: #ffffff; padding: 2px 8px; border-radius: 3px; font-weight: bold; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; display: inline-block;">BRUIT</span>'
            '</p>'
            '</ac:rich-text-body>'
            '</ac:structured-macro>'
        )

        # 3. Tableau principal des alertes
        parts.append(
            cls._build_confluence_table_html(
                main_categories,
                empty_message="Aucune alerte active cette semaine.",
            )
        )

        # 4. Tableau secondaire des alertes de bruit (remplace l'historique des alertes sans action supprimées)
        bruit_count = len(bruit_categories)
        parts.append(
            f'<p style="margin: 24px 0 6px 0;"><strong>🟤 Tableau des alertes de bruit ({bruit_count}) :</strong></p>'
            f'<p style="margin: 0 0 8px 0;"><em>Alertes récurrentes connues qui ne peuvent pas être désactivées (épine dans le pied). '
            f'Statut positionnable manuellement dans Confluence pour isoler ce bruit du flux nominal.</em></p>'
        )
        parts.append(
            cls._build_confluence_table_html(
                bruit_categories,
                empty_message="Aucune alerte qualifiée comme Bruit pour le moment.",
            )
        )

        return "".join(parts)

    @classmethod
    def synchronize_confluence(
        cls,
        confluence_config: dict[str, Any],
        categories: list[dict[str, Any]],
        alerts: list[dict[str, Any]],
        current_date_str: str,
        app_tz: tzinfo | None,
        gitlab_artifact_url: str | None = None,
        gitlab_artifact_browse_url: str | None = None,
        client_class: type | None = None,
        render_html_callback: Any = None,
    ) -> tuple[str | None, dict[str, int]]:
        """
        Orchestre l'ensemble du cycle de vie et de synchronisation des pages Confluence :
        1. Lecture de la page principale et extraction de l'historique
        2. Lecture de la page d'archive (alertes résolues > 3 mois)
        3. Réconciliation avec détection automatique des récurrences
        4. Séparation des alertes résolues > 3 mois vers l'archive
        5. Filtrage des alertes PTPNEL (> 1 mois) et injection des avertissements (>= 4 sem.)
        6. Mise à jour de la page d'archive Confluence
        7. Mise à jour de la page d'historique des statistiques Confluence
        8. Construction et mise à jour de la page principale de suivi Confluence
        """
        confluence_url = confluence_config.get("url") or ""
        confluence_token = confluence_config.get("token")
        confluence_page_id = confluence_config.get("page_id")
        confluence_archive_page_id = confluence_config.get("archive_page_id") or "123456780"
        confluence_stats_page_id = confluence_config.get("stats_page_id") or "123456781"

        if confluence_config.get("disabled"):
            logger.info(
                "[CONFLUENCE] Synchronisation Confluence désactivée (CONFLUENCE_DISABLED=true dans .env)."
            )
            return None, {}

        if not confluence_token or not confluence_page_id:
            logger.warning(
                "[CONFLUENCE] Mode --suivi-confluence activé mais CONFLUENCE_TOKEN ou "
                "CONFLUENCE_PAGE_ID manquant dans .env. Synchronisation ignorée."
            )
            return None, {}

        confluence_page_url: str | None = None
        tracking_stats: dict[str, int] = {}

        try:
            if client_class is None:
                from clients.confluence_client import ConfluenceClient
                client_class = ConfluenceClient

            logger.info("[CONFLUENCE] Synchronisation avec le registre Confluence...")
            with client_class(
                url=confluence_url,
                token=confluence_token,
                page_id=confluence_page_id,
            ) as conf_client:
                # 1. Page principale de suivi
                page_data = conf_client.get_page()
                confluence_page_url = conf_client.build_page_url(page_data)
                storage_html = page_data.get("body", {}).get("storage", {}).get("value", "")
                version_num = page_data.get("version", {}).get("number", 1)
                page_title = page_data.get("title", "Analyse des alertes")
                space_key = page_data.get("space", {}).get("key", "ALERTS")

                existing_registry = cls.parse_confluence_storage(storage_html)

                # 2. Page d'archive (alertes résolues depuis plus de 1 mois)
                archive_page_data = None
                archive_registry: dict[str, dict[str, Any]] = {}
                archive_page_url: str | None = None
                archive_page_title = "Archive des décisions de suivi des alertes résolues depuis plus de 1 mois"
                archive_space_key = "ALERTS"
                archive_version_num = 1

                if confluence_archive_page_id:
                    try:
                        archive_page_data = conf_client.get_page(page_id=confluence_archive_page_id)
                        archive_page_url = conf_client.build_page_url(archive_page_data)
                        archive_storage_html = (
                            archive_page_data.get("body", {}).get("storage", {}).get("value", "")
                        )
                        archive_version_num = archive_page_data.get("version", {}).get("number", 1)
                        archive_page_title = archive_page_data.get("title", archive_page_title)
                        archive_space_key = archive_page_data.get("space", {}).get("key", archive_space_key)
                        archive_registry = cls.parse_confluence_archive_storage(archive_storage_html)
                    except Exception as err_archive:
                        logger.warning(
                            "[CONFLUENCE] Impossible de lire la page d'archive %s : %s",
                            confluence_archive_page_id,
                            err_archive,
                        )

                # Fusionner l'archive dans l'existant pour détecter la réapparition éventuelle d'une alerte archivée
                merged_registry = dict(archive_registry)
                merged_registry.update(existing_registry)

                tracked_categories, _ = cls.reconcile(
                    categories=categories,
                    existing_registry=merged_registry,
                    current_date_str=current_date_str,
                )

                # 3. Séparation : Déplacer les catégories RÉSOLUES dont last_seen > 1 mois vers l'archive
                ref_dt = datetime.now(tz=app_tz)
                active_categories, newly_archived = cls.separate_archived_categories(
                    tracked_categories=tracked_categories,
                    ref_dt=ref_dt,
                    months=1,
                )

                # 4. Traitement des alertes PTPNEL : suppression si > 1 mois, warning si >= 4 semaines
                active_categories, deleted_ptpnel = cls.filter_and_tag_ptpnel_categories(
                    tracked_categories=active_categories,
                    ref_dt=ref_dt,
                )

                tracking_stats = cls.calculate_stats(
                    active_categories,
                    deleted_ptpnel_count=len(deleted_ptpnel),
                )

                # 5. Mettre à jour le registre d'archive
                for item in newly_archived:
                    archive_registry[item["slug"]] = item

                active_slugs = {c["slug"] for c in active_categories}
                for slug in list(archive_registry.keys()):
                    if slug in active_slugs:
                        del archive_registry[slug]

                # 6. Mise à jour de la page d'archive Confluence si configurée
                if confluence_archive_page_id and (newly_archived or archive_page_data):
                    try:
                        archive_list = list(archive_registry.values())
                        archive_storage = cls.build_confluence_archive_storage_html(
                            archived_categories=archive_list,
                            sync_date_str=current_date_str,
                            main_page_url=confluence_page_url,
                        )
                        conf_client.update_page(
                            page_id=confluence_archive_page_id,
                            title=archive_page_title,
                            space_key=archive_space_key,
                            storage_html=archive_storage,
                            next_version=archive_version_num + 1,
                        )
                        logger.info(
                            "[CONFLUENCE] Page d'archive Confluence synchronisée avec succès (%d catégories archivées).",
                            len(archive_list),
                        )
                    except Exception as err_update_arch:
                        logger.warning(
                            "[CONFLUENCE] Erreur lors de la mise à jour de la page d'archive Confluence (%s).",
                            err_update_arch,
                        )

                # 7. Mise à jour de la page de statistiques Confluence si configurée
                stats_page_url: str | None = None
                if confluence_stats_page_id:
                    try:
                        stats_page_data = conf_client.get_page(page_id=confluence_stats_page_id)
                        stats_page_url = conf_client.build_page_url(stats_page_data)
                        stats_storage_html = (
                            stats_page_data.get("body", {}).get("storage", {}).get("value", "")
                        )
                        stats_version_num = stats_page_data.get("version", {}).get("number", 1)
                        stats_page_title = stats_page_data.get("title", "Statistiques du suivi des alertes")
                        stats_space_key = stats_page_data.get("space", {}).get("key", "ALERTS")

                        # Attachement du rapport HTML d'exécution sur la page de statistiques
                        report_filename: str | None = None
                        if render_html_callback:
                            try:
                                report_html_content = render_html_callback(confluence_page_url, tracking_stats)
                                ref_dt_slug = ref_dt.strftime("%Y%m%d_%H%M%S")
                                report_filename = f"rapport_alertes_{ref_dt_slug}.html"
                                conf_client.attach_file(
                                    page_id=confluence_stats_page_id,
                                    filename=report_filename,
                                    content=report_html_content,
                                    comment=f"Rapport d'alerting généré le {current_date_str}",
                                )
                            except Exception as err_attach:
                                logger.warning(
                                    "[CONFLUENCE] Erreur lors de l'attachement du rapport HTML sur la page stats (%s).",
                                    err_attach,
                                )

                        updated_stats_storage = cls.append_weekly_stats_row(
                            storage_html=stats_storage_html,
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
                            "[CONFLUENCE] Page de statistiques Confluence incrémentée avec succès (%s).",
                            current_date_str,
                        )
                    except Exception as err_stats:
                        logger.warning(
                            "[CONFLUENCE] Erreur lors de la mise à jour de la page de statistiques Confluence (%s).",
                            err_stats,
                        )

                # 8. Construction et mise à jour de la page active Confluence
                new_storage = cls.build_confluence_storage_html(
                    tracked_categories=active_categories,
                    stats=tracking_stats,
                    sync_date_str=current_date_str,
                    artifact_url=gitlab_artifact_url,
                    artifact_browse_url=gitlab_artifact_browse_url,
                    archive_page_url=archive_page_url,
                    archived_count=len(archive_registry),
                    stats_page_url=stats_page_url,
                )

                conf_client.update_page(
                    page_id=confluence_page_id,
                    title=page_title,
                    space_key=space_key,
                    storage_html=new_storage,
                    next_version=version_num + 1,
                )
                logger.info(
                    "[CONFLUENCE] Registre Confluence synchronisé avec succès (%d catégories actives, %d archivées).",
                    len(active_categories),
                    len(archive_registry),
                )
        except Exception as e:
            logger.warning(
                "[CONFLUENCE] Erreur lors de la synchronisation Confluence (%s). Poursuite de la génération sans bloquer.",
                e,
            )

        return confluence_page_url, tracking_stats
