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
    """Swing the proxy round to point the way the mocap bone points at
    rest, keeping the target bone's own roll.

    Rigify rests in an A-pose and most captures rest in a T-pose; copying
    motion relative to each rig's own rest would stack the two (an arm
    lowered 80 degrees from a T lands 110 degrees down on a rig already 30
    degrees down). Only the swing is taken, never the twist, so the roll
    fix stays intact.
    """
    to_local = rig.matrix_world.inverted().to_3x3()
    mocap_rest = mocap.matrix_world @ mocap.data.bones[mocap_name].matrix_local
    mocap_dir = (to_local @ mocap_rest.to_3x3().col[1]).normalized()

    source_mat = source.matrix.to_3x3()
    org_dir = source_mat.col[1].normalized()
    org_up = source_mat.col[2].normalized()

    swing = org_dir.rotation_difference(mocap_dir)
    proxy.tail = source.head + mocap_dir * source.length
    proxy.align_roll(swing @ org_up)


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
        # Start from the target bone's own rest: that is what makes the
        # rest offset between the two rigs cancel out.
        proxy.head = source.head
        proxy.tail = source.tail
        proxy.roll = source.roll
        if target_name in swing_bones and mocap_name in mocap.data.bones:
            _align_proxy_to_mocap_rest(proxy, source, rig, mocap, mocap_name)
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
    """Root motion. Local space keeps the mocap's own travel instead of
    teleporting the rig onto the mocap's world position, and owner
    orientation makes it survive a hips bone that points the other way.

    A Transformation constraint rather than Copy Location, because it is
    the only one that can scale the travel: Copy Location's influence is
    capped at 1.0 and could never make a small capture walk far enough.
    """
    owner = rig.pose.bones.get(target_hips)
    if owner is None or mocap_hips not in mocap.data.bones:
        return False

    con = owner.constraints.new("TRANSFORM")
    con.name = "Transformation" + SUFFIX
    con.target = mocap
    con.subtarget = mocap_hips
    con.target_space = "LOCAL_OWNER_ORIENT"
    con.owner_space = "LOCAL"
    con.map_from = "LOCATION"
    con.map_to = "LOCATION"
    con.mix_mode = "ADD"
    # Map [-1, 1] onto [-gain, +gain] and extrapolate: a plain gain.
    con.use_motion_extrapolate = True
    for axis in "xyz":
        setattr(con, f"from_min_{axis}", -1.0)
        setattr(con, f"from_max_{axis}", 1.0)
        setattr(con, f"to_min_{axis}", -gain)
        setattr(con, f"to_max_{axis}", gain)
    return True


def hip_gain(source, source_hips, target, target_hips):
    """Rest-height ratio of the two hips bones, in armature units.

    The Transform constraint reads the mocap's *local* travel, so the gain
    has to convert mocap armature units into target armature units --
    head_local ratios do exactly that and ignore object scale.
    """
    src_bone = source.data.bones.get(source_hips)
    tgt_bone = target.data.bones.get(target_hips)
    if src_bone is None or tgt_bone is None:
        return 1.0
    src_z = abs(src_bone.head_local.z)
    tgt_z = abs(tgt_bone.head_local.z)
    if src_z < 1e-6:
        return 1.0
    return tgt_z / src_z
