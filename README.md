# MocapToRigify

A Blender add-on that binds a **Mocap Fusion** motion-capture rig to a **Rigify** rig non-destructively, so the Rigify rig follows the mocap animation while remaining fully pose-correctable.

> **Audience:** This document is written as a technical context brief for AI assistants and contributors taking over the project. It is intentionally dense.

---

## 1. What it does

The add-on sets up a **multi-rig retargeting chain** that transfers motion from a Mocap Fusion skeleton onto a Rigify rig following two core principles:

1. **Copy rotations only** — limb/spine bones receive `COPY_ROTATION` constraints from their mocap counterparts.
2. **Hips get location** — the root spine bone additionally receives a `COPY_LOCATION` constraint (with `use_offset = True`) so it follows hip translation while still being movable.

### Why multiple rigs (non-destructive correction)

A single direct bind would lock the Rigify rig to the mocap and prevent any correction. Instead, the pipeline creates **intermediate copies** of the Rigify rig that drive each other:

```
Mocap rig  ──(rot + hips loc)──►  copy-org-mch  ──►  *-copy  ──►  original Rigify rig
```

- Each stage copies only the transforms it needs.
- Because hips location uses `use_offset` and the user-controlled (IK/tweak) bones are bound with `mix_mode='AFTER'` / offset semantics, you can still **pose the original Rigify rig locally** (move a foot, shift the hips, rotate a hand) on top of the mocap motion.
- Corrections are therefore **non-destructive**: the mocap drive stays intact, and your manual keys layer on top.

---

## 2. Mocap source

- **Source app:** Mocap Fusion.
- **Export:** BVH, or a `.blend` file containing a custom import script that loads all mocap animations into the scene at once.
- **Skeleton:** *Not* Mixamo. The mocap bone tree uses names like `Hips`, `RightArm`, `LeftForeArm`, `RightUpLeg`, `RightForeArm`, `RightFoot`, `RightToeBase`, … (standard hierarchical BVH naming).
- **Bone-name mapping** between Rigify `ORG-*` bones and mocap bones lives in the `bone_binds` dictionaries inside `animation/rigify.py` (see §6).

---

## 3. The retargeting pipeline (4-step workflow)

The panel group `rigify_utils.copy_rig1–4` is the current workflow. The four buttons are the **same logical operation split into debug steps**; they must be run in order. Each step expects you to select specific armatures before pressing the button.

| Step | Button (`bl_label`) | Operator (`bl_idname`) | Input selection | Output |
|------|---------------------|------------------------|-----------------|--------|
| 1 | `Copy rigify rig`   | `rigify_utils.copy_rig`  | Original **Rigify** rig (active) | `*-copy-org-mch` — duplicate of the Rigify rig containing only **ORG + MCH** bones, reparented into a clean chain |
| 2 | `Copy rigify rig2`  | `rigify_utils.copy_rig2` | Original Rigify rig **+** `*-copy-org-mch` | `*-copy` — second duplicate of the original Rigify rig; its torso IK / hand IK / foot IK MCH parents and `spine_fk` chain get constrained to `*-copy-org-mch` |
| 3 | `Copy rigify rig3`  | `rigify_utils.copy_rig3` | Original Rigify rig **+** `*-copy` | Adds `COPY_ROTATION` (and `COPY_LOCATION` for IK bones) on the **original** Rigify rig's bones, driven by `*-copy` |
| 4 | `Copy rigify rig4`  | `rigify_utils.copy_rig4` | `*-copy-org-mch` **+** **Mocap** rig | Binds `*-copy-org-mch` to the Mocap rig: limb rotations, spine rotations (auto-paired by proximity), and hips location |

After step 4, motion flows: **Mocap → copy-org-mch → *-copy → original Rigify rig**.

### Bone-name inputs

Steps 1–4 read bone names from the `MyAddonProperties` property group exposed in the panel (`context.scene.my_addon_props`). These let you remap bones if the Rigify rig was customized. The groups are:

- **User-controlled bones** (`usr_*`): `torso`, `hand_ik.L/R`, `foot_ik.L/R`.
- **MCH bones** (`mch_*`): `MCH-torso.parent`, `MCH-hand_ik.parent.L/R`, `MCH-foot_ik.parent.L/R`.
- **ORG bones** (`org_*`): `ORG-spine`, `ORG-hand.L/R`, `ORG-foot.L/R`, plus limb chains `ORG-{shoulder,upper_arm,forearm,thigh,shin,toe}.{L,R}`.

### Spine auto-pairing heuristic

Steps that bind the spine do **not** use a hard-coded name map. Instead `find_centered_bones()` picks all bones lying on the X≈0 center plane, sorts them by head Z, and `find_closest_bone()` pairs each Rigify spine bone with the nearest mocap spine bone by midpoint distance. `MCH-torso.parent` is explicitly skipped.

---

## 4. Constraint-cleanup tools

These operators (in `animation/constrains.py`) support the correction workflow. They act on the **selected pose bones** of the active armature.

| Button | Operator | Purpose |
|--------|----------|---------|
| Store Constraints        | `boneconstraints.store`              | Serialize all constraints on selected pose bones into a scene-level dict (`context.scene["_stored_bone_constraints"]`). |
| Apply Constraints        | `boneconstraints.apply`              | Re-create previously stored constraints on selected bones. |
| Keyframe Influence       | `boneconstraints.keyframe_influence` | Insert an `influence` keyframe (at the current frame) for every constraint on selected bones. |
| Bake Pose and Remove Constraints | `boneconstraints.bake_and_remove` | Bake the visual pose of selected bones at the current frame, clear their constraints, re-create the stored constraints, then set their influence to 0 and keyframe that. |

### Foot-freezing workflow (example)

To pin a shaking foot to the ground and later release it back to mocap:

1. Move to the frame where the foot should plant; pose it correctly; press <kbd>I</kbd> to insert transform keys.
2. Press **Keyframe Influence** — locks the constraint influence at the current value (1.0) on this frame.
3. Move a few frames forward; press **Bake Pose and Remove Constraints** — bakes the foot's visual position at that frame, then drops the mocap drive (influence 0) so it stays put.
4. Copy/reverse those influence keyframes to control when the foot re-joins the mocap motion.

---

## 5. Legacy / dead operators

The panel still registers older operators that are **deprecated** and kept only for reference. They should be removed or reworked before shipping:

- `Test` — `boneconstraints.test` — no-op debug stub.
- `Copy rigify rig` (the *non*-`rigify_utils` one) — `boneconstraints.copy_rig` — older single-shot version of step 1.
- `Mocap/copy bind` — `boneconstraints.copy_to_mocap_constr` — older version of step 4.
- `Spine retarget` — `boneconstraints.rigify_spine_retarget` — older standalone spine binder.

Their logic is essentially duplicated by the `rigify_utils.copy_rig*` pipeline and they carry the same bugs.

---

## 6. Bone mapping reference

Rigify `ORG-*` → Mocap Fusion (from the `bone_binds` table, `animation/rigify.py`):

| Rigify ORG | Mocap |
|------------|-------|
| `ORG-shoulder.R/L` | `RightShoulder` / `LeftShoulder` |
| `ORG-upper_arm.R/L` | `RightArm` / `LeftArm` |
| `ORG-forearm.R/L` | `RightForeArm` / `LeftForeArm` |
| `ORG-hand.R/L` | `RightHand` / `LeftHand` |
| `ORG-thigh.R/L` | `RightUpLeg` / `LeftUpLeg` |
| `ORG-shin.R/L` | `RightLeg` / `LeftLeg` |
| `ORG-foot.R/L` | `RightFoot` / `LeftFoot` |
| `ORG-toe.R/L` | `RightToeBase` / `LeftToeBase` |
| `ORG-spine` (+`COPY_LOCATION`) | `Hips` |

Spine chain bones are matched automatically by position, not by name.

---

## 7. Installation

This is a **Blender 4.2+ extension** (declared in `blender_manifest.toml`):

- `id = poseconstrainssaver`, `name = MocapToRigify`, `blender_version_min = 4.2.0`, license `GPL-2.0-or-later`.
- For development, the repo is meant to live under:
  `…/Blender Foundation/Blender/<version>/extensions/vscode_development/MocapToRigify`
  (this is the path shown in user tracebacks).
- No `animation/__init__.py` — the package is imported as a namespace package.

> Note: `bl_info` in `__init__.py` (name *"Store, Reapply and Animate Bone Constraints"*, version `(1, 3)`) is stale and does not match the manifest. See §9.

---

## 8. Project structure

```
MocapToRigify/
├── __init__.py             # bl_info, UI panel (BONECONSTRAINTS_PT_panel), class registration
├── blender_manifest.toml   # Blender 4.2+ extension manifest
├── README.md               # this file
└── animation/
    ├── constrains.py       # Constraint store/apply/keyframe/bake operators + helpers
    └── rigify.py           # Retargeting pipeline (copy_rig1–4), spine heuristics,
                            # bone-name PropertyGroup (MyAddonProperties)
```

### Key definitions in `animation/rigify.py`

- `find_centered_bones(bones)` — returns X≈0 bones sorted by head Z (the spine).
- `find_closest_bone(current, others)` — nearest bone by midpoint distance.
- `Rigify_utils_Copy_rig` / `Copy_rig2` / `Copy_rig3` / `Copy_rig4` — the 4 pipeline operators.
- `MyAddonProperties` — `PropertyGroup` with all `usr_*` / `mch_*` / `org_*` `StringProperty` bone-name fields surfaced in the panel.

### Key definitions in `animation/constrains.py`

- `store_constraints_from_bone(bone)` / `apply_constraints_to_bone(bone, data)` — serialize/deserialize a bone's constraints to/from a dict.
- `BONECONSTRAINTS_OT_store` / `_apply` / `_keyframe_influence` / `_bake_and_remove` — the four cleanup operators.

---

## 9. Known issues & technical debt

> These are live bugs/gotchas. Fixing them is tracked separately; do not assume the code is correct as-is.

### Critical (crashes / wrong output)

1. **`Bone.select` crash on Blender 5.0.** Several operators iterate `armature.data.bones` and set `bone.select = True`. In Blender 5.0 `bpy.types.Bone` no longer exposes `.select` (deprecated since 2.8, now removed), raising `AttributeError`. Affects: `Copy_rig4` (select-all + spine subset), `Copy_to_mocap_constrains` (select-all), `Rigify_spine_retarget` (spine subset). **Fix:** use `bpy.ops.pose.select_all(action='SELECT')` for "select all", and iterate `armature.pose.bones` directly (instead of `context.selected_pose_bones`) for the subset cases.
2. **Duplicate dict key in `Copy_to_mocap_constrains`** — `"ORG-upper_arm.R"` appears twice; the `"RightShoulder"` binding is silently overwritten by `"RightArm"`.
3. **Wrong property for left toe in `Copy_rig4`** — line maps `props.org_toe_r : "LeftToeBase"`; should be `props.org_toe_l`.
4. **Latent `KeyError` in spine loops** — `bones_pairs[bone.name]` assumes every selected pose bone is a paired spine bone. If anything else is selected, it crashes.
5. **`constraints_clear()` in a per-bone loop** — `Rigify_utils_Copy_rig` calls `bpy.ops.pose.constraints_clear()` once per pose bone; that clears the *entire* armature N times. Call it once.

### Robustness

- Heavy reliance on `bpy.ops.*` (mode toggles, selection) instead of the data API; operators are context-sensitive and fragile.
- `bpy.ops.object.editmode_toggle(True/False)` / `posemode_toggle(True/False)` — these operators ignore the boolean argument; the code relies on assumed current mode.
- `apply_constraints_to_bone` writes each property twice (`setattr` then `con[key] = value`) under bare `except:`.
- `find_centered_bones` only filters by X≈0; off-center-but-central bones (face, props) can sneak in.
- No validation of user-entered bone names — a typo in a panel field raises a raw `KeyError` mid-operator.
- `bpy.context` is used inside operators instead of the passed `context`.

### Metadata / packaging

- `bl_info` name, version `(1,3)`, and description are stale; manifest `id = poseconstrainssaver` mismatches the repo/add-on name `MocapToRigify`.
- Manifest `tags` includes `Sequencer`, which is irrelevant.
- `README.md` was a two-line stub (now this document).

---

## 10. Constraint-space cheat sheet

How the pipeline configures spaces (useful when debugging jitter or wrong orientation):

| Binding | Constraint | `target_space` | `owner_space` | Notes |
|---------|------------|----------------|---------------|-------|
| Limb rotations (Mocap→copy-org-mch) | `COPY_ROTATION` | default | default | World-aligned copy; works because Rigify limb bones are roughly axis-aligned. |
| Hips location (Mocap→copy-org-mch)   | `COPY_LOCATION` | `LOCAL_OWNER_ORIENT` | `LOCAL` | `use_offset = True` so you can still move the hips. |
| copy-org-mch → *-copy (torso/hand/foot MCH) | `COPY_LOCATION` + `COPY_ROTATION` | default | default | Drives the MCH parents. |
| *-copy → original Rigify (all bones) | `COPY_ROTATION` | `LOCAL` | `LOCAL` | `mix_mode = 'AFTER'`. |
| *-copy → original Rigify (IK bones) | `COPY_LOCATION` | `LOCAL_WITH_PARENT` | `LOCAL_WITH_PARENT` | `use_offset = True`. |
| Spine_fk → copy-org-mch spine | `COPY_ROTATION` | default | default | Paired by `head_local`/`tail_local` touching within 0.0001. |

---

## License

GPL-2.0-or-later (see `blender_manifest.toml`).