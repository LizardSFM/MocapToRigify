# UI for the universal retargeter: pick two rigs, analyze, review the
# mapping rows (bone-search fields, nothing typed by hand), bind.

import bpy

from . import matching


class MOCAPTORIGIFY_PT_universal_base:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MocapToRigify"


class MOCAPTORIGIFY_PT_universal(MOCAPTORIGIFY_PT_universal_base, bpy.types.Panel):
    bl_label = "Universal Retarget"
    bl_idname = "MOCAPTORIGIFY_PT_universal"

    def draw(self, context):
        layout = self.layout
        props = context.scene.universal_retarget

        layout.prop(props, "source", icon="ARMATURE_DATA")
        layout.prop(props, "target", icon="ARMATURE_DATA")

        analyze = layout.column()
        analyze.enabled = (
            props.source is not None
            and props.target is not None
            and props.source != props.target
        )
        analyze.scale_y = 1.2
        analyze.operator("universal_retarget.analyze", icon="VIEWZOOM")

        if props.status:
            layout.label(text=props.status, icon="INFO")

        if len(props.rows):
            mapping_panel = layout.column()
            mapping_panel.label(text=f"{len(props.rows)} mapping rows", icon="GROUP_BONE")
            mapping_panel.label(text="Edit below, then bind", icon="INFO")

        options = layout.box()
        options.label(text="Options", icon="PREFERENCES")
        options.prop(props, "mode")
        options.prop(props, "auto_hip_scale")
        scale = options.column()
        scale.enabled = not props.auto_hip_scale
        scale.prop(props, "hip_scale")

        bind = layout.column()
        bind.scale_y = 1.4
        missing = [
            slot for slot in matching.REQUIRED_SLOTS
            if not any(r.slot == slot and r.enabled and r.target_bone and r.source_bone
                       for r in props.rows)
        ]
        bind.enabled = len(props.rows) > 0 and not missing
        bind.operator("universal_retarget.bind", icon="LINKED")
        if missing:
            layout.label(text=f"Unresolved: {', '.join(missing)}", icon="ERROR")

        remove = layout.column()
        remove.operator("universal_retarget.remove", icon="TRASH")


class MOCAPTORIGIFY_PT_universal_mapping(MOCAPTORIGIFY_PT_universal_base, bpy.types.Panel):
    bl_label = "Universal Mapping"
    bl_idname = "MOCAPTORIGIFY_PT_universal_mapping"
    bl_parent_id = "MOCAPTORIGIFY_PT_universal"

    def draw(self, context):
        layout = self.layout
        props = context.scene.universal_retarget

        source_data = props.source.data if props.source is not None else None
        target_data = props.target.data if props.target is not None else None

        torso = ("hips", "spine", "chest", "upper_chest", "neck", "head")
        groups = (
            ("Torso", lambda r: r.slot in torso or r.slot == ""),
            ("Arms", lambda r: "arm" in r.slot or "shoulder" in r.slot or "hand" in r.slot),
            ("Legs", lambda r: "thigh" in r.slot or "shin" in r.slot or "foot" in r.slot),
        )

        for title, predicate in groups:
            items = [r for r in props.rows if predicate(r)]
            if not items:
                continue
            box = layout.box()
            box.label(text=title, icon="BONE_DATA")
            for item in items:
                row = box.row(align=True)
                incomplete = item.required and not (item.source_bone and item.target_bone)
                row.alert = incomplete
                row.prop(item, "enabled", text="")
                if source_data is not None:
                    row.prop_search(item, "source_bone", source_data, "bones", text="")
                else:
                    row.prop(item, "source_bone", text="")
                if target_data is not None:
                    row.prop_search(item, "target_bone", target_data, "bones", text="")
                else:
                    row.prop(item, "target_bone", text="")
                if incomplete:
                    row.label(text="", icon="ERROR")
                elif item.conf_target <= 1 or item.conf_source <= 1:
                    row.label(text="", icon="MODIFIER")
