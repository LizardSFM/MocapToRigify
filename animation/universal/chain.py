# The correction layer. Two ways to keep the retarget non-destructive:
#
# Chain mode (rigify-like targets) -- the proven three-copy construction,
# generalized off hardcoded bone names:
#   * org copy   `<target>-URT-org`    the driven bones + the MCH IK
#                parents, separated out; proxies pull mocap rotation in
#   * driver copy `<target>-URT-driver` a full duplicate of the rig whose
#                MCH parents / spine FK controls / neck+head controls
#                follow the org copy, so the rig's own IK and mechanics
#                solve against the mocap pose
#   * original    every control copies the driver's same-named control
#                AFTER its own local rotation, so keys the user sets still
#                layer on top
#
# Direct mode (anything else) -- the proxies and constraints go straight
# on the target's own bones. Corrections then happen per bone through the
# Keyframe Influence / Bake workflow rather than on top of the motion.

import bpy

from . import analysis, binding, matching
from .. import mapping

ROLE_KEY = "urt_role"
ROLE_ORG = "org_copy"
ROLE_DRIVER = "driver_copy"
TARGET_KEY = "urt_target"


def _duplicate(context, obj):
    binding.select_objects(context, (obj,), obj)
    bpy.ops.object.duplicate()
    return context.view_layer.objects.active


def _prune_children(obj):
    """A duplicated rig drags parented meshes along; drop them so the
    helper rigs stay armature-only."""
    for child in list(obj.children):
        if child.type != "ARMATURE":
            bpy.data.objects.remove(child, do_unlink=True)


def _purge_animation(id_data):
    """Drop action, NLA strips and drivers from an ID. AnimData has no
    clear() in 5.x, so drivers come off one driver_remove at a time."""
    anim = id_data.animation_data
    if anim is None:
        return
    if anim.action is not None:
        anim.action_slot = None
        anim.action = None
    for track in list(anim.nla_tracks):
        anim.nla_tracks.remove(track)
    for fcurve in list(anim.drivers):
        try:
            id_data.driver_remove(fcurve.data_path, fcurve.array_index)
        except RuntimeError:
            pass


def _strip_pose_state(rig, strip_constraints=True):
    _purge_animation(rig)
    _purge_animation(rig.data)
    if strip_constraints:
        for pose_bone in rig.pose.bones:
            for con in list(pose_bone.constraints):
                pose_bone.constraints.remove(con)
            pose_bone.lock_location = (False, False, False)
            pose_bone.lock_rotation = (False, False, False)
            pose_bone.lock_scale = (False, False, False)


def build_org_copy(context, target, driven_bones, mch_reparents):
    """Separate the driven bones and the MCH IK parents into a new
    armature that carries the mocap motion."""
    duplicate = _duplicate(context, target)
    _prune_children(duplicate)
    # Hidden bone layers make edit-mode selection unreliable; this object
    # is a scratch duplicate anyway, so show everything.
    for collection in duplicate.data.collections_all:
        collection.is_visible = True

    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = duplicate.data.edit_bones
    wanted = set(driven_bones) | set(mch_reparents)
    for bone in edit_bones:
        bone.select = bone.select_head = bone.select_tail = False
    for name in wanted:
        bone = edit_bones.get(name)
        if bone is not None:
            bone.select = bone.select_head = bone.select_tail = True

    before = set(bpy.data.objects)
    bpy.ops.armature.separate()
    bpy.ops.object.mode_set(mode="OBJECT")
    new_objects = [o for o in bpy.data.objects if o not in before and o.type == "ARMATURE"]
    bpy.data.objects.remove(duplicate, do_unlink=True)
    if not new_objects:
        raise RuntimeError("Separating the driven bones produced no armature")
    org_copy = new_objects[0]
    org_copy.name = target.name + "-URT-org"
    # Tag before anything else can fail, so Remove Setup always finds it.
    org_copy[ROLE_KEY] = ROLE_ORG
    org_copy[TARGET_KEY] = target.name

    # The org copy is an inert carrier: no animation, no constraints, no
    # locks -- just rest pose plus whatever the proxies push onto it.
    _strip_pose_state(org_copy, strip_constraints=True)

    # Park each MCH IK parent on the bone whose world pose it must track
    # (the hand/foot/hips it will place an IK target for). Parenting beats
    # a constraint here: the MCH bone then inherits the whole driven chain.
    binding.select_objects(context, (org_copy,), org_copy)
    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = org_copy.data.edit_bones
    for mch_name, parent_name in mch_reparents.items():
        mch = edit_bones.get(mch_name)
        parent = edit_bones.get(parent_name)
        if mch is not None and parent is not None:
            mch.parent = parent
            mch.use_connect = False
    bpy.ops.object.mode_set(mode="OBJECT")

    return org_copy


def _match_torso_control(driver, bone_name, bound, reserved=()):
    """The FK control of `driver` that should rotate with the org-copy
    bone `bone_name`.

    Ranked: equal trailing numbers with compatible names (spine_fk.003
    with ORG-spine.003), then an FK-named control sitting on the bone's
    joints, then any control on the joints. Controls already bound are
    skipped, and so are their direct children: a tweak control rides its
    FK parent through the hierarchy and must not be driven a second time
    on top. Only the direct link counts -- the FK controls themselves
    chain through MCH bones (spine_fk.003 hangs under MCH-spine.003 under
    spine_fk.002), and those must stay eligible.
    """
    bones = driver.data.bones
    bone = bones.get(bone_name)
    if bone is None:
        return None
    number = analysis.bone_number(bone_name)
    core = analysis.core_name(bone_name)

    best = None
    best_score = -1.0
    for name in analysis.control_bones(driver):
        if name in bound or name in reserved:
            continue
        control = bones[name]
        if control.parent is not None and control.parent.name in bound:
            continue
        control_number = analysis.bone_number(name)
        control_core = analysis.core_name(name)
        on_joints = (
            (control.head_local - bone.head_local).length < analysis.POSITION_EPS
            or (control.head_local - bone.tail_local).length < analysis.POSITION_EPS
        )
        is_fk = "fk" in mapping.normalize(name)
        if number and control_number and number == control_number \
                and (core in control_core or control_core in core):
            score = 4.0
        elif is_fk and on_joints:
            score = 3.0
        elif on_joints:
            score = 2.0
        else:
            continue
        score += min(len(control.children_recursive), 999) * 1e-3
        if score > best_score:
            best_score = score
            best = name
    return best


def build_driver_copy(context, target, org_copy, chain, driven_bones):
    binding.clear_generated_constraints(target)  # re-bind idempotency
    driver = _duplicate(context, target)
    _prune_children(driver)
    driver.name = target.name + "-URT-driver"
    # The driver must keep its rig mechanics (constraints and drivers on
    # the MCH bones), but must not replay the user's own animation.
    anim = driver.animation_data
    if anim is not None:
        anim.action = None
        for track in list(anim.nla_tracks):
            anim.nla_tracks.remove(track)
    binding.clear_generated_constraints(driver)
    driver[ROLE_KEY] = ROLE_DRIVER
    driver[TARGET_KEY] = target.name

    # MCH IK parents: they carry the targets the driver's IK solves for.
    for pose_bone in org_copy.pose.bones:
        if not pose_bone.name.startswith(analysis.MCH_PREFIX):
            continue
        owner = driver.pose.bones.get(pose_bone.name)
        if owner is None:
            continue
        for constraint_type in ("COPY_LOCATION", "COPY_ROTATION"):
            con = owner.constraints.new(constraint_type)
            con.name = constraint_type.replace("_", " ").title() + binding.SUFFIX
            con.target = org_copy
            con.subtarget = pose_bone.name

    # Torso: FK controls follow the org-copy spine bones. The neck/head
    # controls (driven directly, same-name, below) are reserved so the
    # positional matcher cannot grab them for an ORG bone -- the head
    # control sits exactly on ORG-spine.006's head and would otherwise
    # happily copy the upper chest instead of the capture's head.
    reserved = {name for name in driven_bones
                if name not in chain and not name.startswith(analysis.ORG_PREFIX)}
    bound = set()
    for bone_name in chain:
        control = _match_torso_control(driver, bone_name, bound, reserved)
        if control is None:
            continue
        con = driver.pose.bones[control].constraints.new("COPY_ROTATION")
        con.name = "Copy Rotation" + binding.SUFFIX
        con.target = org_copy
        con.subtarget = bone_name
        bound.add(control)

    # Driven bones that are not ORG-layer (neck/head controls on
    # featuresets without ORG twins) bind to their same-named controls.
    for name in sorted(reserved):
        if name in driver.pose.bones and name not in bound:
            con = driver.pose.bones[name].constraints.new("COPY_ROTATION")
            con.name = "Copy Rotation" + binding.SUFFIX
            con.target = org_copy
            con.subtarget = name
            bound.add(name)

    return driver


def bind_original(context, target, driver, ik_controls):
    """The user's rig follows the driver copy, with room left to correct:
    AFTER mixing keeps locally keyed rotation, the IK controls keep their
    location offset."""
    binding.clear_generated_constraints(target)
    ik = set(ik_controls)
    for name in analysis.control_bones(target):
        pose_bone = target.pose.bones.get(name)
        if pose_bone is None or name not in driver.pose.bones:
            continue
        con = pose_bone.constraints.new("COPY_ROTATION")
        con.name = "Copy Rotation" + binding.SUFFIX
        con.target = driver
        con.subtarget = name
        con.target_space = "LOCAL"
        con.owner_space = "LOCAL"
        con.influence = 1.0
        con.mix_mode = "AFTER"

        if name in ik:
            # These controls need the driver's local-with-parent transform
            # replaced rather than layered, plus the location to follow.
            con.target_space = "LOCAL_WITH_PARENT"
            con.owner_space = "LOCAL_WITH_PARENT"
            loc = pose_bone.constraints.new("COPY_LOCATION")
            loc.name = "Copy Location" + binding.SUFFIX
            loc.target = driver
            loc.subtarget = name
            loc.target_space = "LOCAL_WITH_PARENT"
            loc.owner_space = "LOCAL_WITH_PARENT"
            loc.influence = 1.0
            loc.use_offset = True  # allows moving around


def bind_chain(context, target, source, rows, hip_scale):
    """Assemble and wire the whole three-copy chain."""
    flavor = analysis.classify(target)
    pairs = [(row.target_bone, row.source_bone) for row in rows if row.enabled]
    driven_bones = [t for t, _s in pairs]
    swing_bones = {row.target_bone for row in rows
                   if row.enabled and row.slot in matching.SWING_SLOTS}
    hips_row = next((r for r in rows if r.slot == "hips" and r.enabled), None)

    mch_parents = analysis.detect_mch_ik_parents(target)
    mch_reparents = {}
    for mch_name, control_name in mch_parents.items():
        control = mapping.normalize(control_name)
        if control.startswith("handik"):
            slot = "hand_l" if control.endswith("l") else "hand_r"
        elif control.startswith("footik"):
            slot = "foot_l" if control.endswith("l") else "foot_r"
        else:
            slot = "hips"
        slot_row = next((r for r in rows if r.slot == slot and r.target_bone), None)
        if slot_row is not None:
            mch_reparents[mch_name] = slot_row.target_bone

    hips_target = hips_row.target_bone if hips_row else None
    chain = matching.chain_from_hips(target, hips_target, flavor) if hips_target else []

    org_copy = build_org_copy(context, target, driven_bones, mch_reparents)

    binding.create_proxies(context, org_copy, source, pairs, swing_bones)
    bound = binding.bind_rotation_proxies(org_copy, source, pairs)
    hips_bound = False
    if hips_row is not None:
        hips_bound = binding.bind_hips_transform(
            org_copy, source, hips_row.target_bone, hips_row.source_bone, hip_scale
        )

    driver = build_driver_copy(context, target, org_copy, chain, driven_bones)
    bind_original(context, target, driver, mch_parents.values())
    return {
        "org_copy": org_copy.name,
        "driver": driver.name,
        "rotation_pairs": bound,
        "hips": hips_bound,
        "mch_parents": len(mch_reparents),
    }


def bind_direct(context, target, source, rows, hip_scale):
    """No helper rigs: proxies and constraints straight on the target."""
    pairs = [(row.target_bone, row.source_bone) for row in rows if row.enabled]
    swing_bones = {row.target_bone for row in rows
                   if row.enabled and row.slot in matching.SWING_SLOTS}
    hips_row = next((r for r in rows if r.slot == "hips" and r.enabled), None)

    binding.clear_generated_constraints(target)
    binding.remove_proxy_bones(context, target)
    binding.create_proxies(context, target, source, pairs, swing_bones)
    bound = binding.bind_rotation_proxies(target, source, pairs)
    hips_bound = False
    if hips_row is not None:
        hips_bound = binding.bind_hips_transform(
            target, source, hips_row.target_bone, hips_row.source_bone, hip_scale
        )
    return {"rotation_pairs": bound, "hips": hips_bound}


def remove_setup(context, target=None):
    """Undo a bind: delete the generated copies, strip the generated
    constraints, remove the proxy bones."""
    removed = []
    for obj in list(context.scene.objects):
        if obj.get(ROLE_KEY) in (ROLE_ORG, ROLE_DRIVER):
            removed.append(obj.name)
            bpy.data.objects.remove(obj, do_unlink=True)
    if target is not None:
        binding.clear_generated_constraints(target)
        binding.remove_proxy_bones(context, target)
    return removed
