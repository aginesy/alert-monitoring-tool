from __future__ import annotations

import logging
import re
import time
from datetime import datetime, tzinfo
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

RE_DESCRIPTION = re.compile(r"\*\*Description\s*:\*\*\s*([^\n]+)")
RE_TITRE_LINE = re.compile(r"^titre\s*:", re.IGNORECASE)


class MattermostClient:
    """
    Client de connexion et d'extraction de données depuis Mattermost pour le projet d'alerting.
    Optimisé pour les performances réseau (Session HTTP Keep-Alive) et la résilience (Retry/Backoff).
    """

    def __init__(
        self,
        url: str,
        token: str,
        channel_id: str,
        hours: int | None = None,
        excluded_titles: list[str] | None = None,
        team: str | None = None,
        tz: tzinfo | None = None,
    ) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.channel_id = channel_id
        self.hours = hours if (hours is not None and hours > 0) else 24
        self.team = team.strip("/") if team else None
        self.tz = tz

        # Pré-normalisation des règles d'exclusion pour des comparaisons rapides
        self.excluded_titles = [
            item.strip().lower() for item in (excluded_titles or []) if item.strip()
        ]

        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        # Configuration de la session HTTP avec réutilisation de connexion et retries
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def __enter__(self) -> MattermostClient:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def close(self) -> None:
        """Ferme la session HTTP sous-jacente."""
        self.session.close()

    def get_post_permalink(self, post_id: str) -> str:
        """
        Construit le permalien direct vers un post Mattermost.
        Utilise le nom de team si configuré, ou la redirection universelle /parcours/pl/<post_id>.
        """
        if self.team:
            return f"{self.url}/{self.team}/pl/{post_id}"
        return f"{self.url}/parcours/pl/{post_id}"

    def _is_excluded(self, message: str, attachment_titles: list[str]) -> bool:
        """
        Détermine si une alerte doit être exclue en fonction de la liste `excluded_titles`.
        Vérifie les titres des pièces jointes ainsi que les lignes de titre du message.
        """
        if not self.excluded_titles:
            return False

        norm_att_titles = [t.strip().lower() for t in attachment_titles if t.strip()]

        for norm_excluded in self.excluded_titles:
            # Vérification dans les titres des pièces jointes (attachments)
            for norm_title in norm_att_titles:
                if norm_excluded in norm_title:
                    return True

            # Vérification dans le corps du message (ex: "Titre : Batche(s) OK")
            for line in message.splitlines():
                norm_line = line.strip().lower()
                if RE_TITRE_LINE.match(norm_line) and norm_excluded in norm_line:
                    return True
                if norm_line.startswith(norm_excluded):
                    return True

        return False

    def fetch_messages(self) -> list[dict[str, Any]]:
        """
        Récupère TOUS les messages des dernières heures configurées pour le canal configuré en utilisant la pagination.
        Prend en charge l'extraction des informations contenues dans les pièces jointes (props.attachments).
        Retourne une liste de dictionnaires formatés avec la date et le message.
        """
        if not self.channel_id:
            raise RuntimeError("L'ID du canal Mattermost n'est pas configuré.")

        # Calculer le timestamp d'il y a self.hours heures en millisecondes
        since_time = int((time.time() - self.hours * 3600) * 1000)

        url = f"{self.url}/api/v4/channels/{self.channel_id}/posts"

        all_posts: dict[str, dict[str, Any]] = {}
        all_order: list[str] = []
        page = 0
        per_page = 100

        logger.debug("[MATTERMOST] Récupération de tous les messages de Mattermost depuis %s", since_time)

        try:
            while True:
                logger.debug("[MATTERMOST] Chargement des posts - Page %d (per_page=%d)", page, per_page)
                params = {
                    "page": page,
                    "per_page": per_page,
                }
                r = self.session.get(
                    url,
                    headers=self.headers,
                    params=params,
                    timeout=20,
                )
                if r.status_code != 200:
                    try:
                        err_json = r.json()
                        err_msg = err_json.get("message", r.text)
                    except Exception:
                        err_msg = r.text
                    raise RuntimeError(f"Erreur API Mattermost (HTTP {r.status_code}) : {err_msg}")

                data = r.json()
                posts = data.get("posts", {})
                order = data.get("order", [])

                if not order:
                    logger.debug("[MATTERMOST] Aucun post supplémentaire trouvé à la page %d.", page)
                    break

                logger.debug("[MATTERMOST] Page %d : %d posts reçus", page, len(order))

                reached_end = False
                for post_id in order:
                    post = posts.get(post_id)
                    if not post:
                        continue

                    create_at = post.get("create_at", 0)
                    if create_at >= since_time:
                        if post_id not in all_posts:
                            all_posts[post_id] = post
                            all_order.append(post_id)
                    else:
                        reached_end = True

                if reached_end:
                    logger.info("[MATTERMOST] Limite des %d dernières heures atteinte.", self.hours)
                    break

                if len(order) < per_page:
                    logger.debug("[MATTERMOST] Fin des messages atteinte (dernière page incomplète).")
                    break

                page += 1

            formatted_messages: list[dict[str, Any]] = []
            excluded_count = 0
            for post_id in all_order:
                post = all_posts.get(post_id)
                if not post:
                    continue

                message_text = post.get("message", "").strip()

                # Extraire les pièces jointes (attachments) dans les props du post
                props = post.get("props", {}) or {}
                attachments = props.get("attachments", []) or []

                attachment_parts = []
                attachment_titles = []
                attachment_items = []
                for attachment in attachments:
                    title = attachment.get("title", "").strip()
                    text = attachment.get("text", "").strip()

                    # Extraction de la description spécifique de cet attachement
                    desc = attachment.get("description", "").strip() if attachment.get("description") else ""
                    if not desc:
                        fields = attachment.get("fields") or []
                        for f in fields:
                            if isinstance(f, dict) and "description" in (f.get("title") or "").lower():
                                desc = (f.get("value") or "").strip()
                                break
                    if not desc and text:
                        m_desc = RE_DESCRIPTION.search(text)
                        if m_desc:
                            desc = m_desc.group(1).strip()
                    if not desc and text:
                        # Limiter à la première ligne pour éviter des intitulés géants (ex: tracebacks)
                        first_line = text.strip().splitlines()[0].strip()
                        desc = first_line[:120]

                    if title:
                        attachment_titles.append(title)

                    attachment_items.append({
                        "title": title,
                        "text": text,
                        "description": desc,
                    })

                    if title and text:
                        attachment_parts.append(f"Titre : {title}\n{text}")
                    elif text:
                        attachment_parts.append(text)
                    elif title:
                        attachment_parts.append(f"Titre : {title}")

                if attachment_parts:
                    attachments_text = "\n\n".join(attachment_parts)
                    if message_text:
                        message_text = f"{message_text}\n\n{attachments_text}"
                    else:
                        message_text = attachments_text

                # Ignorer les messages vides
                if not message_text.strip():
                    continue

                # Filtrer les alertes exclues selon leurs titres
                if self._is_excluded(message_text, attachment_titles):
                    matched_info = ", ".join(attachment_titles) if attachment_titles else message_text.splitlines()[0]
                    logger.info("[MATTERMOST] Alerte ignorée (titre exclu) : %s", matched_info)
                    excluded_count += 1
                    continue

                # Formatage de la date du post dans le fuseau configuré
                create_at = post.get("create_at", 0)
                dt = datetime.fromtimestamp(create_at / 1000.0, tz=self.tz)
                created_at_str = dt.strftime("%d/%m/%Y %H:%M:%S")

                permalink = self.get_post_permalink(post_id)

                formatted_messages.append({
                    "id": post_id,
                    "message": message_text,
                    "created_at": created_at_str,
                    "timestamp": create_at,
                    "titles": attachment_titles,
                    "attachments": attachment_items,
                    "permalink": permalink,
                })

            if excluded_count > 0:
                logger.info(
                    "[MATTERMOST] %d alerte(s) ignorée(s) selon les règles d'exclusion de titre.",
                    excluded_count,
                )

            logger.info("[MATTERMOST] %d message(s) d'alerte extrait(s) des dernières %dh.", len(formatted_messages), self.hours)
            return formatted_messages

        except requests.RequestException as e:
            raise RuntimeError(f"Erreur réseau lors de la récupération des messages : {e}")
