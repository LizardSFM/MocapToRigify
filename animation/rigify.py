# For mocap. Copy rig, leave only ORG, reparent them. 

import bpy
from bpy.props import StringProperty


GENERATED_ROLE_KEY = "mocap_to_rigify_role"
ROLE_COPY_ORG_MCH = "copy_org_mch"
ROLE_DRIVER_COPY = "driver_copy"
CONSTRAINT_ROTATION_NAME = "MocapToRigify Rotation"
CONSTRAINT_HIPS_LOCATION_NAME = "MocapToRigify Hips Location"
CONSTRAINT_DRIVER_ROTATION_NAME = "MocapToRigify Driver Rotation"
CONSTRAINT_DRIVER_LOCATION_NAME = "MocapToRigify Driver Location"


def has_bone_collection(obj, collection_name):
    return obj.type == 'ARMATURE' and obj.data.collections_all.find(collection_name) != -1


def selected_armatures(context, expected_count=2):
    selected = list(context.selected_objects)
    armatures = [obj for obj in selected if obj.type == 'ARMATURE']
    if len(selected) != expected_count or len(armatures) != expected_count:
        return None
    return armatures


def identify_mocap_and_copy(context):
    armatures = selected_armatures(context)
    if armatures is None:
        return None, None, "Select exactly two armatures: the ORG/MCH copy and the Mocap rig"

    copy_candidates = [
        obj for obj in armatures
        if obj.get(GENERATED_ROLE_KEY) == ROLE_COPY_ORG_MCH
        or has_bone_collection(obj, "ORG-mocap")
    ]
    if len(copy_candidates) != 1:
        return None, None, "Could not identify one Rigify *-copy-org-mch armature"

    copy = copy_candidates[0]
    mocap = armatures[0] if armatures[1] == copy else armatures[1]
    if "Hips" not in mocap.pose.bones:
        return None, None, f"{mocap.name} is missing the Mocap Fusion Hips bone"

    return copy, mocap, None


def identify_original_and_copy(context):
    armatures = selected_armatures(context)
    if armatures is None:
        return None, None, "Select exactly two armatures: the original Rigify rig and its ORG/MCH copy"

    copy_candidates = [
        obj for obj in armatures
        if obj.get(GENERATED_ROLE_KEY) == ROLE_COPY_ORG_MCH
        or has_bone_collection(obj, "ORG-mocap")
    ]
    if len(copy_candidates) != 1:
        return None, None, "Could not identify one Rigify ORG/MCH copy"

    copy = copy_candidates[0]
    original = armatures[0] if armatures[1] == copy else armatures[1]
    if not has_bone_collection(original, "Torso (Tweak)"):
        return None, None, f"{original.name} is not a generated Rigify armature"

    return original, copy, None


def identify_original_and_driver(context):
    armatures = selected_armatures(context)
    if armatures is None:
        return None, None, "Select exactly two armatures: the original Rigify rig and its driver copy"

    driver_candidates = [
        obj for obj in armatures
        if obj.get(GENERATED_ROLE_KEY) == ROLE_DRIVER_COPY
    ]
    if not driver_candidates:
        driver_candidates = [
            obj for obj in armatures
            if obj.name.endswith("-copy") or "-copy." in obj.name
        ]
    if len(driver_candidates) != 1:
        return None, None, "Could not identify one Rigify driver copy"

    driver = driver_candidates[0]
    original = armatures[0] if armatures[1] == driver else armatures[1]
    if not has_bone_collection(original, "Torso (Tweak)"):
        return None, None, f"{original.name} is not the original generated Rigify armature"

    return original, driver, None


def remove_pose_bone_constraints(pose_bone):
    for constraint in list(pose_bone.constraints):
        pose_bone.constraints.remove(constraint)


def remove_driver_constraints(pose_bone, include_current_names=True):
    current_names = {
        CONSTRAINT_DRIVER_ROTATION_NAME,
        CONSTRAINT_DRIVER_LOCATION_NAME,
    }
    for constraint in list(pose_bone.constraints):
        is_legacy = constraint.name.endswith("-mocap2")
        is_current = include_current_names and constraint.name in current_names
        if is_legacy or is_current:
            pose_bone.constraints.remove(constraint)


def replace_target_constraint(pose_bone, constraint_type, name, target, subtarget):
    matches = [
        constraint for constraint in pose_bone.constraints
        if constraint.name == name
        or (
            constraint.type == constraint_type
            and getattr(constraint, "target", None) == target
        )
    ]

    constraint = None
    for candidate in matches:
        if constraint is None and candidate.type == constraint_type:
            constraint = candidate
            continue
        pose_bone.constraints.remove(candidate)

    if constraint is None:
        constraint = pose_bone.constraints.new(constraint_type)

    constraint.name = name
    constraint.target = target
    constraint.subtarget = subtarget
    constraint.influence = 1.0
    constraint.mute = False
    return constraint


def rigify_spine_chain(obj, root_name):
    root = obj.data.bones.get(root_name)
    if root is None:
        return []

    chain = [root]
    current = root
    while True:
        children = [
            child for child in current.children
            if child.name.startswith(f"{root_name}.")
        ]
        if len(children) != 1:
            break
        current = children[0]
        chain.append(current)
    return chain


def mocap_spine_chain(obj, root_name="Hips"):
    root = obj.data.bones.get(root_name)
    if root is None:
        return []

    chain = [root]
    current = root
    while True:
        children = [
            child for child in current.children
            if abs(child.head_local.x) < 0.001
            and abs(child.tail_local.x) < 0.001
            and not child.name.lower().endswith(("_end", ".end"))
        ]
        if len(children) != 1:
            break
        current = children[0]
        chain.append(current)
    return chain


def normalized_chain_midpoints(chain):
    lengths = [max(float(bone.length), 1e-8) for bone in chain]
    total_length = sum(lengths)
    distance = 0.0
    midpoints = []
    for length in lengths:
        midpoints.append((distance + length * 0.5) / total_length)
        distance += length
    return midpoints


def pair_spine_chains(rigify_chain, mocap_chain):
    if not rigify_chain or not mocap_chain:
        return []

    rigify_positions = normalized_chain_midpoints(rigify_chain)
    mocap_positions = normalized_chain_midpoints(mocap_chain)
    pairs = []
    for rigify_bone, position in zip(rigify_chain, rigify_positions):
        index = min(
            range(len(mocap_chain)),
            key=lambda candidate: abs(mocap_positions[candidate] - position),
        )
        pairs.append((rigify_bone.name, mocap_chain[index].name))
    return pairs


# from mathutils import Vector, geometry
class BONECONSTRAINTS_test(bpy.types.Operator):
    """Just test for debug"""
    bl_idname = "boneconstraints.test"
    bl_label = "Test"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        return {'FINISHED'}  
    
class BONECONSTRAINTS_OT_Copy_rig(bpy.types.Operator):
    """Copy rigify rig, leave only ORG BONES"""
    bl_idname = "boneconstraints.copy_rig"
    bl_label = "Copy rigify rig"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        bpy.ops.object.mode_set(mode='OBJECT')
        obj = context.active_object
        # obj = context.object
        if obj is None or obj.type != "ARMATURE":
            self.report({'ERROR'}, "Select an armature in Pose Mode")
            return {'CANCELLED'}
        
        bpy.ops.object.duplicate()
        obj = context.active_object

        
        # Cut ORG out as new armature
        org_id = obj.data.collections_all.find("ORG")
        obj.data.collections_all[org_id].is_solo = True
        col = obj.data.collections[org_id]
        bpy.ops.object.editmode_toggle(True)
        # Move feet MCH to ORG for proper retargeting of feet later
        obj.data.collections[org_id].assign(obj.data.edit_bones["MCH-foot_ik.parent.L"])
        obj.data.collections[org_id].assign(obj.data.edit_bones["MCH-foot_ik.parent.R"])
        obj.data.collections["MCH"].unassign(obj.data.edit_bones["MCH-foot_ik.parent.L"])
        obj.data.collections["MCH"].unassign(obj.data.edit_bones["MCH-foot_ik.parent.R"])
        
        obj.data.edit_bones["MCH-foot_ik.parent.L"].parent = obj.data.edit_bones["ORG-foot.L"]
        obj.data.edit_bones["MCH-foot_ik.parent.R"].parent = obj.data.edit_bones["ORG-foot.R"]
        
        # Not needed
        # obj.data.edit_bones.remove(obj.data.edit_bones["ORG-breast.L"])
        # obj.data.edit_bones.remove(obj.data.edit_bones["ORG-breast.R"])
        obj.data.edit_bones.remove(obj.data.edit_bones["ORG-pelvis.L"])
        obj.data.edit_bones.remove(obj.data.edit_bones["ORG-pelvis.R"])

        bpy.ops.armature.select_all(action='SELECT')
        bpy.ops.armature.separate()
        bpy.ops.object.editmode_toggle(False)
        
        # org_rig = bpy.context.selected_objects[1]
        bpy.data.objects.remove(context.active_object, do_unlink=True)
        bpy.context.view_layer.objects.active = bpy.context.selected_objects[0]

        # Make ORG visible
        bpy.ops.armature.collection_remove_unused()
        for i, collection in enumerate(context.active_object.data.collections):
            collection.is_visible = True
            collection.is_solo = False
        
        # Clear constrains and Locks
        bpy.ops.object.posemode_toggle(True)
        for pose_bone in context.active_object.pose.bones:
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
        edit_bones = context.active_object.data.edit_bones
        center_bones = []
        for edit_bone in edit_bones:
            if abs(edit_bone.head.x) < 0.001 and abs(edit_bone.tail.x) < 0.001:
                center_bones.append(edit_bone)
        # AI Sort bones by their Z position (assuming spine runs vertically) 
        center_bones.sort(key=lambda bone: bone.head.z)

        # Reparent
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
                next_bone.use_connect = True
                print(f"Parented '{next_bone.name}' to '{current_bone.name}'")
            else:
                print(f"Warning: '{next_bone.name}' head doesn't match '{current_bone.name}' tail position")
            # bpy.context.active_bone.parent = bpy.data.armatures["rig.012"].edit_bones["ORG-pelvis.L"]
        
        # Specific finger parenting
        edit_bones["ORG-thumb.01.R"].parent = edit_bones["ORG-hand.R"]
        edit_bones["ORG-palm.01.R"].parent = edit_bones["ORG-hand.R"]
        edit_bones["ORG-palm.02.R"].parent = edit_bones["ORG-hand.R"]
        edit_bones["ORG-palm.03.R"].parent = edit_bones["ORG-hand.R"]
        edit_bones["ORG-palm.04.R"].parent = edit_bones["ORG-hand.R"]

        edit_bones["ORG-thumb.01.L"].parent = edit_bones["ORG-hand.L"]
        edit_bones["ORG-palm.01.L"].parent = edit_bones["ORG-hand.L"]
        edit_bones["ORG-palm.02.L"].parent = edit_bones["ORG-hand.L"]
        edit_bones["ORG-palm.03.L"].parent = edit_bones["ORG-hand.L"]
        edit_bones["ORG-palm.04.L"].parent = edit_bones["ORG-hand.L"]
        bpy.ops.object.editmode_toggle(False)
        
        




        # # Making all bones except ORG visible
        # for i, collection in enumerate(obj.data.collections):
        #     collection.is_visible = True

        #     if collection.name == "ORG": collection.is_solo = False
        #     else: collection.is_solo = True

        # # Remove unused bones
        # bpy.ops.object.editmode_toggle(True)
        # bpy.ops.armature.select_all(action='SELECT')
        # bpy.ops.armature.delete()
        # bpy.ops.object.editmode_toggle(False)

        # # Remove solo
        # for i, collection in enumerate(obj.data.collections):
        #     collection.is_visible = True
        #     collection.is_solo = False

        # bpy.ops.armature.collection_remove_unused()





        # bpy.ops.object.editmode_toggle(False)
        self.report({'INFO'}, f"Copied the rig")
        return {'FINISHED'}

class BONECONSTRAINTS_OT_Copy_to_mocap_constrains(bpy.types.Operator):
    """Creates bindings from Mocap to Copy. Select Copy of Rigify, then mocap, """
    bl_idname = "boneconstraints.copy_to_mocap_constr"
    bl_label = "Mocap/copy bind"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if len(context.selected_objects) < 2:
            self.report({'ERROR'}, "Select two armatures, one is Rigify copy, other is mocap")
            return {'CANCELLED'}
        bpy.ops.object.mode_set(mode='OBJECT')
        
        copy = context.selected_objects[0]
        mocap = context.selected_objects[1]
        id = copy.data.collections_all.find("ORG")
        if copy.data.collections_all.find("ORG") == -1:
            copy = context.selected_objects[1]
            mocap = context.selected_objects[0]

        # Setting constrains
        bpy.ops.object.posemode_toggle(True)
        bpy.ops.pose.select_all(action='DESELECT')
        # Select all bones in the first rig
        for bone in copy.pose.bones:
            bone.select = True

        bone_binds = {
            "ORG-shoulder.R" : "RightShoulder",
            "ORG-upper_arm.R" : "RightArm",
            "ORG-forearm.R" : "RightForeArm",
            "ORG-hand.R" : "RightHand",
            "ORG-thigh.R" : "RightUpLeg",
            "ORG-shin.R" : "RightLeg",
            "ORG-foot.R" : "RightFoot",
            "ORG-toe.R" : "RightToeBase",

            "ORG-shoulder.L" : "LeftShoulder",
            "ORG-upper_arm.L" : "LeftArm",
            "ORG-forearm.L" : "LeftForeArm",
            "ORG-hand.L" : "LeftHand",
            "ORG-thigh.L" : "LeftUpLeg",
            "ORG-shin.L" : "LeftLeg",
            "ORG-foot.L" : "LeftFoot",
            "ORG-toe.L" : "LeftToeBase",

            "" : "",
            "" : "",
            "" : "",
            "" : "",
            "" : "",
            "" : "",
            "" : "",
            "" : "",
        }
        count = 0
        for bone in context.selected_pose_bones:
            if bone.name not in bone_binds:
                continue
            con = bone.constraints.new('COPY_ROTATION')
            con.target = mocap
            con.subtarget = bone_binds[bone.name]

            ## Local doesn't really work if rigify bones aren't straight
            # setattr(con, "target_space", 'LOCAL_OWNER_ORIENT')
            # con.target_space = 'LOCAL_OWNER_ORIENT'
            # con.owner_space = 'LOCAL'
            # con.influence = 1.0
            # con.mix_mode = 'AFTER'
            
            print(con)
            count += 1

        # Hips location bind
        for bone in context.selected_pose_bones:
            if bone.name != "ORG-spine":
                continue
            con = bone.constraints.new('COPY_LOCATION')
            con.target = mocap
            con.subtarget = "Hips"

            # setattr(con, "target_space", 'LOCAL_OWNER_ORIENT')
            con.target_space = 'LOCAL_OWNER_ORIENT'
            con.owner_space = 'LOCAL'
            con.influence = 1.0
            con.use_offset = True # allows moving around

        bpy.ops.object.mode_set(mode='OBJECT')
        self.report({'INFO'}, f"{count} bindings added")
        return {'FINISHED'}

def find_centered_bones(bones):
    center_bones = []
    for bone in bones:
        if abs(bone.head.x) < 0.001 and abs(bone.tail.x) < 0.001:
            center_bones.append(bone)
    # AI Sort bones by their Z position (assuming spine runs vertically) 
    center_bones.sort(key=lambda bone: bone.head.z)
    return center_bones

def find_closest_bone(current_bone, other_bones):
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

# TODO: Ignore MCH-torso.parent from copy rotation
class Rigify_spine_retarget(bpy.types.Operator):
    """Find spine bones close to other rig's spine bones, and retarget"""
    bl_idname = "boneconstraints.rigify_spine_retarget"
    bl_label = "Spine retarget"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        if len(context.selected_objects) < 2:
            self.report({'ERROR'}, "Select two armatures, one is Rigify copy, other is mocap")
            return {'CANCELLED'}
        bpy.ops.object.mode_set(mode='OBJECT')
        
        copy = context.selected_objects[0]
        mocap = context.selected_objects[1]
        id = copy.data.collections_all.find("ORG")
        if copy.data.collections_all.find("ORG") == -1:
            copy = context.selected_objects[1]
            mocap = context.selected_objects[0]
        
        bpy.ops.object.editmode_toggle(True)
        # bpy.ops.object.mode_set(mode="EDIT")
        # bpy.context.view_layer.objects.active = mocap # not required
        bpy.ops.armature.select_all(action='SELECT')
        # Get center bones for copy rigify rig
        bones_copy = find_centered_bones(copy.data.edit_bones)
        bones_mocap = find_centered_bones(mocap.data.edit_bones)
        bones_pairs = {}
        for bone_copy in bones_copy:
            closest_bone, closest_dist = find_closest_bone(bone_copy, bones_mocap)
            bones_pairs[bone_copy.name] = [closest_bone.name, closest_dist]
            self.report({'INFO'}, f"{bone_copy.name} - Closest: {closest_bone.name}, dist: {closest_dist:.4f}")
        


        bpy.ops.object.posemode_toggle(True)
        bpy.ops.pose.select_all(action='DESELECT')
        # Select all bones in the first rig
        for bone in copy.pose.bones:
            if bone.name in bones_pairs:
                bone.select = True
        
        for bone in context.selected_pose_bones:
        # for bone, pair in bones_pairs.items():
            con = bone.constraints.new('COPY_ROTATION')
            con.target = mocap
            con.subtarget = bones_pairs[bone.name][0]

            # copypaste
            ## Local doesn't really work if rigify bones aren't straight
            # setattr(con, "target_space", 'LOCAL_OWNER_ORIENT')
            # con.target_space = 'LOCAL_OWNER_ORIENT'
            # con.owner_space = 'LOCAL'
            # con.influence = 1.0
            # con.mix_mode = 'AFTER'
            
        bpy.ops.object.mode_set(mode='OBJECT')
        return {'FINISHED'}

## REWORK 
## TODO: Implement menu for manual input of bones (feet, hand IK, torso, neck etc)
# if rigify rig was customized and bone names changed
## TODO: neck bone 1 instead of 2
## TODO: clear constrains when copying, and back to pose position
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
            remove_pose_bone_constraints(pose_bone)
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
        obj[GENERATED_ROLE_KEY] = ROLE_COPY_ORG_MCH
        orig_obj.select_set(True)
        self.report({'INFO'}, f"Copied the rig")
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

        orig, copy_org, error = identify_original_and_copy(context)
        if error:
            self.report({'ERROR'}, error)
            return {'CANCELLED'}
        
        # Duplicate rigify rig for attaching to copy-org-mch
        bpy.ops.object.select_all(action='DESELECT')
        orig.select_set(True)
        bpy.context.view_layer.objects.active = orig
        bpy.ops.object.duplicate()

        copy = bpy.context.active_object
        copy.name = orig.name + "-copy"
        copy[GENERATED_ROLE_KEY] = ROLE_DRIVER_COPY
        for pose_bone in copy.pose.bones:
            remove_driver_constraints(pose_bone)

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
            print(pose_bone, pose_bone.select)
            for center_pose_bone in center_bones:
                center_bone = center_pose_bone.bone
                if (bone.head_local - center_bone.tail_local).length <= 0.0001:
                    con = pose_bone.constraints.new('COPY_ROTATION')
                    con.name = con.name + "-mocap"
                    con.target = copy_org
                    con.subtarget = center_bone.name

        bpy.context.object.data.collections_all["Torso (Tweak)"].is_solo = False



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

        orig, copy_org, error = identify_original_and_driver(context)
        if error:
            self.report({'ERROR'}, error)
            return {'CANCELLED'}

        props = context.scene.my_addon_props
        ikbones = [props.usr_torso, props.usr_hand_l, props.usr_hand_r, props.usr_foot_l, props.usr_foot_r]
        for pose_bone in orig.pose.bones:
            remove_driver_constraints(pose_bone, include_current_names=False)
            con = replace_target_constraint(
                pose_bone,
                'COPY_ROTATION',
                CONSTRAINT_DRIVER_ROTATION_NAME,
                copy_org,
                pose_bone.name,
            )
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

                    con = replace_target_constraint(
                        pose_bone,
                        'COPY_LOCATION',
                        CONSTRAINT_DRIVER_LOCATION_NAME,
                        copy_org,
                        pose_bone.name,
                    )

                    # setattr(con, "target_space", 'LOCAL_OWNER_ORIENT')
                    con.target_space = 'LOCAL_WITH_PARENT'
                    con.owner_space = 'LOCAL_WITH_PARENT'
                    # con.target_space = 'LOCAL_OWNER_ORIENT'
                    # con.owner_space = 'LOCAL'
                    con.influence = 1.0
                    con.use_offset = True # allows moving around

        self.report({'INFO'}, f"Copied the rig")
        return {'FINISHED'}

# TODO: Create retarget from Mocap to Copy-org-mch
class Rigify_utils_Copy_rig4(bpy.types.Operator):
    """Creates bindings from Mocap to Copy. Select Copy-mch-org, then mocap"""
    bl_idname = "rigify_utils.copy_rig4"
    bl_label = "Copy rigify rig4"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        copy, mocap, error = identify_mocap_and_copy(context)
        if error:
            self.report({'ERROR'}, error)
            return {'CANCELLED'}

        props = context.scene.my_addon_props # Stored user inputs in UI
        bone_binds = [
            (props.org_shoulder_r, "RightShoulder"),
            (props.org_upper_arm_r, "RightArm"),
            (props.org_forearm_r, "RightForeArm"),
            (props.org_hand_r, "RightHand"),
            (props.org_thigh_r, "RightUpLeg"),
            (props.org_shin_r, "RightLeg"),
            (props.org_foot_r, "RightFoot"),
            (props.org_toe_r, "RightToeBase"),
            (props.org_shoulder_l, "LeftShoulder"),
            (props.org_upper_arm_l, "LeftArm"),
            (props.org_forearm_l, "LeftForeArm"),
            (props.org_hand_l, "LeftHand"),
            (props.org_thigh_l, "LeftUpLeg"),
            (props.org_shin_l, "LeftLeg"),
            (props.org_foot_l, "LeftFoot"),
            (props.org_toe_l, "LeftToeBase"),
        ]

        duplicate_owner_names = sorted({
            owner_name for owner_name, _ in bone_binds
            if sum(1 for candidate, _ in bone_binds if candidate == owner_name) > 1
        })
        missing_owner = sorted({
            owner_name for owner_name, _ in bone_binds
            if not owner_name or owner_name not in copy.pose.bones
        })
        missing_target = sorted({
            target_name for _, target_name in bone_binds
            if target_name not in mocap.pose.bones
        })
        if duplicate_owner_names or missing_owner or missing_target:
            details = []
            if duplicate_owner_names:
                details.append(f"duplicate Rigify fields: {', '.join(duplicate_owner_names)}")
            if missing_owner:
                details.append(f"missing on {copy.name}: {', '.join(missing_owner)}")
            if missing_target:
                details.append(f"missing on {mocap.name}: {', '.join(missing_target)}")
            self.report({'ERROR'}, "; ".join(details))
            return {'CANCELLED'}

        rigify_chain = rigify_spine_chain(copy, props.org_spine)
        mocap_chain = mocap_spine_chain(mocap)
        if len(rigify_chain) < 2 or len(mocap_chain) < 2:
            self.report({'ERROR'}, "Could not build Rigify and Mocap spine chains")
            return {'CANCELLED'}

        spine_pairs = pair_spine_chains(rigify_chain, mocap_chain)

        for owner_name, target_name in bone_binds:
            replace_target_constraint(
                copy.pose.bones[owner_name],
                'COPY_ROTATION',
                CONSTRAINT_ROTATION_NAME,
                mocap,
                target_name,
            )

        hips_bone = copy.pose.bones.get(props.org_spine)
        if hips_bone is None:
            self.report({'ERROR'}, f"Missing hips bone on {copy.name}: {props.org_spine}")
            return {'CANCELLED'}
        hips_location = replace_target_constraint(
            hips_bone,
            'COPY_LOCATION',
            CONSTRAINT_HIPS_LOCATION_NAME,
            mocap,
            "Hips",
        )
        hips_location.target_space = 'LOCAL_OWNER_ORIENT'
        hips_location.owner_space = 'LOCAL'
        hips_location.use_offset = True

        for owner_name, target_name in spine_pairs:
            replace_target_constraint(
                copy.pose.bones[owner_name],
                'COPY_ROTATION',
                CONSTRAINT_ROTATION_NAME,
                mocap,
                target_name,
            )

        copy[GENERATED_ROLE_KEY] = ROLE_COPY_ORG_MCH
        self.report(
            {'INFO'},
            f"Bound {len(bone_binds)} limbs and {len(spine_pairs)} spine bones from {mocap.name}",
        )
        return {'FINISHED'}



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
