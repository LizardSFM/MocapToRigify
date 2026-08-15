# For mocap. Copy rig, leave only ORG, reparent them. 

import bpy
from bpy.props import StringProperty


from . import mapping
from .mapping import (
    is_driver_copy,
    is_mocap_armature,
    is_org_copy,
    is_original_rigify,
)

# Everything this add-on creates carries a marker so a re-bind can clean up
# after itself instead of stacking a second set of constraints on top.
MOCAP_SUFFIX = "-mocap"
PROXY_PREFIX = "RTG-"
PROXY_COLLECTION = "RTG-mocap"
# Step 3 marks the constraints it puts on the user's own rig separately, so a
# re-bind can strip them without touching anything the animator added.
CONTROL_SUFFIX = "-mocap2"


def find_centered_bones(bones):
    center_bones = []
    for bone in bones:
        if abs(bone.head.x) < 0.001 and abs(bone.tail.x) < 0.001:
            center_bones.append(bone)
    # AI Sort bones by their Z position (assuming spine runs vertically) 
    center_bones.sort(key=lambda bone: bone.head.z)
    return center_bones

def find_closest_bone(current_bone, other_bones):
    """Nearest bone by midpoint. Returns (None, inf) when there is nothing to
    compare against, so callers must check before touching the result."""
    closest_bone = None
    closest_dist = float('inf')

    # Use the midpoint of current bone as reference
    current_mid = (current_bone.head + current_bone.tail) * 0.5

    for bone in other_bones:
        # Midpoint of candidate bone
        bone_mid = (bone.head + bone.tail) * 0.5

        # Distance between midpoints
        dist = (bone_mid - current_mid).length

        if dist < closest_dist:
            closest_dist = dist
            closest_bone = bone

    return closest_bone, closest_dist


# Tolerance when matching a DEF bone's head/tail against an ORG bone's.
_DEF_POSITION_EPS = 0.00001


def _is_descendant(bone, ancestor):
    """True when 'bone' is 'ancestor' or lies somewhere below it."""
    current = bone
    while current is not None:
        if current == ancestor:
            return True
        current = current.parent
    return False


def _positional_def_counterpart(org_bone, def_bones, skip):
    """DEF bone occupying exactly the same span (head & tail) as an ORG bone.

    Same-direction matches win over flipped ones (head<->tail swapped), and
    among equals the name-corresponding DEF (ORG-spine.001 -> DEF-spine.001)
    wins. 'skip' is never returned: it is the DEF bone being re-parented,
    which often sits exactly where its own ORG parent does.
    """
    expected = "DEF-" + org_bone.name[len("ORG-"):]
    best = None
    best_rank = None
    for candidate in def_bones:
        if candidate == skip:
            continue
        same_direction = (
            (candidate.head - org_bone.head).length < _DEF_POSITION_EPS
            and (candidate.tail - org_bone.tail).length < _DEF_POSITION_EPS
        )
        flipped = (
            (candidate.head - org_bone.tail).length < _DEF_POSITION_EPS
            and (candidate.tail - org_bone.head).length < _DEF_POSITION_EPS
        )
        if not (same_direction or flipped):
            continue
        rank = (
            0 if same_direction else 1,
            0 if candidate.name == expected else 1,
        )
        if best_rank is None or rank < best_rank:
            best = candidate
            best_rank = rank
    return best


def rigify_def_parent_fix(armature_object, context=None):
    """Re-parent DEF bones that hang directly under an ORG bone.

    On some Rigify rigs a few DEF bones (shoulder, thigh, ...) end up
    parented to an ORG bone instead of the deform chain, e.g.
    DEF-shoulder.L -> ORG-spine.001. The new DEF parent is found with two
    rules, in order:

    1. The ORG parent is itself parented to a DEF bone: use that bone, so
       the chain stays DEF -> DEF:
           DEF-shoulder.L -> ORG-spine.001 -> DEF-spine.005
           becomes DEF-shoulder.L -> DEF-spine.005
    2. Otherwise (the ORG parent hangs under another ORG bone, an MCH bone
       or nothing): use the DEF bone that sits in exactly the same spot as
       the ORG parent (head and tail coincide), if there is one:
           DEF-shoulder.L -> ORG-spine.001 (no DEF bone above it)
           becomes DEF-shoulder.L -> DEF-spine.001

    Returns how many bones were re-parented.
    """
    if armature_object is None or armature_object.type != 'ARMATURE':
        return 0

    ctx = context or bpy.context
    view_layer = ctx.view_layer
    prev_active = view_layer.objects.active
    prev_selected = [obj for obj in view_layer.objects if obj.select_get()]

    # Bone parenting is only editable in Edit Mode, which needs the armature
    # to be the active and selected object.
    if ctx.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for obj in prev_selected:
        obj.select_set(False)
    armature_object.select_set(True)
    view_layer.objects.active = armature_object
    bpy.ops.object.mode_set(mode='EDIT')

    fixed = 0
    edit_bones = armature_object.data.edit_bones
    def_bones = [b for b in edit_bones if b.name.startswith("DEF-")]

    for bone in def_bones:
        org_parent = bone.parent
        if org_parent is None or not org_parent.name.startswith("ORG-"):
            continue
        matched_by_position = False
        def_parent = org_parent.parent
        if def_parent is None or not def_parent.name.startswith("DEF-"):
            # The ORG parent does not lead to the DEF chain through the
            # hierarchy: look for a DEF bone that is a positional copy of
            # the ORG parent instead.
            def_parent = _positional_def_counterpart(org_parent, def_bones, bone)
            matched_by_position = def_parent is not None
            if not matched_by_position:
                continue
        if _is_descendant(def_parent, bone):
            # Would create a bone cycle; leave this one alone.
            continue
        bone.parent = def_parent
        # Keep the bone connected only when it physically touches its new
        # parent, otherwise the connected flag would snap it out of place.
        bone.use_connect = (bone.head - def_parent.tail).length < 0.0001
        fixed += 1
        if matched_by_position:
            print("DEF parent fix: '" + bone.name + "' -> '" + def_parent.name
                  + "' (positional match for '" + org_parent.name + "')")
        else:
            print("DEF parent fix: '" + bone.name + "' -> '" + def_parent.name + "'")

    bpy.ops.object.mode_set(mode='OBJECT')

    # Put the caller's selection and active object back.
    for obj in prev_selected:
        if obj.name in view_layer.objects:
            obj.select_set(True)
    if prev_active is not None and prev_active.name in view_layer.objects:
        view_layer.objects.active = prev_active

    return fixed

## TODO: clear constrains when copying, and back to pose position


def proxy_name(org_name):
    return PROXY_PREFIX + org_name


# Rigify's own plumbing. These bones are driven by the rig itself, an animator
# never touches them, and they must not be bound to the driver copy.
INTERNAL_COLLECTIONS = {"ORG", "MCH", "DEF"}


def control_bones(rigify_object):
    """Every bone an animator can pose: all of them except Rigify's internals.

    Deliberately not "the visible ones" -- visibility is a UI state the user
    toggles, and letting it decide what gets bound made the result depend on
    which collections happened to be open.
    """
    result = []
    for pose_bone in rigify_object.pose.bones:
        collections = pose_bone.bone.collections
        if not collections:
            continue
        if any(c.name not in INTERNAL_COLLECTIONS for c in collections):
            result.append(pose_bone)
    return result


def resolve_mocap_map(context, mocap):
    """Mocap bone per canonical slot: whatever the user typed in the panel,
    falling back to auto-detection.

    A typed name only wins if the selected armature actually has that bone.
    The fields persist in the scene, so binding a second mocap rig with a
    different naming convention would otherwise inherit the first rig's
    names and resolve nothing.
    """
    props = context.scene.my_addon_props
    detected = mapping.detect_mocap_bones(mocap)
    resolved = {}
    for slot in mapping.SLOTS:
        typed = getattr(props, mapping.mocap_prop_name(slot), "").strip()
        if typed and typed in mocap.data.bones:
            resolved[slot] = typed
            continue
        name = detected.get(slot, "")
        if name and name in mocap.data.bones:
            resolved[slot] = name
    return resolved


def store_mocap_map(props, resolved):
    for slot in mapping.SLOTS:
        setattr(props, mapping.mocap_prop_name(slot), resolved.get(slot, ""))


def clear_mocap_binding(context, org_copy):
    """Undo a previous bind so re-running step 4 replaces it instead of
    stacking a second copy on top."""
    for pose_bone in org_copy.pose.bones:
        for con in list(pose_bone.constraints):
            if con.name.endswith(MOCAP_SUFFIX):
                pose_bone.constraints.remove(con)

    if not any(b.name.startswith(PROXY_PREFIX) for b in org_copy.data.bones):
        return
    _select_objects(context, (org_copy,), org_copy)
    bpy.ops.object.mode_set(mode='EDIT')
    edit_bones = org_copy.data.edit_bones
    for bone in list(edit_bones):
        if bone.name.startswith(PROXY_PREFIX):
            edit_bones.remove(bone)
    bpy.ops.object.mode_set(mode='OBJECT')


def _align_proxy_to_mocap_rest(proxy, source, org_copy, mocap, mocap_name):
    """Swing the proxy round to point the way the mocap bone points at rest,
    keeping the Rigify bone's own roll.

    Rigify rests in an A-pose and most captures rest in a T-pose. Copying the
    motion relative to each rig's own rest would then stack the two: an arm
    lowered 80 degrees from a T-pose lands 110 degrees down on a rig that was
    already 30 degrees down, and the hands end up crossing the body. Only the
    swing is taken, never the twist, so the roll fix stays intact.
    """
    to_local = org_copy.matrix_world.inverted().to_3x3()
    mocap_rest = mocap.matrix_world @ mocap.data.bones[mocap_name].matrix_local
    mocap_dir = (to_local @ mocap_rest.to_3x3().col[1]).normalized()

    source_mat = source.matrix.to_3x3()
    org_dir = source_mat.col[1].normalized()
    org_up = source_mat.col[2].normalized()

    swing = org_dir.rotation_difference(mocap_dir)
    proxy.tail = source.head + mocap_dir * source.length
    proxy.align_roll(swing @ org_up)


def create_retarget_proxies(context, org_copy, mocap, pairs, aligned=()):
    """One unparented helper bone per retargeted ORG bone. The helper is what
    carries the mocap motion; the ORG bone only copies rotation off it."""
    _select_objects(context, (org_copy,), org_copy)
    bpy.ops.object.mode_set(mode='EDIT')

    armature = org_copy.data
    if armature.collections_all.find(PROXY_COLLECTION) == -1:
        armature.collections.new(PROXY_COLLECTION)
    collection = armature.collections_all[PROXY_COLLECTION]

    edit_bones = armature.edit_bones
    created = []
    for org_name, mocap_name in pairs.items():
        source = edit_bones.get(org_name)
        if source is None:
            continue
        proxy = edit_bones.new(proxy_name(org_name))
        # Start from the ORG bone's own rest: that is what makes the rest
        # offset between the two rigs cancel out.
        proxy.head = source.head
        proxy.tail = source.tail
        proxy.roll = source.roll
        if org_name in aligned and mocap_name in mocap.data.bones:
            _align_proxy_to_mocap_rest(proxy, source, org_copy, mocap, mocap_name)
        proxy.parent = None
        proxy.use_deform = False
        collection.assign(proxy)
        created.append(proxy.name)

    bpy.ops.object.mode_set(mode='OBJECT')
    collection.is_visible = False
    return created


def bind_proxies_to_mocap(org_copy, mocap, pairs):
    """Drive each ORG bone from its proxy, and each proxy from the mocap.

    A plain world-space Copy Rotation forces ORG_pose = MOCAP_pose, which is
    only correct when both bones share a rest orientation. They usually do
    not: Rigify's ORG-hand sits about 102 degrees off a VRM/Mixamo hand, and
    that error travels down into MCH-hand_ik.parent and out to hand_ik.

    Child Of evaluates as owner = target_pose * inverse_matrix * owner_rest.
    Feeding it the mocap bone's rest matrix as the inverse turns that into
    ORG_pose = MOCAP_pose * MOCAP_rest^-1 * ORG_rest, which is the rotation
    the mocap bone actually travelled, applied on top of Rigify's own rest.
    """
    count = 0
    for org_name, mocap_name in pairs.items():
        proxy = org_copy.pose.bones.get(proxy_name(org_name))
        target_bone = mocap.data.bones.get(mocap_name)
        owner = org_copy.pose.bones.get(org_name)
        if proxy is None or owner is None or target_bone is None:
            continue

        follow = proxy.constraints.new('CHILD_OF')
        follow.name = "Child Of" + MOCAP_SUFFIX
        follow.target = mocap
        follow.subtarget = mocap_name
        follow.inverse_matrix = (
            mocap.matrix_world @ target_bone.matrix_local
        ).inverted()

        copy_rotation = owner.constraints.new('COPY_ROTATION')
        copy_rotation.name = "Copy Rotation" + MOCAP_SUFFIX
        copy_rotation.target = org_copy
        copy_rotation.subtarget = proxy.name
        count += 1
    return count


def bind_hips_location(org_copy, mocap, hips_org, hips_mocap, scale):
    """Root motion. Local space keeps the mocap's own travel instead of
    teleporting the rig onto the mocap's world position, and owner
    orientation makes it survive a hips bone that points the other way
    (the VRM hips bone is 185 degrees off Rigify's).

    A Transformation constraint rather than Copy Location, because it is the
    only one that can scale the travel: Copy Location's influence is capped
    at 1.0 and could never make the character walk further than the mocap.
    """
    owner = org_copy.pose.bones.get(hips_org)
    if owner is None or hips_mocap not in mocap.data.bones:
        return False

    con = owner.constraints.new('TRANSFORM')
    con.name = "Transformation" + MOCAP_SUFFIX
    con.target = mocap
    con.subtarget = hips_mocap
    con.target_space = 'LOCAL_OWNER_ORIENT'
    con.owner_space = 'LOCAL'
    con.map_from = 'LOCATION'
    con.map_to = 'LOCATION'
    con.mix_mode = 'ADD'
    # Map [-1, 1] onto [-scale, scale] and extrapolate, which is a plain gain.
    con.use_motion_extrapolate = True
    for axis in "xyz":
        setattr(con, f"from_min_{axis}", -1.0)
        setattr(con, f"from_max_{axis}", 1.0)
        setattr(con, f"to_min_{axis}", -scale)
        setattr(con, f"to_max_{axis}", scale)
    return True


def _select_objects(context, objects, active):
    if context.object is not None and context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects:
        obj.select_set(True)
    context.view_layer.objects.active = active


def _run_binding_operator(result, step_name):
    if result != {'FINISHED'}:
        raise RuntimeError(f"{step_name} was cancelled")


def _new_armature(before_pointers, step_name):
    created = [
        obj for obj in bpy.data.objects
        if obj.type == 'ARMATURE' and obj.as_pointer() not in before_pointers
    ]
    if len(created) != 1:
        names = ", ".join(obj.name for obj in created) or "none"
        raise RuntimeError(f"{step_name} created {len(created)} armatures: {names}")
    return created[0]


def bind_step1(context, rigify: bpy.types.Object):
    """Run the existing ORG/MCH-copy operator for one Rigify armature."""
    before_pointers = {obj.as_pointer() for obj in bpy.data.objects}
    _select_objects(context, (rigify,), rigify)
    _run_binding_operator(bpy.ops.rigify_utils.copy_rig(), "Step 1")
    return _new_armature(before_pointers, "Step 1")


def bind_step2(context, rigify: bpy.types.Object, org_copy: bpy.types.Object):
    """Run the existing driver-copy operator for an explicit object pair."""
    before_pointers = {obj.as_pointer() for obj in bpy.data.objects}
    _select_objects(context, (rigify, org_copy), rigify)
    _run_binding_operator(bpy.ops.rigify_utils.copy_rig2(), "Step 2")
    return _new_armature(before_pointers, "Step 2")


def bind_step3(context, rigify: bpy.types.Object, driver_copy: bpy.types.Object):
    """Run the existing Rigify-controls operator for an explicit object pair."""
    _select_objects(context, (rigify, driver_copy), rigify)
    _run_binding_operator(bpy.ops.rigify_utils.copy_rig3(), "Step 3")


def bind_step4(context, org_copy: bpy.types.Object, mocap: bpy.types.Object):
    """Run the existing Mocap-source operator. Step 4 picks the two objects
    apart by role now, so the selection order no longer matters."""
    _select_objects(context, (org_copy, mocap), org_copy)
    _run_binding_operator(bpy.ops.rigify_utils.copy_rig4(), "Step 4")


class Rigify_utils_Copy_rig(bpy.types.Operator):
    """Copy rigify rig, leave ORG and MCH bones. It should follow mocap rig"""
    bl_idname = "rigify_utils.copy_rig"
    bl_label = "Copy rigify rig"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        bpy.ops.object.mode_set(mode='OBJECT')
        obj = context.active_object
        orig_obj = context.active_object
        orig_name = context.active_object.name

        if obj is None or obj.type != "ARMATURE" or obj.data.collections_all.find("Torso (Tweak)") == -1:
            self.report({'ERROR'}, "Select a rigify armature")
            return {'CANCELLED'}
        
        bpy.ops.object.duplicate()
        obj = context.active_object

        
        # Cut ORG out as new armature
        org_id = obj.data.collections_all.find("ORG")
        obj.data.collections_all[org_id].name = ("ORG-mocap")
        obj.data.collections_all[org_id].is_solo = True
        col = obj.data.collections[org_id]
        bpy.ops.object.editmode_toggle(True)

        # Cut and edit the neck (reduce from 2 bones to 1)

        # Move feet MCH to MCH-mocap for proper retargeting of feet later
        obj.data.collections.new("MCH-mocap")
        obj.data.collections_all["MCH-mocap"].is_solo = True
        # Name of bone, their new parent, 1 if parent should lose parent

        props = context.scene.my_addon_props # Stored user inputs in UI
        mchbones = {props.mch_foot_l: [props.org_foot_l, False],
                    props.mch_foot_r: [props.org_foot_r, False],
                    props.mch_hand_r: [props.org_hand_r, False],
                    props.mch_hand_l: [props.org_hand_l, False], 
                    props.mch_torso: [props.org_spine, True]}
        
        for bone_name, parent_data in mchbones.items():
            parent_name = parent_data[0]
            parent_loses_parent = parent_data[1]
            bone = obj.data.edit_bones[bone_name]
            parent = obj.data.edit_bones[parent_name]

            obj.data.collections["MCH-mocap"].assign(bone)
            obj.data.collections["MCH"].unassign(bone)
            if parent_loses_parent:
                parent.parent = None
            bone.parent = parent
        # obj.data.collections_all["MCH-mocap"].is_solo = False
        
        # Not needed
        # obj.data.edit_bones.remove(obj.data.edit_bones["ORG-breast.L"])
        # obj.data.edit_bones.remove(obj.data.edit_bones["ORG-breast.R"])
        # obj.data.edit_bones.remove(obj.data.edit_bones["ORG-pelvis.L"])
        # obj.data.edit_bones.remove(obj.data.edit_bones["ORG-pelvis.R"])

        bpy.ops.armature.select_all(action='SELECT')
        bpy.ops.armature.separate()
        bpy.ops.object.editmode_toggle(False)

        # org_rig = bpy.context.selected_objects[1]
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.context.view_layer.objects.active = bpy.context.selected_objects[0]

        obj = context.active_object
        # Make ORG visible
        bpy.ops.armature.collection_remove_unused()
        for i, collection in enumerate(obj.data.collections):
            collection.is_visible = True
            collection.is_solo = False
        
        # Clear constrains and Locks
        bpy.ops.object.posemode_toggle(True)
        for pose_bone in obj.pose.bones:
            bpy.ops.pose.constraints_clear()
            pose_bone.lock_location[0] = False
            pose_bone.lock_location[1] = False
            pose_bone.lock_location[2] = False
            pose_bone.lock_rotation_w = False
            pose_bone.lock_rotation[0] = False
            pose_bone.lock_rotation[1] = False
            pose_bone.lock_rotation[2] = False
            pose_bone.lock_scale[0] = False
            pose_bone.lock_scale[1] = False
            pose_bone.lock_scale[2] = False
        bpy.ops.pose.select_all(action='SELECT')
        bpy.ops.pose.constraints_clear()
        bpy.ops.object.posemode_toggle(False)

        # Find center bones 
        bpy.ops.object.editmode_toggle(True)
        edit_bones = obj.data.edit_bones

        # Find only ORG bones
        org_bones = []
        for bone in edit_bones:
            cols = bone.collections
            for col in cols:
                if col.name == "ORG-mocap": org_bones.append(bone)
        center_bones = find_centered_bones(org_bones)
        
        # Reparent. Need to only be used on ORG
        for i, edit_bone in enumerate(center_bones):
            if i >= (len(center_bones) - 1): break
            current_bone = center_bones[i]
            next_bone = center_bones[i + 1]
            
            # Check if next bone's head matches current bone's tail
            head_tail_match = (
                abs(next_bone.head.x - current_bone.tail.x) < 0.001 and
                abs(next_bone.head.y - current_bone.tail.y) < 0.001 and
                abs(next_bone.head.z - current_bone.tail.z) < 0.001
            )
            if head_tail_match:
                next_bone.parent = current_bone
                # next_bone.use_connect = True
                print(f"Parented '{next_bone.name}' to '{current_bone.name}'")
            else:
                print(f"Warning: '{next_bone.name}' head doesn't match '{current_bone.name}' tail position")
            # bpy.context.active_bone.parent = bpy.data.armatures["rig.012"].edit_bones["ORG-pelvis.L"]
        
        # Specific finger parenting
        # edit_bones["ORG-thumb.01.R"].parent = edit_bones["ORG-hand.R"]
        # edit_bones["ORG-palm.01.R"].parent = edit_bones["ORG-hand.R"]
        # edit_bones["ORG-palm.02.R"].parent = edit_bones["ORG-hand.R"]
        # edit_bones["ORG-palm.03.R"].parent = edit_bones["ORG-hand.R"]
        # edit_bones["ORG-palm.04.R"].parent = edit_bones["ORG-hand.R"]

        # edit_bones["ORG-thumb.01.L"].parent = edit_bones["ORG-hand.L"]
        # edit_bones["ORG-palm.01.L"].parent = edit_bones["ORG-hand.L"]
        # edit_bones["ORG-palm.02.L"].parent = edit_bones["ORG-hand.L"]
        # edit_bones["ORG-palm.03.L"].parent = edit_bones["ORG-hand.L"]
        # edit_bones["ORG-palm.04.L"].parent = edit_bones["ORG-hand.L"]
        bpy.ops.object.editmode_toggle(False)

        obj.data.pose_position = 'POSE'
        obj.name = orig_name + "-copy-org-mch"
        # Tag the role so later steps recognise it even if it gets renamed.
        obj[mapping.GENERATED_ROLE_KEY] = mapping.ROLE_COPY_ORG_MCH
        orig_obj.select_set(True)

        if getattr(context.scene.my_addon_props, "fix_def_parents", False):
            fixed = rigify_def_parent_fix(orig_obj, context)
            self.report({'INFO'}, f"Copied the rig, re-parented {fixed} DEF bone(s)")
        else:
            self.report({'INFO'}, "Copied the rig")
        return {'FINISHED'}

## TODO: clear constrains when copying, and back to pose position
# TODO: Attempt to create Transform con for hands
class Rigify_utils_Copy_rig2(bpy.types.Operator):
    """Copy rigify rig, attach it to copy-org-mch"""
    bl_idname = "rigify_utils.copy_rig2"
    bl_label = "Copy rigify rig2"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        bpy.ops.object.mode_set(mode='OBJECT')

        if len(context.selected_objects) < 2:
            self.report({'ERROR'}, "Select two armatures, one is Rigify copy, other is copy-org-mch")
            return {'CANCELLED'}
        
        
        orig = context.selected_objects[0]
        copy_org = context.selected_objects[1]
        if orig.data.collections_all.find("Torso (Tweak)") == -1:
            orig = context.selected_objects[1]
            copy_org = context.selected_objects[0]
        
        # Duplicate rigify rig for attaching to copy-org-mch
        bpy.ops.object.select_all(action='DESELECT')
        orig.select_set(True)
        bpy.context.view_layer.objects.active = orig
        bpy.ops.object.duplicate()

        copy = bpy.context.active_object
        copy.name = orig.name + "-copy"
        copy[mapping.GENERATED_ROLE_KEY] = mapping.ROLE_DRIVER_COPY

        # Iterating over bones
        bpy.ops.object.posemode_toggle(True)
        bpy.context.object.data.collections_all["MCH"].is_visible = True
        bpy.ops.pose.select_all(action='SELECT')
        # name, copy from, 1 copy location, 1 copy rotation
        props = context.scene.my_addon_props # Stored user inputs in UI
        bone_binds = {props.mch_torso: [props.mch_torso, 1,1],
                      props.mch_hand_l: [props.mch_hand_l, 1,1],
                      props.mch_hand_r: [props.mch_hand_r, 1,1],
                      props.usr_foot_l: [props.mch_foot_l, 1,1],
                      props.usr_foot_r: [props.mch_foot_r, 1,1],}
        

        for bone in context.selected_pose_bones:
            if bone.name not in bone_binds:
                continue
            params = bone_binds[bone.name]
            parent = params[0]
            copy_loc = params[1]
            copy_rot = params[2]

            if copy_loc:
                con = bone.constraints.new('COPY_LOCATION')
                con.name = con.name + "-mocap"
                con.target = copy_org
                con.subtarget = parent
            if copy_rot:
                con = bone.constraints.new('COPY_ROTATION')
                con.name = con.name + "-mocap"
                con.target = copy_org
                con.subtarget = parent


        # find Torso tweak bones (spine_fk)
        bpy.context.object.data.collections_all["Torso (Tweak)"].is_solo = True
        bpy.ops.pose.select_all(action='SELECT')
        spine_fk = []
        for bone in context.selected_pose_bones:
            if bone.name.startswith("spine_fk"):
                print(f"found - {bone.name}")
                spine_fk.append(bone)
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        # copy.select_set(True)
        copy_org.select_set(True)
        bpy.context.view_layer.objects.active = copy_org

        # Find chest bones of copy_org for later attachments
        bpy.ops.object.mode_set(mode='POSE')
        bpy.context.object.data.collections_all["ORG-mocap"].is_solo = True
        bpy.ops.pose.select_all(action='SELECT')
        center_bones = find_centered_bones(context.selected_pose_bones)
        bpy.context.object.data.collections_all["ORG-mocap"].is_solo = False
        # print("Center bones")
        # for bone in center_bones:
        #     print(bone.name)

        # Get spine_fk on the screen
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        copy.select_set(True)
        bpy.context.view_layer.objects.active = copy

        bpy.ops.object.mode_set(mode='POSE')
        bpy.ops.pose.select_all(action='DESELECT')
        
        # Now attaching
        for pose_bone in spine_fk:
            bone = pose_bone.bone
            pose_bone.select = True
            for center_pose_bone in center_bones:
                center_bone = center_pose_bone.bone
                if (bone.head_local - center_bone.tail_local).length <= 0.0001:
                    con = pose_bone.constraints.new('COPY_ROTATION')
                    con.name = con.name + "-mocap"
                    con.target = copy_org
                    con.subtarget = center_bone.name

        bpy.context.object.data.collections_all["Torso (Tweak)"].is_solo = False

        # The spine_fk chain stops at the chest, so nothing above it followed
        # the mocap and the head stayed rigid on the torso. The head control
        # sits exactly on the last ORG spine bone, so a world copy is exact.
        neck_org, head_org = mapping.neck_and_head(copy_org, props)
        for control_name, org_name in (
            (props.usr_neck, neck_org),
            (props.usr_head, head_org),
        ):
            pose_bone = copy.pose.bones.get(control_name)
            if pose_bone is None or not org_name:
                continue
            if org_name not in copy_org.data.bones:
                continue
            con = pose_bone.constraints.new('COPY_ROTATION')
            con.name = con.name + "-mocap"
            con.target = copy_org
            con.subtarget = org_name



        bpy.context.object.data.collections_all["MCH"].is_visible = False
        bpy.ops.object.mode_set(mode='OBJECT')
        self.report({'INFO'}, f"Copied the rig")
        return {'FINISHED'}
    

class Rigify_utils_Copy_rig3(bpy.types.Operator):
    """Attach original rig to its copy"""
    bl_idname = "rigify_utils.copy_rig3"
    bl_label = "Copy rigify rig3"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        bpy.ops.object.mode_set(mode='OBJECT')

        if len(context.selected_objects) < 2:
            self.report({'ERROR'}, "Select two armatures, one is original rig, other is its untouched copy")
            return {'CANCELLED'}
        
        
        orig = context.selected_objects[0]
        copy_org = context.selected_objects[1]
        if is_driver_copy(orig):
            orig, copy_org = copy_org, orig

        # grab pose bones
        bpy.ops.object.select_all(action='DESELECT')
        orig.select_set(True)
        bpy.context.view_layer.objects.active = orig

        # Drop a previous binding first. This runs on the user's own rig, so
        # without it a second bind stacks another full set of constraints on
        # every bone and the pose doubles up.
        for pose_bone in orig.pose.bones:
            for con in list(pose_bone.constraints):
                if con.name.endswith(CONTROL_SUFFIX):
                    pose_bone.constraints.remove(con)

        # Iterating over bones. Not via pose.select_all: that only picks up
        # bones in visible collections, so whichever collections happened to
        # be open decided how much of the rig followed the mocap. spine_fk
        # lives in a collection that is closed by default, which is why the
        # chest and head used to lag behind the torso.
        bpy.ops.object.posemode_toggle(True)
        props = context.scene.my_addon_props
        ikbones = [props.usr_torso, props.usr_hand_l, props.usr_hand_r, props.usr_foot_l, props.usr_foot_r]
        for pose_bone in control_bones(orig):
            con = pose_bone.constraints.new('COPY_ROTATION')
            con.name = con.name + CONTROL_SUFFIX
            con.target = copy_org
            con.subtarget = pose_bone.name
            # con.target_space = 'LOCAL_OWNER_ORIENT'
            # con.target_space = 'LOCAL_WITH_PARENT'
            # con.owner_space = 'LOCAL_WITH_PARENT'
            con.target_space = 'LOCAL'
            con.owner_space = 'LOCAL'
            con.influence = 1.0
            con.mix_mode = 'AFTER'

            for ikbone in ikbones:
                if ikbone == pose_bone.name:
                    # cuz these bones require target's local rotation to be modified directly via constrain
                    con.target_space = 'LOCAL_WITH_PARENT'
                    con.owner_space = 'LOCAL_WITH_PARENT'

                    con = pose_bone.constraints.new('COPY_LOCATION')
                    con.name = con.name + CONTROL_SUFFIX
                    con.target = copy_org
                    con.subtarget = pose_bone.name

                    # setattr(con, "target_space", 'LOCAL_OWNER_ORIENT')
                    con.target_space = 'LOCAL_WITH_PARENT'
                    con.owner_space = 'LOCAL_WITH_PARENT'
                    # con.target_space = 'LOCAL_OWNER_ORIENT'
                    # con.owner_space = 'LOCAL'
                    con.influence = 1.0
                    con.use_offset = True # allows moving around

        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        orig.select_set(True)
        copy_org.select_set(True)
        bpy.context.view_layer.objects.active = orig
        self.report({'INFO'}, f"Copied the rig")
        return {'FINISHED'}

class Rigify_utils_Detect_mocap_bones(bpy.types.Operator):
    """Fill the mocap bone names from the selected mocap armature"""
    bl_idname = "rigify_utils.detect_mocap_bones"
    bl_label = "Detect Mocap Bones"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        candidates = [
            obj for obj in context.selected_objects
            if obj.type == 'ARMATURE' and not is_org_copy(obj)
            and not is_driver_copy(obj) and not is_original_rigify(obj)
        ]
        if not candidates:
            self.report({'ERROR'}, "Select the mocap armature")
            return {'CANCELLED'}

        mocap = candidates[0]
        resolved = mapping.detect_mocap_bones(mocap)
        store_mocap_map(context.scene.my_addon_props, resolved)

        missing = mapping.unresolved_slots(resolved)
        if missing:
            self.report(
                {'WARNING'},
                f"{len(resolved)} bones detected on {mocap.name}, "
                f"not found: {', '.join(missing)}",
            )
        else:
            self.report({'INFO'}, f"All {len(resolved)} bones detected on {mocap.name}")
        return {'FINISHED'}


class Rigify_utils_Copy_rig4(bpy.types.Operator):
    """Creates bindings from Mocap to Copy. Select Copy-mch-org, then mocap"""
    bl_idname = "rigify_utils.copy_rig4"
    bl_label = "Copy rigify rig4"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        armatures = [obj for obj in context.selected_objects if obj.type == 'ARMATURE']
        if len(armatures) < 2:
            self.report({'ERROR'}, "Select two armatures, one is Rigify copy, other is mocap")
            return {'CANCELLED'}
        bpy.ops.object.mode_set(mode='OBJECT')

        # Identify by role, not by selection order. The ORG collection was
        # renamed to ORG-mocap back in step 1, so looking for "ORG" here used
        # to miss on both objects and pick whichever came first.
        copies = [obj for obj in armatures if is_org_copy(obj)]
        mocaps = [obj for obj in armatures if not is_org_copy(obj)]
        if len(copies) != 1 or not mocaps:
            self.report({'ERROR'}, "Select exactly one ORG/MCH copy and one mocap armature")
            return {'CANCELLED'}
        copy = copies[0]
        mocap = mocaps[0]

        props = context.scene.my_addon_props
        mocap_map = resolve_mocap_map(context, mocap)
        if "hips" not in mocap_map:
            self.report(
                {'ERROR'},
                f"Could not identify the hips bone of {mocap.name}. "
                "Fill it in under Bone Mapping > Mocap Bones.",
            )
            return {'CANCELLED'}
        store_mocap_map(props, mocap_map)

        pairs = mapping.build_bone_pairs(copy, mocap, props, mocap_map)
        if not pairs:
            self.report({'ERROR'}, "No bone pairs could be resolved")
            return {'CANCELLED'}

        clear_mocap_binding(context, copy)
        create_retarget_proxies(
            context, copy, mocap, pairs, mapping.limb_org_bones(copy, props)
        )
        count = bind_proxies_to_mocap(copy, mocap, pairs)

        hips_org = mapping.spine_chain(copy, props.org_spine)
        if hips_org:
            bind_hips_location(
                copy, mocap, hips_org[0], mocap_map["hips"],
                props.hip_translation_scale,
            )

        bpy.ops.object.mode_set(mode='OBJECT')

        missing = mapping.unresolved_slots(mocap_map)
        if missing:
            self.report(
                {'WARNING'},
                f"{count} bindings added, no mocap bone for: {', '.join(missing)}",
            )
        else:
            self.report({'INFO'}, f"{count} bindings added")
        return {'FINISHED'}


class Rigify_utils_Bind_rigify_to_mocap(bpy.types.Operator):
    """Run all four binding steps for a selected Rigify and Mocap pair"""
    bl_idname = "rigify_utils.bind_rigify_to_mocap"
    bl_label = "Bind Rigify to Mocap"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        selected = list(context.selected_objects)
        armatures = [obj for obj in selected if obj.type == 'ARMATURE']
        if len(selected) != 2 or len(armatures) != 2:
            self.report({'ERROR'}, "Select exactly two armatures: Rigify and Mocap")
            return {'CANCELLED'}

        rigify_candidates = [obj for obj in armatures if is_original_rigify(obj)]
        mocap_candidates = [obj for obj in armatures if is_mocap_armature(obj)]
        if len(rigify_candidates) != 1 or len(mocap_candidates) != 1:
            self.report({'ERROR'}, "Could not identify one Rigify rig and one Mocap rig")
            return {'CANCELLED'}

        rigify = rigify_candidates[0]
        mocap = mocap_candidates[0]
        if rigify == mocap:
            self.report({'ERROR'}, "Rigify and Mocap must be different armatures")
            return {'CANCELLED'}

        try:
            org_copy = bind_step1(context, rigify)
            driver_copy = bind_step2(context, rigify, org_copy)
            bind_step3(context, rigify, driver_copy)
            bind_step4(context, org_copy, mocap)
        except Exception as error:
            self.report({'ERROR'}, f"Binding failed: {error}")
            return {'CANCELLED'}

        _select_objects(context, (rigify, mocap), rigify)
        self.report({'INFO'}, "Rigify successfully bound to Mocap")
        return {'FINISHED'}



_MOCAP_DESC = "Bone on the mocap armature. Leave empty to auto-detect"


# Bones
class MyAddonProperties(bpy.types.PropertyGroup):
    my_text: bpy.props.StringProperty(
        name="Text Input",
        description="Enter some text here",
        default="torso"
    )

    # user controlled bones
    usr_torso: bpy.props.StringProperty(
        name="torso",
        description="User controlled bone",
        default="torso"
    )
    usr_hand_l: bpy.props.StringProperty(
        name="hand_ik.L",
        description="User controlled bone",
        default="hand_ik.L"
    )
    usr_hand_r: bpy.props.StringProperty(
        name="hand_ik.R",
        description="User controlled bone",
        default="hand_ik.R"
    )
    usr_foot_l: bpy.props.StringProperty(
        name="Foot IK L",
        description="User controlled bone",
        default="foot_ik.L"
    )
    usr_foot_r: bpy.props.StringProperty(
        name="Foot IK R",
        description="User controlled bone",
        default="foot_ik.R"
    )
    usr_neck: bpy.props.StringProperty(
        name="neck",
        description="User controlled bone",
        default="neck"
    )
    usr_head: bpy.props.StringProperty(
        name="head",
        description="User controlled bone",
        default="head"
    )






    mch_torso: bpy.props.StringProperty(
        name="MCH Torso",
        description="Torso mch bone name",
        default="MCH-torso.parent"
    )
    mch_hand_l: bpy.props.StringProperty(
        name="MCH Hand L",
        description="MCH bone name",
        default="MCH-hand_ik.parent.L"
    )

    mch_hand_r: bpy.props.StringProperty(
        name="MCH Hand R",
        description="MCH bone name",
        default="MCH-hand_ik.parent.R"
    )

    mch_foot_l: bpy.props.StringProperty(
        name="MCH Foot L",
        description="MCH bone name",
        default="MCH-foot_ik.parent.L"
    )

    mch_foot_r: bpy.props.StringProperty(
        name="MCH Foot R",
        description="MCH bone name",
        default="MCH-foot_ik.parent.R"
    )




    org_spine: bpy.props.StringProperty(
        name="ORG-spine",
        description="ORG Bones",
        default="ORG-spine"
    )
    org_hand_l: bpy.props.StringProperty(
        name="ORG-hand.L",
        description="ORG Bones",
        default="ORG-hand.L"
    )
    org_hand_r: bpy.props.StringProperty(
        name="ORG-hand.R",
        description="ORG Bones",
        default="ORG-hand.R"
    )
    org_foot_l: bpy.props.StringProperty(
        name="ORG-foot.L",
        description="ORG Bones",
        default="ORG-foot.L"
    )
    org_foot_r: bpy.props.StringProperty(
        name="ORG-foot.R",
        description="ORG Bones",
        default="ORG-foot.R"
    )




    org_shoulder_r: bpy.props.StringProperty(
        name="ORG-shoulder.R",
        description="ORG Bones",
        default="ORG-shoulder.R"
    )
    org_upper_arm_r: bpy.props.StringProperty(
        name="ORG-upper_arm.R",
        description="ORG Bones",
        default="ORG-upper_arm.R"
    )
    org_forearm_r: bpy.props.StringProperty(
        name="ORG-forearm.R",
        description="ORG Bones",
        default="ORG-forearm.R"
    )
    org_thigh_r: bpy.props.StringProperty(
        name="ORG-thigh.R",
        description="ORG Bones",
        default="ORG-thigh.R"
    )
    org_shin_r: bpy.props.StringProperty(
        name="ORG-shin.R",
        description="ORG Bones",
        default="ORG-shin.R"
    )
    org_toe_r: bpy.props.StringProperty(
        name="ORG-toe.R",
        description="ORG Bones",
        default="ORG-toe.R"
    )


    org_shoulder_l: bpy.props.StringProperty(
        name="ORG-shoulder.L",
        description="ORG Bones",
        default="ORG-shoulder.L"
    )
    org_upper_arm_l: bpy.props.StringProperty(
        name="ORG-upper_arm.L",
        description="ORG Bones",
        default="ORG-upper_arm.L"
    )
    org_forearm_l: bpy.props.StringProperty(
        name="ORG-forearm.L",
        description="ORG Bones",
        default="ORG-forearm.L"
    )
    org_thigh_l: bpy.props.StringProperty(
        name="ORG-thigh.L",
        description="ORG Bones",
        default="ORG-thigh.L"
    )
    org_shin_l: bpy.props.StringProperty(
        name="ORG-shin.L",
        description="ORG Bones",
        default="ORG-shin.L"
    )
    org_toe_l: bpy.props.StringProperty(
        name="ORG-toe.L",
        description="ORG Bones",
        default="ORG-toe.L"
    )




    # Mocap side. Left empty these are filled by auto-detection at bind time;
    # type a bone name to override a slot the detector got wrong or missed.
    mocap_hips: bpy.props.StringProperty(name="Hips", description=_MOCAP_DESC, default="")
    mocap_spine: bpy.props.StringProperty(name="Spine", description=_MOCAP_DESC, default="")
    mocap_chest: bpy.props.StringProperty(name="Chest", description=_MOCAP_DESC, default="")
    mocap_upper_chest: bpy.props.StringProperty(name="Upper Chest", description=_MOCAP_DESC, default="")
    mocap_neck: bpy.props.StringProperty(name="Neck", description=_MOCAP_DESC, default="")
    mocap_head: bpy.props.StringProperty(name="Head", description=_MOCAP_DESC, default="")

    mocap_shoulder_l: bpy.props.StringProperty(name="Shoulder L", description=_MOCAP_DESC, default="")
    mocap_upper_arm_l: bpy.props.StringProperty(name="Upper Arm L", description=_MOCAP_DESC, default="")
    mocap_forearm_l: bpy.props.StringProperty(name="Forearm L", description=_MOCAP_DESC, default="")
    mocap_hand_l: bpy.props.StringProperty(name="Hand L", description=_MOCAP_DESC, default="")

    mocap_shoulder_r: bpy.props.StringProperty(name="Shoulder R", description=_MOCAP_DESC, default="")
    mocap_upper_arm_r: bpy.props.StringProperty(name="Upper Arm R", description=_MOCAP_DESC, default="")
    mocap_forearm_r: bpy.props.StringProperty(name="Forearm R", description=_MOCAP_DESC, default="")
    mocap_hand_r: bpy.props.StringProperty(name="Hand R", description=_MOCAP_DESC, default="")

    mocap_thigh_l: bpy.props.StringProperty(name="Thigh L", description=_MOCAP_DESC, default="")
    mocap_shin_l: bpy.props.StringProperty(name="Shin L", description=_MOCAP_DESC, default="")
    mocap_foot_l: bpy.props.StringProperty(name="Foot L", description=_MOCAP_DESC, default="")
    mocap_toe_l: bpy.props.StringProperty(name="Toe L", description=_MOCAP_DESC, default="")

    mocap_thigh_r: bpy.props.StringProperty(name="Thigh R", description=_MOCAP_DESC, default="")
    mocap_shin_r: bpy.props.StringProperty(name="Shin R", description=_MOCAP_DESC, default="")
    mocap_foot_r: bpy.props.StringProperty(name="Foot R", description=_MOCAP_DESC, default="")
    mocap_toe_r: bpy.props.StringProperty(name="Toe R", description=_MOCAP_DESC, default="")

    # Step 1 option: repair DEF bones parented to ORG bones on the original
    # rig, applied right after the ORG/MCH copy is created.
    fix_def_parents: bpy.props.BoolProperty(
        name="Fix DEF Parents",
        description=(
            "After creating the ORG/MCH copy, re-parent DEF bones that hang "
            "under an ORG bone onto the DEF bone that ORG bone is parented to"
        ),
        default=False,
    )

    hip_translation_scale: bpy.props.FloatProperty(
        name="Hip Translation Scale",
        description=(
            "Multiplier on the mocap's root travel. Raise it when the mocap "
            "character is smaller than the Rigify one and the steps fall short"
        ),
        default=1.0,
        min=0.0,
        soft_max=2.0,
    )
