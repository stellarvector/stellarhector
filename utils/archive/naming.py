import posixpath
import re


def normalize_name(name, fallback="unnamed"):
    # Keep only ASCII alphanumerics and dashes so names are safe as paths and URLs
    name = re.sub(r"\s+", "-", name)
    name = re.sub(r"[^A-Za-z0-9-]", "", name)
    name = re.sub(r"-{2,}", "-", name).strip("-")

    return name or fallback


def unique_name(name, taken, fallback="unnamed"):
    """The normalized name, numbered (-2, -3, …) when it is in taken already, and added to taken."""
    base = normalize_name(name, fallback=fallback)
    unique, i = base, 2
    while unique in taken:
        unique, i = f"{base}-{i}", i + 1

    taken.add(unique)
    return unique


def relative_link(from_page, to_page):
    """The link from one page to another, both given as paths relative to the same folder (e.g. a CTF's archive)."""
    # relpath resolves paths against the working directory; under a made-up root deep enough for every .. in them,
    # the links don't depend on it
    root = "/" + "/".join(["folder"] * (f"{from_page}/{to_page}".count("..") + 1))
    return posixpath.relpath(f"{root}/{to_page}", f"{root}/{posixpath.dirname(from_page)}")
