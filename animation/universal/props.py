# Scene-side state for the universal retargeter: the two rigs, the
# binding options, and the mapping rows the panel shows. The rows are the
# single source of truth -- Analyze fills them, the user may fix them,
# Bind reads them.

import bpy


def _armature_poll(self, obj):
    return obj is not None and obj.type == "ARMATURE"


class URT_Row(bpy.types.PropertyGroup):
    slot: bpy.props.StringProperty(
        name="Slot",
        description="Canonical humanoid slot this pair fills ('' for surplus torso bones)",
    )
    label: bpy.props.StringProperty(name="Label")
    source_bone: bpy.props.StringProperty(name="Source Bone")
    target_bone: bpy.props.StringProperty(name="Target Bone")
    enabled: bpy.props.BoolProperty(
        name="Enabled",
        description="Include this pair in the retarget",
        default=True,
    )
    required: bpy.props.BoolProperty(name="Required")
    conf_source: bpy.props.IntProperty(name="Source Confidence", default=0)
    conf_target: bpy.props.IntProperty(name="Target Confidence", default=0)


class URT_Props(bpy.types.PropertyGroup):
    source: bpy.props.PointerProperty(
        name="Source (Mocap) Rig",
        description="The animated rig to take motion from",
        type=bpy.types.Object,
        poll=_armature_poll,
    )
    target: bpy.props.PointerProperty(
        name="Target Rig",
        description="The rig that should follow the mocap",
        type=bpy.types.Object,
        poll=_armature_poll,
    )
    mode: bpy.props.EnumProperty(
        name="Binding Mode",
        items=(
            ("AUTO", "Auto",
             "Rigify chain when the target looks Rigify-generated, direct constraints otherwise"),
            ("CHAIN", "Rigify Chain",
             "Three-copy chain: an ORG copy follows the mocap, a driver copy runs the rig's "
             "own mechanics, the original follows the driver -- corrections stay possible "
             "on top of the motion"),
            ("DIRECT", "Direct",
             "Constraints straight on the target's bones; correct per bone with Keyframe "
             "Influence / Bake. Best for plain FK rigs"),
        ),
        default="AUTO",
    )
    auto_hip_scale: bpy.props.BoolProperty(
        name="Auto Hip Scale",
        description="Prefill the hip travel gain from the rigs' rest heights",
        default=True,
    )
    hip_scale: bpy.props.FloatProperty(
        name="Hip Travel Scale",
        description="Gain on the mocap hips travel, in target armature units",
        default=1.0,
        min=0.001,
        soft_max=20.0,
        precision=3,
    )
    rows: bpy.props.CollectionProperty(type=URT_Row)
    status: bpy.props.StringProperty(name="Status")
