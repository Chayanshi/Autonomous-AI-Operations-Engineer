"""Human-facing descriptions of the targets under targets/."""

from __future__ import annotations


# Shown to people choosing a scenario. Symptoms only: the cause is for the agent to find.
TARGET_INFO: dict[str, dict[str, str]] = {
    "users_api": {
        "title": "Users API · always returns HTTP 500",
        "symptom": "Every request to GET /api/users fails with a server error (HTTP 500) instead of returning the user list.",
        "objective": "Investigate why the /api/users endpoint returns HTTP 500 and fix the root cause.",
    },
    "config_service": {
        "title": "Config service · crashes on startup",
        "symptom": "The service crashes as soon as it starts on a machine where the PAGE_SIZE setting has not been configured.",
        "objective": "The settings service crashes on startup when PAGE_SIZE is not configured. Investigate and fix the root cause.",
    },
    "pagination_api": {
        "title": "Products API · pages one item short",
        "symptom": "No error at all, but customers see only 2 products per page when they asked for 3. A silent logic bug.",
        "objective": "Customers asking for 3 products per page receive only 2. Investigate /api/products and fix the root cause.",
    },
    "profile_api": {
        "title": "Profile API · 500 for some users only",
        "symptom": "Profiles work for most users but return a server error for users who have no email address on file.",
        "objective": "GET /api/users/{id}/profile returns HTTP 500 for some users. Investigate and fix the root cause.",
    },
}


def describe_target(name: str) -> dict[str, str]:
    info = TARGET_INFO.get(name, {})
    return {
        "title": info.get("title", name),
        "symptom": info.get("symptom", "Custom target without a description."),
        "objective": info.get("objective", f"Investigate the failing tests in {name} and fix the root cause."),
    }
