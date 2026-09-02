# Universal retargeting: any rig -> any rig, mapping detected instead of
# typed. See analysis/matching/binding/chain for the layers; props holds
# the scene state, operators and panel the user surface.

from . import analysis, binding, chain, matching, operators, panel, props

classes = (
    props.URT_Row,
    props.URT_Props,
    operators.URT_OT_analyze,
    operators.URT_OT_bind,
    operators.URT_OT_remove,
    panel.MOCAPTORIGIFY_PT_universal,
    panel.MOCAPTORIGIFY_PT_universal_mapping,
)
