# The Direct adapter: proxies and constraints straight on the target's
# own bones, no helper rigs. Corrections happen per bone through the
# Keyframe Influence / Bake workflow rather than on top of the motion.

from .. import binding, chain, matching
from .base import RigAdapter


class DirectAdapter(RigAdapter):
    id = "DIRECT"
    label = "Direct"

    @classmethod
    def detect(cls, rig):
        return 0.1 if rig.type == "ARMATURE" else 0.0

    @classmethod
    def build(cls, context, target, source, rows, hips_gain):
        pairs = [(row.target_bone, row.source_bone) for row in rows if row.enabled]
        swing_bones = {row.target_bone for row in rows
                       if row.enabled and row.slot in matching.ALIGNED_SLOTS}
        hips_row = next((r for r in rows if r.slot == "hips" and r.enabled), None)

        binding.clear_generated_constraints(target)
        binding.remove_proxy_bones(context, target)
        binding.create_proxies(context, target, source, pairs, swing_bones)
        bound = binding.bind_rotation_proxies(target, source, pairs)
        hips_bound = False
        if hips_row is not None:
            hips_bound = binding.bind_hips_transform(
                target, source, hips_row.target_bone, hips_row.source_bone, hips_gain)
        return {"rotation_pairs": bound, "hips": hips_bound}
