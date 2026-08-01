import bpy

def get_storage(context):
    return context.scene.get("_stored_bone_constraints", {})


def set_storage(context, data):
    context.scene["_stored_bone_constraints"] = data


def store_constraints_from_bone(bone):
    """Save all constraints of a single bone into a dict"""
    bone_data = []
    for con in bone.constraints:
        con_data = {
            "type": con.type,
        }
        for prop in con.bl_rna.properties:
            if not prop.is_readonly and not prop.is_hidden:
                name = prop.identifier
                try:
                    value = getattr(con, name)
                    if name != "target":
                        con_data[name] = value
                except:
                    pass
        if hasattr(con, 'target'):
        # if con.target:
            con_data["target_name"] = con.target.name
            con_data["target_type"] = con.target.type
        else:
            con_data["target_name"] = None
            con_data["target_type"] = None

        if hasattr(con, "subtarget"):
            con_data["subtarget"] = con.subtarget

        bone_data.append(con_data)
    return bone_data


def apply_constraints_to_bone(bone, bone_data):
    """Apply stored constraints back onto a bone"""
    for con_data in bone_data:
        con = bone.constraints.new(con_data["type"])

        if con_data.get("target_name"):
            target_obj = bpy.data.objects.get(con_data["target_name"])
            if target_obj:
                con.target = target_obj

        if con_data.get("subtarget"):
            con.subtarget = con_data["subtarget"]

        for key, value in con_data.items():
            if key in {"type", "target_name", "target_type", "subtarget"}:
                continue
            if hasattr(con, key):
                try:
                    # con[key] = value
                    setattr(con, key, value)
                except Exception as e:
                    print(e)
                    pass
                try:
                    con[key] = value
                except:
                    pass

# ----------------------
# Operators
# ----------------------

class BONECONSTRAINTS_OT_store(bpy.types.Operator):
    """Store constraints from selected bones"""
    bl_idname = "boneconstraints.store"
    bl_label = "Store Constraints"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.object
        if obj is None or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Select an armature in Pose Mode")
            return {'CANCELLED'}

        storage = {}
        for bone in context.selected_pose_bones:
            storage[bone.name] = store_constraints_from_bone(bone)

        set_storage(context, storage)
        self.report({'INFO'}, f"Stored constraints for {len(storage)} bones")
        return {'FINISHED'}


class BONECONSTRAINTS_OT_apply(bpy.types.Operator):
    """Reapply stored constraints to selected bones"""
    bl_idname = "boneconstraints.apply"
    bl_label = "Apply Constraints"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.object
        if obj is None or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Select an armature in Pose Mode")
            return {'CANCELLED'}

        storage = get_storage(context)
        if not storage:
            self.report({'ERROR'}, "No stored constraints found")
            return {'CANCELLED'}

        count = 0
        for bone in context.selected_pose_bones:
            if bone.name in storage:
                apply_constraints_to_bone(bone, storage[bone.name])
                count += len(storage[bone.name])

        self.report({'INFO'}, f"Applied {count} constraints")
        return {'FINISHED'}


class BONECONSTRAINTS_OT_keyframe_influence(bpy.types.Operator):
    """Insert keyframe for constraint influence on selected bones"""
    bl_idname = "boneconstraints.keyframe_influence"
    bl_label = "Keyframe Influence"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.object
        if obj is None or obj.type != "ARMATURE":
            self.report({'ERROR'}, "Select an armature in Pose Mode")
            return {'CANCELLED'}

        frame = context.scene.frame_current
        count = 0
        for bone in context.selected_pose_bones:
            for con in bone.constraints:
                try:
                    con.keyframe_insert("influence", frame=frame)
                    count += 1
                except:
                    pass

        self.report({'INFO'}, f"Inserted {count} influence keyframes")
        return {'FINISHED'}


class BONECONSTRAINTS_OT_bake_and_remove(bpy.types.Operator):
    """Bake pose at current frame, remove constraints, keyframe influence=0, then reapply constraints"""
    bl_idname = "boneconstraints.bake_and_remove"
    bl_label = "Bake Pose and Remove Constraints"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        obj = context.object
        if obj is None or obj.type != "ARMATURE":
            self.report({'ERROR'}, "Select an armature in Pose Mode")
            return {'CANCELLED'}

        frame = context.scene.frame_current
        baked = 0

        # Step 1: store constraints
        stored = {}
        for bone in context.selected_pose_bones:
            stored[bone.name] = store_constraints_from_bone(bone)

        # Step 2: bake single keyframe with Blender’s built-in operator
        bpy.ops.nla.bake(
            frame_start=frame,
            frame_end=frame,
            only_selected=True,
            visual_keying=True,
            clear_constraints=True,
            use_current_action=True,
            bake_types={'POSE'}
        )

        # Step 3: reapply stored constraints
        for bone in context.selected_pose_bones:
            if bone.name in stored:
                apply_constraints_to_bone(bone, stored[bone.name])

        # Step 4: set influence to 0 and keyframe it
        for bone in context.selected_pose_bones:
            for con in bone.constraints:
                con.influence = 0.0
                try:
                    con.keyframe_insert("influence", frame=frame)
                except:
                    pass
            baked += 1

        self.report({'INFO'}, f"Baked {baked} bones")
        return {'FINISHED'}

