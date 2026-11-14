from __future__ import annotations

import logging
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class ConfluenceClient:
    """
    Client for connecting to and interacting with the Confluence Server / Data Center REST API.
    Handles retrieving and updating pages in XHTML storage format.
    """

    def __init__(
        self,
        url: str,
        token: str,
        page_id: str | None = None,
        timeout: int = 20,
    ) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.page_id = page_id
        self.timeout = timeout

        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

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

    def __enter__(self) -> ConfluenceClient:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def close(self) -> None:
        """Closes the underlying HTTP session."""
        self.session.close()

    def get_page(self, page_id: str | None = None) -> dict[str, Any]:
        """
        Retrieves details and content for a Confluence page (including body.storage, space, and version).
        """
        target_id = page_id or self.page_id
        if not target_id:
            raise ValueError("No Confluence page ID provided.")

        api_url = f"{self.url}/rest/api/content/{target_id}?expand=body.storage,version,space"
        response = self.session.get(api_url, headers=self.headers, timeout=self.timeout)

        if response.status_code != 200:
            logger.error(
                "[CONFLUENCE] Failed to retrieve page %s (HTTP %s): %s",
                target_id,
                response.status_code,
                response.text[:200],
            )
            response.raise_for_status()

        return response.json()

    def update_page(
        self,
        page_id: str | None,
        title: str,
        space_key: str,
        storage_html: str,
        next_version: int,
    ) -> dict[str, Any]:
        """
        Updates the content of a Confluence page.
        """
        target_id = page_id or self.page_id
        if not target_id:
            raise ValueError("No Confluence page ID provided for update.")

        api_url = f"{self.url}/rest/api/content/{target_id}"
        payload = {
            "id": target_id,
            "type": "page",
            "title": title,
            "space": {"key": space_key},
            "body": {
                "storage": {
                    "value": storage_html,
                    "representation": "storage",
                }
            },
            "version": {
                "number": next_version,
            },
        }

        response = self.session.put(
            api_url,
            headers=self.headers,
            json=payload,
            timeout=self.timeout,
        )

        if response.status_code != 200:
            logger.error(
                "[CONFLUENCE] Failed to update page %s (HTTP %s): %s",
                target_id,
                response.status_code,
                response.text[:300],
            )
            response.raise_for_status()

        logger.info(
            "[CONFLUENCE] Page %s updated successfully (new version %s).",
            target_id,
            next_version,
        )
        return response.json()

    def attach_file(
        self,
        page_id: str | None,
        filename: str,
        content: bytes | str,
        content_type: str = "text/html; charset=utf-8",
        comment: str | None = None,
    ) -> dict[str, Any]:
        """
        Attaches a file to a Confluence page via the multipart/form-data REST API.
        """
        target_id = page_id or self.page_id
        if not target_id:
            raise ValueError("No Confluence page ID provided for file attachment.")

        api_url = f"{self.url}/rest/api/content/{target_id}/child/attachment"

        headers = {
            "Authorization": f"Bearer {self.token}",
            "X-Atlassian-Token": "nocheck",
        }

        file_bytes = content.encode("utf-8") if isinstance(content, str) else content
        files = {
            "file": (filename, file_bytes, content_type),
        }
        data = {}
        if comment:
            data["comment"] = comment

        response = self.session.post(
            api_url,
            headers=headers,
            files=files,
            data=data,
            timeout=self.timeout,
        )

        if response.status_code not in (200, 201):
            logger.error(
                "[CONFLUENCE] Failed to attach file '%s' to page %s (HTTP %s): %s",
                filename,
                target_id,
                response.status_code,
                response.text[:300],
            )
            response.raise_for_status()

        logger.info(
            "[CONFLUENCE] File '%s' attached successfully to page %s.",
            filename,
            target_id,
        )
        return response.json()

    def build_page_url(self, page_data: dict[str, Any] | None = None) -> str:
        """
        Builds the direct web URL to a Confluence page.
        """
        if page_data:
            webui = page_data.get("_links", {}).get("webui", "")
            if webui:
                return f"{self.url}{webui}"
            space_key = page_data.get("space", {}).get("key")
            title = page_data.get("title", "").replace(" ", "+")
            page_id = page_data.get("id")
            if space_key and title:
                return f"{self.url}/spaces/{space_key}/pages/{page_id}/{title}"

        if self.page_id:
            return f"{self.url}/pages/viewpage.action?pageId={self.page_id}"
        return self.url
