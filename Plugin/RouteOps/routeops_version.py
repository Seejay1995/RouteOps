"""Single source of truth for the RouteOps version.

Imported by routeops_runtime (ZMQ handshake), ui_renderer (HEADER banner), and
RouteOps (empty-state HEADER). Keep this module import-free so it can be pulled in
anywhere without circular-import risk (RouteOps.py imports ui_renderer, so ui_renderer
must never import RouteOps).
"""

from __future__ import annotations

VERSION = "0.7.11.0"
# Short human banner form, e.g. "v0.7.11"
DISPLAY_VERSION = "v" + ".".join(VERSION.split(".")[:3])
