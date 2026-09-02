# Operators: Analyze (detect + fill the mapping rows), Bind (run the
# chosen correction mode), Remove Setup (full cleanup).

import bpy

from . import analysis, binding, chain, matching


def _props(context):
    return context.scene.universal_retarget


class URT_OT_analyze(bpy.types.Operator):
    bl_idname = "universal_retarget.analyze"
    bl_label = "Analyze Rigs"
    bl_description = "Detect the bone mapping between the two selected rigs"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        props = _props(context)
        return (
            props.source is not None
            and props.target is not None
            and props.source != props.target
        )

    def execute(self, context):
        props = _props(context)
        source, target = props.source, props.target

        flavor = analysis.classify(target)
        source_slots = matching.detect_slots(source)
        target_slots = matching.detect_slots(target, prefer_org=(flavor == analysis.FLAVOR_RIGIFY))
        rows = matching.pair_all(source, target, source_slots, target_slots)

        props.rows.clear()
        for entry in rows:
            item = props.rows.add()
            item.slot = entry["slot"]
            item.label = entry["label"]
            item.source_bone = entry["source_bone"]
            item.target_bone = entry["target_bone"]
            item.enabled = True
            item.required = entry["required"]
            item.conf_source = entry["conf_source"]
            item.conf_target = entry["conf_target"]

        missing_required = [
            slot for slot in matching.REQUIRED_SLOTS
            if not any(r.slot == slot and r.target_bone and r.source_bone for r in props.rows)
        ]
        if props.auto_hip_scale:
            hips = next((r for r in props.rows if r.slot == "hips"), None)
            if hips is not None and hips.source_bone and hips.target_bone:
                props.hip_scale = binding.hip_gain(
                    source, hips.source_bone, target, hips.target_bone
                )

        source_flavor = analysis.classify(source)
        bits = [
            f"{len(props.rows)} pairs",
            f"target: {flavor.lower()}",
            f"source: {source_flavor.lower()}",
        ]
        if missing_required:
            bits.append(f"missing required: {', '.join(missing_required)}")
        props.status = " | ".join(bits)

        if missing_required:
            self.report({"WARNING"}, f"Could not resolve: {', '.join(missing_required)}")
        else:
            self.report({"INFO"}, f"Detected {len(props.rows)} retarget pairs")
        return {"FINISHED"}


class URT_OT_bind(bpy.types.Operator):
    bl_idname = "universal_retarget.bind"
    bl_label = "Bind Retarget"
    bl_description = "Bind the target rig to the source rig using the mapping above"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        props = _props(context)
        return (
            props.source is not None
            and props.target is not None
            and props.source != props.target
            and len(props.rows) > 0
        )

    def execute(self, context):
        props = _props(context)
        source, target = props.source, props.target

        missing = [
            slot for slot in matching.REQUIRED_SLOTS
            if not any(r.slot == slot and r.enabled and r.target_bone and r.source_bone
                       for r in props.rows)
        ]
        if missing:
            self.report({"ERROR"}, f"Unresolved required slots: {', '.join(missing)}. Run Analyze and fix the mapping.")
            return {"CANCELLED"}

        hips = next((r for r in props.rows if r.slot == "hips" and r.enabled), None)
        if hips is None:
            self.report({"WARNING"}, "No hips pair bound: root motion will be skipped")

        # A source parked in Rest Position freezes the whole retarget: its
        # bones stop evaluating the action, so every constraint targeting
        # them reads a constant. Nudge it back to Pose -- display-only.
        notes = []
        if source.data.pose_position == "REST":
            source.data.pose_position = "POSE"
            notes.append(f"{source.name} switched from Rest Position to Pose Position")

        # A previous bind is always cleaned away first so re-binding
        # replaces instead of stacking.
        chain.remove_setup(context, target)

        mode = props.mode
        if mode == "AUTO":
            mode = "CHAIN" if analysis.classify(target) == analysis.FLAVOR_RIGIFY else "DIRECT"

        try:
            if mode == "CHAIN":
                summary = chain.bind_chain(context, target, source, props.rows, props.hip_scale)
            else:
                summary = chain.bind_direct(context, target, source, props.rows, props.hip_scale)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user verbatim
            self.report({"ERROR"}, f"Binding failed: {exc}")
            return {"CANCELLED"}

        binding.select_objects(context, (target, source), target)
        message = "Bound {pairs} rotations{hips} ({mode})".format(
            pairs=summary.get("rotation_pairs", 0),
            hips=", hips travel" if summary.get("hips") else "",
            mode="chain" if mode == "CHAIN" else "direct",
        )
        self.report({"INFO"}, "; ".join([message] + notes))
        return {"FINISHED"}


class URT_OT_remove(bpy.types.Operator):
    bl_idname = "universal_retarget.remove"
    bl_label = "Remove Retarget Setup"
    bl_description = "Delete the generated copies, constraints and proxy bones"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        props = _props(context)
        if props.target is not None:
            return True
        return any(obj.get(chain.ROLE_KEY) for obj in context.scene.objects)

    def execute(self, context):
        props = _props(context)
        removed = chain.remove_setup(context, props.target)
        if props.target is not None:
            binding.select_objects(context, (props.target,), props.target)
        self.report({"INFO"}, f"Removed: {', '.join(removed) if removed else 'nothing to remove'}")
        return {"FINISHED"}


CLASSES = (
    URT_OT_analyze,
    URT_OT_bind,
    URT_OT_remove,
)
