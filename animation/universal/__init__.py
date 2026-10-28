# Universal retargeting: any rig -> any rig, mapping detected instead of
# typed. The core (analysis/matching/binding/chain) is rig-agnostic; the
# adapters/ package holds one strategy per rig family. Props holds the
# scene state, operators and panel the user surface.

from . import adapters, analysis, binding, chain, matching, operators, panel, props

classes = (
    props.URT_Row,
    props.URT_Props,
    operators.URT_OT_analyze,
    operators.URT_OT_bind,
    operators.URT_OT_remove,
    panel.MOCAPTORIGIFY_PT_universal,
    panel.MOCAPTORIGIFY_PT_universal_mapping,
)
