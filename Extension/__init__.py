# SPDX-License-Identifier: GPL-3.0-or-later
"""H-Style RBD Nodes: H-Style RBD nodes (fracture, constraints, Bullet solver), baked to the timeline, exported to game engines."""
from . import ui


def register():
    ui.register()


def unregister():
    ui.unregister()
