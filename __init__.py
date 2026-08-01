bl_info = {
    "name": "MocapToRigify",
    "author": "Liz",
    "version": (1, 1, 0),
    "blender": (5, 0, 0),
    "location": "View3D > Sidebar > MocapToRigify",
    "description": "Non-destructive Mocap Fusion to Rigify retargeting",
    "category": "Animation",
}

import bpy

from .animation import constrains, rigify


GENERATED_ROLE_KEY = "mocap_to_rigify_role"
ROLE_COPY_ORG_MCH = "copy_org_mch"
ROLE_DRIVER_COPY = "driver_copy"


def selected_armatures(context):
    return [obj for obj in context.selected_objects if obj.type == "ARMATURE"]


def has_bone_collection(obj, collection_name):
    return (
        obj.type == "ARMATURE"
        and obj.data.collections_all.find(collection_name) != -1
    )


def is_original_rigify(obj):
    return (
        has_bone_collection(obj, "Torso (Tweak)")
        and obj.get(GENERATED_ROLE_KEY) != ROLE_DRIVER_COPY
        and not obj.name.endswith("-copy")
        and "-copy." not in obj.name
    )


def is_org_copy(obj):
    return (
        obj.get(GENERATED_ROLE_KEY) == ROLE_COPY_ORG_MCH
        or has_bone_collection(obj, "ORG-mocap")
    )


def is_driver_copy(obj):
    return (
        obj.get(GENERATED_ROLE_KEY) == ROLE_DRIVER_COPY
        or obj.name.endswith("-copy")
        or "-copy." in obj.name
    )


def is_mocap(obj):
    return obj.type == "ARMATURE" and "Hips" in obj.pose.bones


def selection_is_pair(armatures, first_test, second_test):
    if len(armatures) != 2:
        return False
    first, second = armatures
    return (
        first_test(first) and second_test(second)
    ) or (
        first_test(second) and second_test(first)
    )


def scene_pipeline_state(context):
    armatures = [obj for obj in context.scene.objects if obj.type == "ARMATURE"]
    has_org_copy = any(is_org_copy(obj) for obj in armatures)
    has_driver_copy = any(is_driver_copy(obj) for obj in armatures)
    return has_org_copy, has_driver_copy


def draw_status(layout, label, complete):
    row = layout.row(align=True)
    row.label(text=label, icon="CHECKMARK" if complete else "DOT")


def draw_step(layout, number, title, operator_id, button_text, hint, enabled, icon):
    box = layout.box()
    box.label(text=f"{number}. {title}")
    action = box.column()
    action.enabled = enabled
    action.operator(operator_id, text=button_text, icon=icon)
    box.label(text=hint, icon="INFO")


def draw_mapping_group(layout, title, props, fields):
    box = layout.box()
    box.label(text=title)
    for field_name, label in fields:
        box.prop(props, field_name, text=label)


class MOCAPTORIGIFY_PT_base:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MocapToRigify"


class MOCAPTORIGIFY_PT_workflow(MOCAPTORIGIFY_PT_base, bpy.types.Panel):
    bl_label = "Retargeting Workflow"
    bl_idname = "MOCAPTORIGIFY_PT_workflow"

    def draw(self, context):
        layout = self.layout
        active = context.active_object
        armatures = selected_armatures(context)
        active_is_armature = active is not None and active.type == "ARMATURE"
        only_armatures_selected = len(context.selected_objects) == len(armatures)
        bind_ready = only_armatures_selected and selection_is_pair(
            armatures, is_original_rigify, is_mocap
        )
        has_org_copy, has_driver_copy = scene_pipeline_state(context)

        selection = layout.box()
        selection.label(text="Current Selection", icon="RESTRICT_SELECT_OFF")
        if active_is_armature:
            selection.label(text=f"Active: {active.name}", icon="ARMATURE_DATA")
        else:
            selection.label(text="Select an armature to begin", icon="ERROR")
        selection.label(text=f"Selected armatures: {len(armatures)}")

        progress = layout.box()
        progress.label(text="Scene Setup", icon="OUTLINER_OB_ARMATURE")
        draw_status(progress, "ORG/MCH copy", has_org_copy)
        draw_status(progress, "Driver copy", has_driver_copy)

        binding = layout.box()
        binding.label(text="One-click Binding", icon="LINKED")
        action = binding.column()
        action.enabled = bind_ready
        action.scale_y = 1.4
        action.operator(
            "rigify_utils.bind_rigify_to_mocap",
            text="Bind Rigify to Mocap",
            icon="LINKED",
        )
        binding.label(
            text="Select the original Rigify and Mocap armatures.",
            icon="INFO",
        )


class MOCAPTORIGIFY_PT_debug_steps(MOCAPTORIGIFY_PT_base, bpy.types.Panel):
    bl_label = "Debug: Individual Steps"
    bl_idname = "MOCAPTORIGIFY_PT_debug_steps"
    bl_parent_id = "MOCAPTORIGIFY_PT_workflow"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        active = context.active_object
        armatures = selected_armatures(context)
        active_is_armature = active is not None and active.type == "ARMATURE"
        only_armatures_selected = len(context.selected_objects) == len(armatures)
        step1_ready = active_is_armature and is_original_rigify(active)
        step2_ready = only_armatures_selected and selection_is_pair(
            armatures, is_original_rigify, is_org_copy
        )
        step3_ready = only_armatures_selected and selection_is_pair(
            armatures, is_original_rigify, is_driver_copy
        )
        step4_ready = only_armatures_selected and selection_is_pair(
            armatures, is_org_copy, is_mocap
        )

        draw_step(
            layout,
            1,
            "Prepare ORG/MCH Copy",
            "rigify_utils.copy_rig",
            "Create ORG/MCH Copy",
            "Select the original Rigify armature.",
            step1_ready,
            "DUPLICATE",
        )
        draw_step(
            layout,
            2,
            "Create Driver Copy",
            "rigify_utils.copy_rig2",
            "Create Driver Copy",
            "Select original Rigify + ORG/MCH copy.",
            step2_ready,
            "DUPLICATE",
        )
        draw_step(
            layout,
            3,
            "Bind Rigify Controls",
            "rigify_utils.copy_rig3",
            "Bind Original Rigify",
            "Select original Rigify + driver copy.",
            step3_ready,
            "CONSTRAINT_BONE",
        )
        draw_step(
            layout,
            4,
            "Bind Mocap Source",
            "rigify_utils.copy_rig4",
            "Bind Mocap",
            "Select ORG/MCH copy + Mocap armature.",
            step4_ready,
            "LINKED",
        )


class MOCAPTORIGIFY_PT_corrections(MOCAPTORIGIFY_PT_base, bpy.types.Panel):
    bl_label = "Pose Corrections"
    bl_idname = "MOCAPTORIGIFY_PT_corrections"
    bl_parent_id = "MOCAPTORIGIFY_PT_workflow"

    def draw(self, context):
        layout = self.layout
        active = context.active_object
        selected_pose_bones = context.selected_pose_bones or ()
        ready = (
            active is not None
            and active.type == "ARMATURE"
            and active.mode == "POSE"
            and bool(selected_pose_bones)
        )

        if ready:
            layout.label(
                text=f"Selected pose bones: {len(selected_pose_bones)}",
                icon="CHECKMARK",
            )
        else:
            layout.label(text="Select bones in Pose Mode", icon="INFO")

        controls = layout.column()
        controls.enabled = ready

        snapshots = controls.row(align=True)
        snapshots.operator(
            "boneconstraints.store",
            text="Store Snapshot",
            icon="COPYDOWN",
        )
        snapshots.operator(
            "boneconstraints.apply",
            text="Restore",
            icon="PASTEDOWN",
        )

        controls.operator(
            "boneconstraints.keyframe_influence",
            text="Keyframe Influence",
            icon="KEY_HLT",
        )
        bake = controls.row()
        bake.alert = True
        bake.operator(
            "boneconstraints.bake_and_remove",
            text="Bake Pose & Release",
            icon="ACTION_TWEAK",
        )


class MOCAPTORIGIFY_PT_mapping(MOCAPTORIGIFY_PT_base, bpy.types.Panel):
    bl_label = "Bone Mapping"
    bl_idname = "MOCAPTORIGIFY_PT_mapping"
    bl_parent_id = "MOCAPTORIGIFY_PT_workflow"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        props = context.scene.my_addon_props

        draw_mapping_group(
            layout,
            "User Controls",
            props,
            (
                ("usr_torso", "Torso"),
                ("usr_hand_l", "Hand L"),
                ("usr_hand_r", "Hand R"),
                ("usr_foot_l", "Foot L"),
                ("usr_foot_r", "Foot R"),
            ),
        )
        draw_mapping_group(
            layout,
            "MCH Controls",
            props,
            (
                ("mch_torso", "Torso"),
                ("mch_hand_l", "Hand L"),
                ("mch_hand_r", "Hand R"),
                ("mch_foot_l", "Foot L"),
                ("mch_foot_r", "Foot R"),
            ),
        )
        draw_mapping_group(
            layout,
            "ORG Center",
            props,
            (("org_spine", "Spine / Hips"),),
        )
        draw_mapping_group(
            layout,
            "ORG Right",
            props,
            (
                ("org_shoulder_r", "Shoulder"),
                ("org_upper_arm_r", "Upper Arm"),
                ("org_forearm_r", "Forearm"),
                ("org_hand_r", "Hand"),
                ("org_thigh_r", "Thigh"),
                ("org_shin_r", "Shin"),
                ("org_foot_r", "Foot"),
                ("org_toe_r", "Toe"),
            ),
        )
        draw_mapping_group(
            layout,
            "ORG Left",
            props,
            (
                ("org_shoulder_l", "Shoulder"),
                ("org_upper_arm_l", "Upper Arm"),
                ("org_forearm_l", "Forearm"),
                ("org_hand_l", "Hand"),
                ("org_thigh_l", "Thigh"),
                ("org_shin_l", "Shin"),
                ("org_foot_l", "Foot"),
                ("org_toe_l", "Toe"),
            ),
        )


classes = (
    constrains.BONECONSTRAINTS_OT_store,
    constrains.BONECONSTRAINTS_OT_apply,
    constrains.BONECONSTRAINTS_OT_keyframe_influence,
    constrains.BONECONSTRAINTS_OT_bake_and_remove,
    rigify.BONECONSTRAINTS_test,
    rigify.BONECONSTRAINTS_OT_Copy_rig,
    rigify.BONECONSTRAINTS_OT_Copy_to_mocap_constrains,
    rigify.Rigify_spine_retarget,
    rigify.Rigify_utils_Copy_rig,
    rigify.Rigify_utils_Copy_rig2,
    rigify.Rigify_utils_Copy_rig3,
    rigify.Rigify_utils_Copy_rig4,
    rigify.Rigify_utils_Bind_rigify_to_mocap,
    rigify.MyAddonProperties,
    MOCAPTORIGIFY_PT_workflow,
    MOCAPTORIGIFY_PT_debug_steps,
    MOCAPTORIGIFY_PT_corrections,
    MOCAPTORIGIFY_PT_mapping,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.my_addon_props = bpy.props.PointerProperty(
        type=rigify.MyAddonProperties
    )


def unregister():
    del bpy.types.Scene.my_addon_props
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "main":
    register()
