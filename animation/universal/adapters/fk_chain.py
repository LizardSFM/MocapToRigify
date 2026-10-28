# The FK Chain adapter: the non-destructive correction workflow for any
# plain-FK rig -- metarigs used as final rigs, game-skeleton exports,
# Mixamo rigs. The 3-copy construction does not need Rigify:
#
#   * org copy    the driven bones, carrying the mocap motion through the
#                 RTG- proxies (shared builder)
#   * driver copy a full duplicate; its driven bones copy the org copy's
#                 rotations, and its hips bone carries the mocap travel
#   * original    every bone follows the driver's same-named bone with
#                 LOCAL/LOCAL AFTER mixing -- the rig's own simplicity is
#                 its mechanics -- and the hips gets the same travel
#                 constraint, so keys the user sets still layer on top
# exactly like on a Rigify rig.

from .. import binding, chain, matching
from ..binding import SUFFIX
from .base import RigAdapter


class FKChainAdapter(RigAdapter):
    id = "FK_CHAIN"
    label = "FK Chain"

    @classmethod
    def detect(cls, rig):
        # Any armature that is not a Rigify-generated rig is a plain-FK
        # candidate; the registry only asks adapters above this one first.
        return 0.7 if rig.type == "ARMATURE" else 0.0

    @classmethod
    def build(cls, context, target, source, rows, hips_gain):
        pairs = [(row.target_bone, row.source_bone) for row in rows if row.enabled]
        driven_bones = [name for name, _source in pairs]
        swing_bones = {row.target_bone for row in rows
                       if row.enabled and row.slot in matching.ALIGNED_SLOTS}
        hips_row = next((r for r in rows if r.slot == "hips" and r.enabled), None)

        # Stage 1: the mocap carrier.
        org_copy = chain.build_org_copy(context, target, driven_bones, {})
        binding.create_proxies(context, org_copy, source, pairs, swing_bones)
        bound = binding.bind_rotation_proxies(org_copy, source, pairs)

        # Stage 2: the driver duplicate. Its driven bones copy the org
        # copy's (rest-corrected) world rotations; the hips travel arrives
        # straight from the mocap through the same world mapping. The
        # rig's own IK constraints are muted here: an IK is a chain solver
        # that rewrites the rotations of its whole chain (forearm IK owns
        # the upper arm too), which fights the Copy Rotation instead of
        # layering with it.
        driver = chain.make_driver_skeleton(context, target)
        chain.mute_rig_ik(driver)
        for name in driven_bones:
            owner = driver.pose.bones.get(name)
            if owner is None:
                continue
            con = owner.constraints.new("COPY_ROTATION")
            con.name = "Copy Rotation" + SUFFIX
            con.target = org_copy
            con.subtarget = name
        hips_bound = False
        if hips_row is not None:
            hips_bound = binding.bind_hips_transform(
                driver, source, hips_row.target_bone, hips_row.source_bone, hips_gain)

        # Stage 3: the user's rig. Every bone that exists in the driver
        # follows it with AFTER mixing, so locally keyed corrections layer
        # on top of the mocap instead of fighting it. Bones the mapping
        # never touched (hair, cloth, jiggle) follow their own copies too
        # -- an inert no-op at rest that keeps the whole skeleton in sync.
        binding.clear_generated_constraints(target)
        muted_ik = chain.mute_rig_ik(target)
        for pose_bone in target.pose.bones:
            if pose_bone.name not in driver.pose.bones:
                continue
            con = pose_bone.constraints.new("COPY_ROTATION")
            con.name = "Copy Rotation" + SUFFIX
            con.target = driver
            con.subtarget = pose_bone.name
            con.target_space = "LOCAL"
            con.owner_space = "LOCAL"
            con.influence = 1.0
            con.mix_mode = "AFTER"
        if hips_row is not None:
            hips_bound = binding.bind_hips_transform(
                target, source, hips_row.target_bone, hips_row.source_bone, hips_gain
            ) and hips_bound

        return {"rotation_pairs": bound, "hips": hips_bound, "muted_ik": muted_ik}
