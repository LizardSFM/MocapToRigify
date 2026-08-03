# For mocap. Copy rig, leave only ORG, reparent them. 

import bpy
from bpy.props import StringProperty


def resolve_subtarget(armature, candidates):
    """Given a bone name or list of candidate names, return the first one that
    exists in armature.pose.bones, else None. Accepts both old-style single
    strings and new-style lists of names so one binding table can target
    multiple mocap rigs (Mocap Fusion, VRM, etc.)."""
    if isinstance(candidates, str):
        candidates = [candidates]
    for name in candidates:
        if name and name in armature.pose.bones:
            return name
    return None


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
        for bone in copy.data.bones:
            bone.select = True

        bone_binds = {
            "ORG-shoulder.R" : ["RightShoulder", "J_Bip_R_Shoulder"],
            "ORG-upper_arm.R" : ["RightArm", "J_Bip_R_UpperArm"],
            "ORG-forearm.R" : ["RightForeArm", "J_Bip_R_LowerArm"],
            "ORG-hand.R" : ["RightHand", "J_Bip_R_Hand"],
            "ORG-thigh.R" : ["RightUpLeg", "J_Bip_R_UpperLeg"],
            "ORG-shin.R" : ["RightLeg", "J_Bip_R_LowerLeg"],
            "ORG-foot.R" : ["RightFoot", "J_Bip_R_Foot"],
            "ORG-toe.R" : ["RightToeBase", "J_Bip_R_ToeBase"],

            "ORG-shoulder.L" : ["LeftShoulder", "J_Bip_L_Shoulder"],
            "ORG-upper_arm.L" : ["LeftArm", "J_Bip_L_UpperArm"],
            "ORG-forearm.L" : ["LeftForeArm", "J_Bip_L_LowerArm"],
            "ORG-hand.L" : ["LeftHand", "J_Bip_L_Hand"],
            "ORG-thigh.L" : ["LeftUpLeg", "J_Bip_L_UpperLeg"],
            "ORG-shin.L" : ["LeftLeg", "J_Bip_L_LowerLeg"],
            "ORG-foot.L" : ["LeftFoot", "J_Bip_L_Foot"],
            "ORG-toe.L" : ["LeftToeBase", "J_Bip_L_ToeBase"],
            
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
        skipped = 0
        for bone in context.selected_pose_bones:
            if bone.name not in bone_binds:
                continue
            target_name = resolve_subtarget(mocap, bone_binds[bone.name])
            if target_name is None:
                skipped += 1
                continue
            con = bone.constraints.new('COPY_ROTATION')
            con.target = mocap
            con.subtarget = target_name

            ## Local doesn't really work if rigify bones aren't straight
            # setattr(con, "target_space", 'LOCAL_OWNER_ORIENT')
            # con.target_space = 'LOCAL_OWNER_ORIENT'
            # con.owner_space = 'LOCAL'
            # con.influence = 1.0
            # con.mix_mode = 'AFTER'
            
            print(con)
            count += 1
        if skipped:
            self.report({'WARNING'}, f"{skipped} bones had no matching mocap target")

        # Hips location bind
        hips_candidates = ["Hips", "J_Bip_Hips", "hips", "Hip"]
        hips_name = resolve_subtarget(mocap, hips_candidates)
        for bone in context.selected_pose_bones:
            if bone.name != "ORG-spine":
                continue
            if hips_name is None:
                self.report({'WARNING'}, "No 'Hips' bone found in mocap rig")
                break
            con = bone.constraints.new('COPY_LOCATION')
            con.target = mocap
            con.subtarget = hips_name

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
        for bone in copy.data.bones:
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
    """Run the existing Mocap-source operator with its expected object ordering."""
    _select_objects(context, (org_copy, mocap), org_copy)
    with context.temp_override(
        object=org_copy,
        active_object=org_copy,
        selected_objects=[mocap, org_copy],
        selected_editable_objects=[mocap, org_copy],
    ):
        result = bpy.ops.rigify_utils.copy_rig4()
    _run_binding_operator(result, "Step 4")


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

        if len(context.selected_objects) < 2:
            self.report({'ERROR'}, "Select two armatures, one is original rig, other is its untouched copy")
            return {'CANCELLED'}
        
        
        orig = context.selected_objects[0]
        copy_org = context.selected_objects[1]
        print(f"cond: {orig.name.endswith('-copy')}")
        if orig.name.endswith("-copy"):
            orig = context.selected_objects[1]
            copy_org = context.selected_objects[0]

        # grab pose bones
        bpy.ops.object.select_all(action='DESELECT')
        orig.select_set(True)
        bpy.context.view_layer.objects.active = orig

        # Iterating over bones
        bpy.ops.object.posemode_toggle(True)
        bpy.ops.pose.select_all(action='SELECT')
        props = context.scene.my_addon_props
        ikbones = [props.usr_torso, props.usr_hand_l, props.usr_hand_r, props.usr_foot_l, props.usr_foot_r]
        for pose_bone in context.selected_pose_bones:
            con = pose_bone.constraints.new('COPY_ROTATION')
            con.name = con.name + "-mocap2"
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
                    con.name = con.name + "-mocap2"
                    con.target = copy_org
                    con.subtarget = pose_bone.name

                    # setattr(con, "target_space", 'LOCAL_OWNER_ORIENT')
                    con.target_space = 'LOCAL_WITH_PARENT'
                    con.owner_space = 'LOCAL_WITH_PARENT'
                    # con.target_space = 'LOCAL_OWNER_ORIENT'
                    # con.owner_space = 'LOCAL'
                    con.influence = 1.0
                    con.use_offset = True # allows moving around

        # Damped Track constraints on the driver copy's IK bones,
        # pointing at the ORG bones on the *-copy-org-mch rig so elbows/knees
        # aim toward the mocap-driven child bones.
        copy_org_mch_name = copy_org.name.replace("-copy", "-copy-org-mch", 1)
        copy_org_mch = bpy.data.objects.get(copy_org_mch_name)
        if copy_org_mch is None:
            self.report({'WARNING'}, f"Damped Track: could not find '{copy_org_mch_name}'")
        else:
            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.object.select_all(action='DESELECT')
            copy_org.select_set(True)
            bpy.context.view_layer.objects.active = copy_org
            bpy.ops.object.posemode_toggle(True)

            damped_track_binds = {
                props.usr_upper_arm_r: props.org_forearm_r,
                props.usr_upper_arm_l: props.org_forearm_l,
                props.usr_thigh_r:     props.org_shin_r,
                props.usr_thigh_l:     props.org_shin_l,
            }
            for ik_bone_name, org_target_name in damped_track_binds.items():
                if not ik_bone_name or not org_target_name:
                    continue
                pbone = copy_org.pose.bones.get(ik_bone_name)
                if pbone is None:
                    self.report({'WARNING'}, f"Damped Track: '{ik_bone_name}' not found on {copy_org.name}")
                    continue
                con = pbone.constraints.new('DAMPED_TRACK')
                con.name = con.name + "-damped"
                con.target = copy_org_mch
                con.subtarget = org_target_name
                con.head_tail = 0.0
                con.track_axis = 'TRACK_NEGATIVE_Z'

        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        orig.select_set(True)
        copy_org.select_set(True)
        bpy.context.view_layer.objects.active = orig
        self.report({'INFO'}, f"Copied the rig")
        return {'FINISHED'}

# TODO: Create retarget from Mocap to Copy-org-mch
class Rigify_utils_Copy_rig4(bpy.types.Operator):
    """Creates bindings from Mocap to Copy. Select Copy-mch-org, then mocap"""
    bl_idname = "rigify_utils.copy_rig4"
    bl_label = "Copy rigify rig4"
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
        props = context.scene.my_addon_props # Stored user inputs in UI
        bone_binds = {
            # props.org_shoulder_r : ["RightShoulder", "J_Bip_R_Shoulder"],
            props.org_upper_arm_r : ["RightArm", "J_Bip_R_UpperArm"],
            props.org_forearm_r : ["RightForeArm", "J_Bip_R_LowerArm"],
            props.org_hand_r : ["RightHand", "J_Bip_R_Hand"],
            props.org_thigh_r : ["RightUpLeg", "J_Bip_R_UpperLeg"],
            props.org_shin_r : ["RightLeg", "J_Bip_R_LowerLeg"],
            props.org_foot_r : ["RightFoot", "J_Bip_R_Foot"],
            props.org_toe_r : ["RightToeBase", "J_Bip_R_ToeBase"],

            # props.org_shoulder_l : ["LeftShoulder", "J_Bip_L_Shoulder"],
            props.org_upper_arm_l : ["LeftArm", "J_Bip_L_UpperArm"],
            props.org_forearm_l : ["LeftForeArm", "J_Bip_L_LowerArm"],
            props.org_hand_l : ["LeftHand", "J_Bip_L_Hand"],
            props.org_thigh_l : ["LeftUpLeg", "J_Bip_L_UpperLeg"],
            props.org_shin_l : ["LeftLeg", "J_Bip_L_LowerLeg"],
            props.org_foot_l : ["LeftFoot", "J_Bip_L_Foot"],
            props.org_toe_l : ["LeftToeBase", "J_Bip_L_ToeBase"],
        }
        count = 0
        skipped = 0
        for bone in context.selected_pose_bones:
            if bone.name not in bone_binds:
                continue
            target_name = resolve_subtarget(mocap, bone_binds[bone.name])
            if target_name is None:
                skipped += 1
                continue
            con = bone.constraints.new('COPY_ROTATION')
            con.target = mocap
            con.subtarget = target_name

            ## Local doesn't really work if rigify bones aren't straight
            # setattr(con, "target_space", 'LOCAL_OWNER_ORIENT')
            # con.target_space = 'LOCAL_OWNER_ORIENT'
            # con.owner_space = 'LOCAL'
            # con.influence = 1.0
            # con.mix_mode = 'AFTER'
            count += 1
        if skipped:
            self.report({'WARNING'}, f"{skipped} bones had no matching mocap target")

        # Hips location bind
        hips_candidates = ["Hips", "J_Bip_Hips", "hips", "Hip"]
        hips_name = resolve_subtarget(mocap, hips_candidates)
        for bone in context.selected_pose_bones:
            if bone.name != "ORG-spine":
                continue
            if hips_name is None:
                self.report({'WARNING'}, "No 'Hips' bone found in mocap rig")
                break
            con = bone.constraints.new('COPY_LOCATION')
            con.target = mocap
            con.subtarget = hips_name

            # setattr(con, "target_space", 'LOCAL_OWNER_ORIENT')
            con.target_space = 'LOCAL_OWNER_ORIENT'
            con.owner_space = 'LOCAL'
            con.influence = 1.0
            con.use_offset = True # allows moving around


        
        # SPINE BONES   
        bpy.ops.object.editmode_toggle(True)
        bpy.ops.armature.select_all(action='SELECT')

        # Get center bones for copy rigify rig
        bones_copy = find_centered_bones(copy.data.edit_bones)
        bones_mocap = find_centered_bones(mocap.data.edit_bones)
        bones_pairs = {}
        for bone_copy in bones_copy:
            if bone_copy.name == props.mch_torso: # Ignore
                continue
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

        rigify_candidates = [
            obj for obj in armatures
            if obj.data.collections_all.find("Torso (Tweak)") != -1
            and not obj.name.endswith("-copy")
            and "-copy." not in obj.name
        ]
        mocap_candidates = [
            obj for obj in armatures
            if "Hips" in obj.pose.bones
        ]
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

    # IK control bones that receive Damped Track in step 3
    usr_upper_arm_l: bpy.props.StringProperty(
        name="Upper Arm IK L",
        description="IK bone that gets Damped Track to ORG-forearm.L",
        default="upper_arm_ik.L"
    )
    usr_upper_arm_r: bpy.props.StringProperty(
        name="Upper Arm IK R",
        description="IK bone that gets Damped Track to ORG-forearm.R",
        default="upper_arm_ik.R"
    )
    usr_thigh_l: bpy.props.StringProperty(
        name="Thigh IK L",
        description="IK bone that gets Damped Track to ORG-shin.L",
        default="thigh_ik.L"
    )
    usr_thigh_r: bpy.props.StringProperty(
        name="Thigh IK R",
        description="IK bone that gets Damped Track to ORG-shin.R",
        default="thigh_ik.R"
    )
