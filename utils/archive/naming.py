import re


def normalize_name(name, fallback="unnamed"):
    # Keep only ASCII alphanumerics and dashes so names are safe as paths and URLs
    name = re.sub(r"\s+", "-", name)
    name = re.sub(r"[^A-Za-z0-9-]", "", name)
    name = re.sub(r"-{2,}", "-", name).strip("-")

    return name or fallback
