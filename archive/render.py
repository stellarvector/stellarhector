from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

_env = Environment(loader=PackageLoader("archive", "templates"), autoescape=select_autoescape())


def render(template: str, **context: object) -> str:
    return _env.get_template(template).render(**context)


def fill_marker(path: Path, marker: str, html: str) -> str:
    """Replace the `marker` comment (such as <!--add-year-->) in the file at `path` with `html`, and return the file's
    previous content. The `html` must contain the marker again, so the next item can be added after it."""
    before = path.read_text()
    path.write_text(before.replace(marker, html))
    return before
