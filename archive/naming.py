"""Names for the archive's folders, pages and files that are safe to use as paths and URLs."""

import itertools
import posixpath
import re
from collections.abc import Callable


def normalize_name(name: str, fallback: str = "unnamed") -> str:
    """Keep only ASCII letters, digits and dashes, turning whitespace into dashes. Return `fallback` when nothing is
    left."""
    name = re.sub(r"\s+", "-", name)
    name = re.sub(r"[^A-Za-z0-9-]", "", name)
    name = re.sub(r"-{2,}", "-", name).strip("-")

    return name or fallback


def unique_name(name: str, taken: set[str], fallback: str = "unnamed") -> str:
    """Normalize `name`, number it (-2, -3, ...) if it is already in `taken`, and add the result to `taken`."""
    unique = first_free(normalize_name(name, fallback=fallback), lambda candidate: candidate in taken)
    taken.add(unique)
    return unique


def first_free(base: str, is_taken: Callable[[str], bool]) -> str:
    candidates = itertools.chain([base], (f"{base}-{i}" for i in itertools.count(2)))
    return next(candidate for candidate in candidates if not is_taken(candidate))


def file_name(name: str, fallback: str = "file") -> str:
    """Replace every character other than ASCII letters, digits, dots, dashes and underscores with an underscore, and
    drop leading dots, so the name cannot point into another folder."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", name).lstrip(".") or fallback


def relative_link(from_page: str, to_page: str) -> str:
    """Return the link from one page to another. Both paths are relative to the same folder, such as a CTF's
    archive."""
    # relpath resolves paths against the working directory. Placing both under a made-up root that is deep enough
    # for every ".." in them keeps the result independent of it.
    root = "/" + "/".join(["folder"] * (f"{from_page}/{to_page}".count("..") + 1))
    return posixpath.relpath(f"{root}/{to_page}", f"{root}/{posixpath.dirname(from_page)}")
