from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from jinja2 import Environment, FileSystemLoader


class TemplateRenderer:
    """
    Service responsible for rendering Jinja templates with environment caching.
    """

    def __init__(self) -> None:
        self._environments: dict[tuple[str, ...], Environment] = {}

    def render(
        self,
        template_file: str,
        context: Mapping[str, Any],
    ) -> str:
        """
        Renders a Jinja template with the provided context dictionary.
        """
        template_path = Path(template_file)

        if template_path.is_absolute():
            template_directories = [str(template_path.parent)]
            template_name = template_path.name
        else:
            root_directory = Path(__file__).resolve().parent.parent
            template_directories = [str(root_directory), str(root_directory / "templates")]
            template_name = template_file

        cache_key = tuple(template_directories)

        if cache_key not in self._environments:
            self._environments[cache_key] = Environment(
                loader=FileSystemLoader(template_directories),
                autoescape=True,
            )

        environment = self._environments[cache_key]
        template = environment.get_template(template_name)

        return template.render(**context)
