# The constraint core: one unparented proxy bone per retargeted bone, a
# Child Of with the mocap rest matrix as its inverse, and a Copy Rotation
# off the proxy. Ported from the rigify-specific pipeline verbatim -- that
# math is rig-agnostic already, only the bone selection around it was not.
#
# Why the proxy: a plain world-space Copy Rotation forces
# target_pose = mocap_pose, which is only correct when both bones share a
# rest orientation (Rigify's ORG-hand sits ~102 degrees off a BVH hand).
# Child Of evaluates owner = target_pose * inverse_matrix * owner_rest, so
# feeding it the mocap bone's rest matrix yields
# target_pose = mocap_pose * mocap_rest^-1 * target_rest: the rotation the
# mocap bone actually travelled, applied on top of the target's own rest.

import bpy
from math import atan2

from mathutils import Vector

from .. import mapping

SUFFIX = "-urt"
PROXY_PREFIX = "RTG-"
PROXY_COLLECTION = "RTG-universal"


def proxy_name(bone_name):
    return PROXY_PREFIX + bone_name


def select_objects(context, objects, active):
    if context.object is not None and context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    context.view_layer.objects.active = active


def clear_generated_constraints(rig):
    """Drop every constraint this module created on `rig`."""
    for pose_bone in rig.pose.bones:
        for con in list(pose_bone.constraints):
            if con.name.endswith(SUFFIX):
                pose_bone.constraints.remove(con)


def remove_proxy_bones(context, rig):
    if not any(b.name.startswith(PROXY_PREFIX) for b in rig.data.bones):
        return
    select_objects(context, (rig,), rig)
    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = rig.data.edit_bones
    for bone in list(edit_bones):
        if bone.name.startswith(PROXY_PREFIX):
            edit_bones.remove(bone)
    bpy.ops.object.mode_set(mode="OBJECT")


def _align_proxy_to_mocap_rest(proxy, source, rig, mocap, mocap_name):
    """Rest the proxy in the mocap bone's own frame: same direction *and*
    same roll, scaled to the target bone's length.

    With the proxy framed like the mocap bone, the Child-Of delta makes
    the driven bone's world orientation equal the mocap bone's outright --
    which is what actually matters downstream: a roll mismatch does not
    show on a straight limb, but it rotates the plane the child bends in,
    so elbows and knees bend in a twisted plane and the hands and feet
    land far off the moment the limb folds. Swing-only alignment (the
    original pipeline's choice, preserving the target roll) is only right
    when both rigs share a twist convention -- an A-pose rig against a
    T-pose capture mostly does, a Source Filmmaker port against BVH does
    not.

    The roll is picked by closed loop: the signed-angle math is computed
    from a measured no-roll axis, then candidate rolls (sign and mirror
    variants) are written and their actual resulting Z axis read back,
    keeping the closest. align_roll()'s solver, an analytic reference and
    a single measured pass each produced mirrored frames on some bones
    and perfect ones on others.
    """
    from math import pi

    to_local = rig.matrix_world.inverted().to_3x3()
    mocap_rest = (mocap.matrix_world @ mocap.data.bones[mocap_name].matrix_local).to_3x3()
    mocap_dir = (to_local @ mocap_rest.col[1]).normalized()
    z_target = to_local @ mocap_rest.col[2]
    z_target = (z_target - mocap_dir * z_target.dot(mocap_dir))
    if z_target.length < 1e-8:
        z_target = to_local @ mocap_rest.col[0]
        z_target = (z_target - mocap_dir * z_target.dot(mocap_dir))
        if z_target.length < 1e-8:
            return
    z_target.normalize()

    proxy.tail = source.head + mocap_dir * source.length
    proxy.roll = 0.0
    z_base = proxy.z_axis.normalized()
    theta = atan2(z_base.cross(z_target).dot(mocap_dir), z_base.dot(z_target))

    best_roll = 0.0
    best_error = z_base.angle(z_target)
    for candidate in (theta, -theta, theta + pi, pi - theta):
        proxy.roll = candidate
        error = proxy.z_axis.normalized().angle(z_target)
        if error < best_error:
            best_error = error
            best_roll = candidate
    proxy.roll = best_roll


def create_proxies(context, rig, mocap, pairs, swing_bones=()):
    """One unparented helper bone per retargeted bone of `rig`."""
    select_objects(context, (rig,), rig)
    bpy.ops.object.mode_set(mode="EDIT")

    armature = rig.data
    if armature.collections_all.find(PROXY_COLLECTION) == -1:
        armature.collections.new(PROXY_COLLECTION)
    collection = armature.collections_all[PROXY_COLLECTION]

    created = []
    for target_name, mocap_name in pairs:
        source = armature.edit_bones.get(target_name)
        if source is None:
            continue
        proxy = armature.edit_bones.new(proxy_name(target_name))
        # The head anchors the proxy; everything else is either the
        # target bone's own rest (that is what makes the rest offset
        # between the two rigs cancel out) or, for aligned slots, the
        # mocap bone's full frame. Assign the frame before any other
        # roll has touched the bone: an edit bone's derived axes read
        # back stale on the first write after a mutation, and the roll
        # math below reads them.
        proxy.head = source.head
        if target_name in swing_bones and mocap_name in mocap.data.bones:
            _align_proxy_to_mocap_rest(proxy, source, rig, mocap, mocap_name)
        else:
            proxy.tail = source.tail
            proxy.roll = source.roll
        proxy.parent = None
        proxy.use_deform = False
        collection.assign(proxy)
        created.append(proxy.name)

    bpy.ops.object.mode_set(mode="OBJECT")
    collection.is_visible = False
    return created


def bind_rotation_proxies(rig, mocap, pairs):
    """Drive each target bone from its proxy, and each proxy from mocap."""
    count = 0
    for target_name, mocap_name in pairs:
        proxy = rig.pose.bones.get(proxy_name(target_name))
        mocap_bone = mocap.data.bones.get(mocap_name)
        owner = rig.pose.bones.get(target_name)
        if proxy is None or owner is None or mocap_bone is None:
            continue

        follow = proxy.constraints.new("CHILD_OF")
        follow.name = "Child Of" + SUFFIX
        follow.target = mocap
        follow.subtarget = mocap_name
        follow.inverse_matrix = (
            mocap.matrix_world @ mocap_bone.matrix_local
        ).inverted()

        copy_rotation = owner.constraints.new("COPY_ROTATION")
        copy_rotation.name = "Copy Rotation" + SUFFIX
        copy_rotation.target = rig
        copy_rotation.subtarget = proxy.name
        count += 1
    return count


def bind_hips_transform(rig, mocap, target_hips, mocap_hips, gain):
    """Root motion, as a plain gain on the mocap's travel.

    World-space affine mapping when the owner bone is a root (the org
    copy's hips always is): map the mocap hips' world position, anchored
    at its rest position, onto the owner's rest position plus gain x
    travel. Reading world axes directly is immune to either rig's hips
    pointing somewhere exotic -- a BVH root stub's local channels do not
    line up with world axes, and LOCAL_OWNER_ORIENT re-expresses them in
    the owner's rest frame, which skews the travel direction.

    Fallback for a parented hips (direct mode on a generic rig): the
    legacy local-space gain, converted to armature units.

    A Transformation constraint rather than Copy Location, because it is
    the only one that can scale the travel: Copy Location's influence is
    capped at 1.0 and could never make a small capture walk far enough.
    """
    owner = rig.pose.bones.get(target_hips)
    if owner is None or mocap_hips not in mocap.data.bones:
        return False

    mocap_bone = mocap.data.bones[mocap_hips]
    target_bone = rig.data.bones.get(target_hips)
    mocap_rest = mocap.matrix_world @ mocap_bone.head_local
    target_rest = rig.matrix_world @ target_bone.head_local

    con = owner.constraints.new("TRANSFORM")
    con.name = "Transformation" + SUFFIX
    con.target = mocap
    con.subtarget = mocap_hips
    con.map_from = "LOCATION"
    con.map_to = "LOCATION"
    con.use_motion_extrapolate = True

    parent = target_bone.parent
    # World mapping whenever the hips effectively roots the skeleton: no
    # parent, or a static master bone above it (nothing above a root ever
    # moves, so replacing the world position detaches it from nothing).
    rootish = (
        parent is None
        or parent.parent is None
        or "root" in mapping.normalize(parent.name)
    )
    if rootish:
        # World -> world, rest-anchored on both sides:
        #   out = target_rest + gain * (in - mocap_rest)
        con.target_space = "WORLD"
        con.owner_space = "WORLD"
        con.mix_mode = "REPLACE"
        for i, axis in enumerate("xyz"):
            setattr(con, f"from_min_{axis}", mocap_rest[i] - 1.0)
            setattr(con, f"from_max_{axis}", mocap_rest[i] + 1.0)
            setattr(con, f"to_min_{axis}", target_rest[i] - gain)
            setattr(con, f"to_max_{axis}", target_rest[i] + gain)
    else:
        con.target_space = "LOCAL_OWNER_ORIENT"
        con.owner_space = "LOCAL"
        con.mix_mode = "ADD"
        # Convert the world-units gain into the owner's armature units:
        # gain_local = gain_world * (mocap local->world) / (owner local->world).
        src_scale = (mocap.matrix_world.to_3x3() @ mocap_bone.head_local).length
        src_len = mocap_bone.head_local.length
        owner_scale = (rig.matrix_world.to_3x3() @ target_bone.head_local).length
        owner_len = target_bone.head_local.length
        factor = (src_scale / src_len) / (owner_scale / owner_len) if src_len > 1e-9 and owner_len > 1e-9 else 1.0
        local_gain = gain * factor
        for axis in "xyz":
            setattr(con, f"from_min_{axis}", -1.0)
            setattr(con, f"from_max_{axis}", 1.0)
            setattr(con, f"to_min_{axis}", -local_gain)
            setattr(con, f"to_max_{axis}", local_gain)
    return True


def hip_gain(source, source_hips, target, target_hips):
    """Rest-height ratio of the two hips bones, in world units.

    The hips travel of one rig, scaled by this, lands where the other
    rig's hips would: a 1.6 m capture driving a 10-unit character walks
    6-odd units per unit of capture travel.
    """
    src_bone = source.data.bones.get(source_hips)
    tgt_bone = target.data.bones.get(target_hips)
    if src_bone is None or tgt_bone is None:
        return 1.0
    src_z = abs((source.matrix_world @ src_bone.head_local).z)
    tgt_z = abs((target.matrix_world @ tgt_bone.head_local).z)
    if src_z < 1e-6:
        return 1.0
    return tgt_z / src_z
