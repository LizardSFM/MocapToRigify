"""Cooperative 'Lizzy Tools' parent panel — shared by all Lizzy addons.

Keep this file identical in every Lizzy addon. The first addon to
register creates the parent panel; the last one to unregister removes
it. Child panels attach via:

    bl_parent_id = "LIZZY_TOOLS_PT_main"
    bl_category = "Lizzy Tools"

A Lizzy addon marks itself with ``LIZZY_TOOL = True`` in its __init__.py.
"""
import bpy
import sys

PARENT_IDNAME = "LIZZY_TOOLS_PT_main"
PARENT_LABEL = "Lizzy Tools"
PARENT_CATEGORY = "Lizzy Tools"

_ADDON_NAME = __package__.split(".")[0] if __package__ else __name__


class LizzyToolsPanel(bpy.types.Panel):
    """Umbrella panel aggregating all enabled Lizzy addons."""
    bl_label = PARENT_LABEL
    bl_idname = PARENT_IDNAME
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = PARENT_CATEGORY

    @classmethod
    def poll(cls, context):
        return _any_tool_enabled(exclude=None)

    def draw(self, context):
        pass  # sub-panels provide the content


def _lizzy_enabled_names():
    """Module names of *enabled* addons marked with ``LIZZY_TOOL``.

    Reads the marker from the real imported module in ``sys.modules``.
    (``addon_utils.modules()`` can't be used: Blender 5.x returns
    metadata-only "fake modules" that never expose custom attributes.)
    """
    names = []
    for addon in bpy.context.preferences.addons:
        mod = sys.modules.get(addon.module)
        if mod is not None and getattr(mod, "LIZZY_TOOL", False):
            names.append(addon.module)
    return names


def _any_tool_enabled(exclude=None):
    for name in _lizzy_enabled_names():
        if name == exclude:
            continue
        return True
    return False


def register_hub():
    """Create the parent panel if no other Lizzy addon has done so."""
    if not hasattr(bpy.types, PARENT_IDNAME):
        bpy.utils.register_class(LizzyToolsPanel)


def unregister_hub():
    """Remove the parent panel only if no other Lizzy addon stays enabled."""
    if _any_tool_enabled(exclude=_ADDON_NAME):
        return
    cls = getattr(bpy.types, PARENT_IDNAME, None)
    if cls is not None:
        bpy.utils.unregister_class(cls)
