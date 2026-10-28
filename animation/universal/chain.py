# Shared scaffolding for the correction-layer adapters: the org-copy
# builder, the verified rig duplication, and the cleanup. The adapters in
# `adapters/` decide what to build out of these; this module knows
# nothing about any particular rig family.

import bpy
import json

from . import binding

ROLE_KEY = "urt_role"
ROLE_ORG = "org_copy"
ROLE_DRIVER = "driver_copy"
TARGET_KEY = "urt_target"
MUTED_IK_KEY = "urt_muted_ik"


def duplicate_rig(context, obj):
    """Duplicate `obj` with the object operator, but never trust it
    blindly: if the operator no-ops (hidden collection, odd context), the
    active object is still the original, and every caller downstream would
    be mangling the user's rig. Verify a new object came out, or raise."""
    binding.select_objects(context, (obj,), obj)
    before = set(bpy.data.objects)
    result = bpy.ops.object.duplicate()
    copy = context.view_layer.objects.active
    if copy is None or copy == obj:
        new = [o for o in bpy.data.objects if o not in before and o.type == "ARMATURE"]
        if len(new) == 1:
            copy = new[0]
    if copy is None or copy == obj or copy.type != "ARMATURE":
        raise RuntimeError(
            f"Duplicating '{obj.name}' failed (operator returned {result}); "
            "is the object's collection visible in this view layer?"
        )
    context.view_layer.objects.active = copy
    return copy


def _prune_children(obj):
    """A duplicated rig drags parented meshes along; drop them so the
    helper rigs stay armature-only."""
    for child in list(obj.children):
        if child.type != "ARMATURE":
            bpy.data.objects.remove(child, do_unlink=True)


def build_org_copy(context, target, driven_bones, mch_reparents):
    """Build the org copy from an exact copy of the target's armature
    datablock, minus every bone that is not driven.

    Copying the datablock keeps every rest roll bit-exact -- recreating
    bones from head/tail/roll is a trap: align_roll() degenerates when a
    bone's rest Z runs along its length (the hips, the thighs here) and hands
    back 180-degree-off rolls, which then ride the world-space Copy
    Rotations out to the controls as a backwards pelvis. Deleting bones
    from our own copy never touches the user's rig, and a fresh object
    carries no animation, constraints or locks, so there is nothing to
    strip either.
    """
    arm = target.data.copy()
    arm.name = target.name + "-URT-org"
    # The copied datablock may carry armature-level drivers; the org copy
    # is an inert carrier.
    anim = arm.animation_data
    if anim is not None:
        for fcurve in list(anim.drivers):
            try:
                arm.driver_remove(fcurve.data_path, fcurve.array_index)
            except RuntimeError:
                pass

    org_copy = bpy.data.objects.new(target.name + "-URT-org", arm)
    org_copy.matrix_world = target.matrix_world.copy()
    # Tag before anything else can fail, so Remove Setup always finds it.
    org_copy[ROLE_KEY] = ROLE_ORG
    org_copy[TARGET_KEY] = target.name
    owner_collections = target.users_collection
    (owner_collections[0] if owner_collections else context.scene.collection).objects.link(org_copy)

    wanted = set(driven_bones) | set(mch_reparents)
    binding.select_objects(context, (org_copy,), org_copy)
    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = arm.edit_bones
    for bone in list(edit_bones):
        if bone.name not in wanted:
            edit_bones.remove(bone)

    # Park each MCH IK parent on the bone whose world pose it must track
    # (the hand/foot/hips it will place an IK target for). Parenting beats
    # a constraint here: the MCH bone then inherits the whole driven chain.
    for mch_name, parent_name in mch_reparents.items():
        mch = edit_bones.get(mch_name)
        parent = edit_bones.get(parent_name)
        if mch is not None and parent is not None:
            mch.parent = parent
            mch.use_connect = False
    bpy.ops.object.mode_set(mode="OBJECT")

    for collection in arm.collections_all:
        collection.is_visible = True
    return org_copy


def make_driver_skeleton(context, target):
    """A verified full duplicate of the target as the driver rig: meshes
    pruned, its own animation replay dropped (constraints and drivers
    stay -- those are the rig's mechanics), tagged for cleanup."""
    binding.clear_generated_constraints(target)  # re-bind idempotency
    driver = duplicate_rig(context, target)
    _prune_children(driver)
    driver.name = target.name + "-URT-driver"
    anim = driver.animation_data
    if anim is not None:
        if anim.action is not None:
            anim.action_slot = None
            anim.action = None
        for track in list(anim.nla_tracks):
            anim.nla_tracks.remove(track)
    binding.clear_generated_constraints(driver)
    driver[ROLE_KEY] = ROLE_DRIVER
    driver[TARGET_KEY] = target.name
    return driver


def mute_rig_ik(obj):
    """Mute the rig's own IK constraints and record what was muted.

    An IK constraint is a chain solver: it rewrites the rotations of its
    whole chain (the forearm IK owns the upper arm too, the shin IK owns
    thigh and knee), so it does not layer with the AFTER-mix Copy Rotation
    -- the two solve the same bones twice and the limbs end up tens of
    degrees off. While the mocap drives the skeleton the rig's IK has
    nothing to contribute; it comes back on Remove. Bones not in the
    driver skeleton are left alone (their IK fights nothing we impose).

    The record rides a json custom property so a bind that predates a
    Remove (or a crashed bind) still restores cleanly next time.
    """
    record = []
    for pose_bone in obj.pose.bones:
        for con in pose_bone.constraints:
            if con.type != "IK" or con.name.endswith(binding.SUFFIX):
                continue
            if not con.mute:
                record.append([pose_bone.name, con.name])
                con.mute = True
    if record:
        obj[MUTED_IK_KEY] = json.dumps(record)
    return len(record)


def restore_rig_ik(obj):
    """Unmute the IK constraints a bind muted (Remove Setup)."""
    record = obj.get(MUTED_IK_KEY)
    if record is None:
        return 0
    count = 0
    for bone_name, con_name in json.loads(record):
        pose_bone = obj.pose.bones.get(bone_name)
        con = pose_bone.constraints.get(con_name) if pose_bone else None
        if con is not None:
            con.mute = False
            count += 1
    del obj[MUTED_IK_KEY]
    return count


def remove_setup(context, target=None):
    """Undo a bind: delete the generated copies, strip the generated
    constraints, restore anything the bind muted, remove the proxy bones."""
    removed = []
    for obj in list(context.scene.objects):
        if obj.get(ROLE_KEY) in (ROLE_ORG, ROLE_DRIVER):
            removed.append(obj.name)
            bpy.data.objects.remove(obj, do_unlink=True)
    if target is not None:
        binding.clear_generated_constraints(target)
        binding.remove_proxy_bones(context, target)
        restore_rig_ik(target)
    return removed
