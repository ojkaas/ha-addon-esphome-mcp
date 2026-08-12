"""Auto-discover the ESPHome Device Builder dashboard URL.

The dashboard is served ingress-only on a Supervisor-assigned port that is
specific to each installation (and changes on reinstall), so it can't be a
fixed default. When ``dashboard_url`` is left blank, ``run.sh`` runs this
module to resolve the current port from the Supervisor API and prints
``http://127.0.0.1:<ingress_port>`` (exit 0), or nothing (exit 1) if it can't
be found — in which case ``run.sh`` falls back to the conventional ``:6052``.

Requires the add-on to have ``hassio_api: true`` so ``SUPERVISOR_TOKEN`` is set
and the Supervisor API is reachable at ``http://supervisor``.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

SUPERVISOR = "http://supervisor"


def _pick_dashboard_slug(addons: list[dict]) -> str | None:
    """Pick the ESPHome dashboard add-on from a Supervisor add-on list.

    The dashboard add-on's slug ends in ``_esphome`` (e.g. ``15ef4d2f_esphome``).
    This add-on's own slug ends in ``_esphome-mcp``, so it never matches self.
    """
    for addon in addons:
        slug = addon.get("slug", "")
        if slug.endswith("_esphome"):
            return slug
    return None


def _get(path: str) -> dict:
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    req = urllib.request.Request(
        SUPERVISOR + path, headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 (trusted host)
        return json.load(resp)


def resolve_dashboard_url() -> str | None:
    """Return ``http://127.0.0.1:<ingress_port>`` for the dashboard, or None."""
    addons = _get("/addons").get("data", {}).get("addons", [])
    slug = _pick_dashboard_slug(addons)
    if not slug:
        return None
    info = _get(f"/addons/{slug}/info").get("data", {})
    port = info.get("ingress_port")
    return f"http://127.0.0.1:{port}" if port else None


def main() -> int:
    try:
        url = resolve_dashboard_url()
    except Exception:  # noqa: BLE001 - any failure means "not discovered"
        return 1
    if not url:
        return 1
    print(url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
