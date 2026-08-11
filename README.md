# MocapToRigify

A Blender add-on that binds a **Mocap Fusion** motion-capture rig to a **Rigify** rig non-destructively, so the Rigify rig follows the mocap animation while remaining fully pose-correctable.

> **Audience:** This document is written as a technical context brief for AI assistants and contributors taking over the project. It is intentionally dense.

---

## 1. What it does

The add-on sets up a **multi-rig retargeting chain** that transfers motion from a Mocap Fusion skeleton onto a Rigify rig following two core principles:

1. **Copy rotations only** — limb/spine bones follow their mocap counterparts in rotation, through a per-bone helper (`RTG-*`) that cancels the rest-pose difference between the two skeletons. See §6.
2. **Hips get location** — the root spine bone additionally receives a `TRANSFORM` constraint (location→location, `ADD`) so it follows hip translation while still being movable, with an adjustable gain.

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
- **Skeleton:** any humanoid naming convention. Mocap Fusion / BVH (`Hips`, `RightArm`, `LeftForeArm`, …), Mixamo (`mixamorig:LeftArm`), VRM (`J_Bip_L_UpperArm`) and Unreal (`upperarm_l`) are all recognised, and a single rig may mix them — real captures do (one of the test rigs uses `J_Bip_C_Hips` alongside `Spine` and `RightArm`).
- **Bone-name mapping** is resolved per bone by `animation/mapping.py`, not chosen as a whole-rig preset. Anything it fails to identify can be typed into *Bone Mapping → Mocap Bones* in the panel; a filled-in field wins over detection, but only if the selected armature actually has that bone.

---

## 3. The retargeting pipeline (4-step workflow)

The panel group `rigify_utils.copy_rig1–4` is the current workflow. The four buttons are the **same logical operation split into debug steps**; they must be run in order. Each step expects you to select specific armatures before pressing the button.

| Step | Button (`bl_label`) | Operator (`bl_idname`) | Input selection | Output |
|------|---------------------|------------------------|-----------------|--------|
| 1 | `Copy rigify rig`   | `rigify_utils.copy_rig`  | Original **Rigify** rig (active) | `*-copy-org-mch` — duplicate of the Rigify rig containing only **ORG + MCH** bones, reparented into a clean chain |
| 2 | `Copy rigify rig2`  | `rigify_utils.copy_rig2` | Original Rigify rig **+** `*-copy-org-mch` | `*-copy` — second duplicate of the original Rigify rig; its torso IK / hand IK / foot IK MCH parents and `spine_fk` chain get constrained to `*-copy-org-mch` |
| 3 | `Copy rigify rig3`  | `rigify_utils.copy_rig3` | Original Rigify rig **+** `*-copy` | Adds `COPY_ROTATION` (and `COPY_LOCATION` for IK bones) on the **original** Rigify rig's bones, driven by `*-copy` |
| 4 | `Copy rigify rig4`  | `rigify_utils.copy_rig4` | `*-copy-org-mch` **+** **Mocap** rig | Binds `*-copy-org-mch` to the Mocap rig: limb rotations, spine rotations (paired by name and hierarchy), and hips location. Idempotent — re-running replaces the previous bind |

After step 4, motion flows: **Mocap → copy-org-mch → *-copy → original Rigify rig**.

### Bone-name inputs

Steps 1–4 read bone names from the `MyAddonProperties` property group exposed in the panel (`context.scene.my_addon_props`). These let you remap bones if the Rigify rig was customized. The groups are:

- **User-controlled bones** (`usr_*`): `torso`, `hand_ik.L/R`, `foot_ik.L/R`, `neck`, `head`.
- **MCH bones** (`mch_*`): `MCH-torso.parent`, `MCH-hand_ik.parent.L/R`, `MCH-foot_ik.parent.L/R`.
- **ORG bones** (`org_*`): `ORG-spine`, `ORG-hand.L/R`, `ORG-foot.L/R`, plus limb chains `ORG-{shoulder,upper_arm,forearm,thigh,shin,toe}.{L,R}`.
- **Mocap bones** (`mocap_*`): one field per humanoid slot, filled by *Detect From Selected Mocap* or by hand.
- **`hip_translation_scale`**: gain on the root travel, for when the mocap character is a different size than the Rigify one.

### Spine pairing

The Rigify spine chain is walked structurally — from `ORG-spine` upward, always following the child whose head sits on the parent's tail. Three anchors tie it to the mocap chain: the hips at the bottom, the bone the shoulders are parented to in the middle (`ORG-spine.003` against the mocap's `UpperChest` or equivalent), and the head on top. Bones between anchors are distributed proportionally, so a 7-bone Rigify spine works against a 6-bone mocap spine.

This replaced an earlier heuristic that picked bones lying on the X≈0 plane and paired them by proximity. It broke on any mocap rig whose rest bones are not centred in armature space — one of the test captures sits 1.1 m off X in its own local space, which yielded an empty list and crashed step 4 partway through, after the arms and legs had already been bound. That is the "only arms and legs bind" symptom.

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

Removed. `boneconstraints.test`, `boneconstraints.copy_rig`, `boneconstraints.copy_to_mocap_constr` and `boneconstraints.rigify_spine_retarget` duplicated the `rigify_utils.copy_rig*` pipeline with the same bugs and were never wired into the panel. The constraint-cleanup operators in §4 are unaffected.

---

## 6. How a bone is retargeted

A plain world-space `COPY_ROTATION` sets `ORG_pose = MOCAP_pose`, which is only right when both bones share a rest orientation. They rarely do. Measured on the test file, Rigify's `ORG-hand.L` sits **102°** away from the capture's `LeftHand` at rest, and that error rides straight through `MCH-hand_ik.parent` into `hand_ik` — the "hands are rotated 90°" bug.

Step 4 therefore builds, for every retargeted bone, an unparented helper `RTG-<bone>` in a hidden `RTG-mocap` collection:

- the helper gets a **`CHILD_OF`** constraint on the mocap bone, with `inverse_matrix` set to the mocap bone's **rest** matrix. Child Of evaluates as `owner = target_pose · inverse_matrix · owner_rest`, so the helper ends up at `MOCAP_pose · MOCAP_rest⁻¹ · ORG_rest` — the rotation the mocap bone actually travelled, applied on top of Rigify's own rest;
- the ORG bone gets a world **`COPY_ROTATION`** off its helper.

**Rest-pose alignment.** For the arms and legs only, the helper is additionally swung so it points the way the mocap bone points at rest (`_align_proxy_to_mocap_rest`). Rigify rests in an A-pose and most captures rest in a T-pose; without this the two stack and an arm lowered 80° from a T-pose lands 110° down on a rig already 30° down, putting the hands across the body. Only the swing is taken, never the twist, so the roll fix survives. The torso is excluded on purpose — spine bones already agree between rigs, and a hips bone that points the opposite way by convention (VRM's does) would be turned upside down by a swing.

Net effect, measured against the capture over a whole clip: hands and feet point where the mocap points to within 0.1°, and the leftover roll is a fixed rest-convention offset that does not drift.

### Slots

`animation/mapping.py` maps 22 humanoid slots — `hips, spine, chest, upper_chest, neck, head` plus `shoulder / upper_arm / forearm / hand` and `thigh / shin / foot / toe` per side. The Rigify side comes from the `org_*` fields and the structural spine walk; the mocap side from `MOCAP_SYNONYMS` plus the panel overrides.

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

### Fixed

1. **Step 4 crashed partway through on off-centre mocap rigs** — see §3. Arms and legs were bound, then `find_closest_bone()` returned `None` and the operator died before the spine, head and neck.
2. **Hands rotated ~102°** — rest-orientation mismatch, see §6.
3. **Mocap names were hard-coded to Mixamo** — a VRM-named capture produced 14 invalid constraints out of 21. Replaced by the slot mapper.
4. **Wrong property for left toe in `Copy_rig4`** — `props.org_toe_r` was used as a dict key twice, so `ORG-toe.R` bound to `LeftToeBase` and `ORG-toe.L` bound to nothing.
5. **`"Hips"` hard-coded** for the hips location constraint; neither test capture has a bone by that name.
6. **`is_mocap()` required a bone literally named `Hips`**, which left the one-click button permanently greyed out.
7. **Step 4 picked its two objects by selection order** — it looked for an `"ORG"` bone collection that step 1 had already renamed to `"ORG-mocap"`, so the test missed on both objects and always swapped them.
8. **Re-binding stacked constraints** — steps 3 and 4 now strip their own previous output first.
9. **Step 3 only bound *visible* bones.** `pose.select_all` skips closed collections, so `spine_fk` (in the closed *Torso (Tweak)* collection) was never bound and the chest and head followed the torso rigidly, ~20° off. It now binds every bone outside `ORG`/`MCH`/`DEF`.
10. **Step 2 never bound the neck or head** — the `spine_fk` chain stops at the chest, so nothing above it followed the capture.

### Still open

- **Elbows and knees.** Only the IK targets are driven, so the elbow and knee land wherever Rigify's pole targets put them: `DEF-upper_arm` sits ~35° off the captured arm even though the hand is exact. Driving the poles from the capture's actual elbow position is not implemented.
- **`constraints_clear()` in a per-bone loop** — `Rigify_utils_Copy_rig` calls `bpy.ops.pose.constraints_clear()` once per pose bone; that clears the *entire* armature N times. Call it once.
- **Fingers are not retargeted**, and step 1 leaves the copy's palm bones unparented.

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
| Mocap → `RTG-*` helper | `CHILD_OF` | — | — | `inverse_matrix` = the mocap bone's rest matrix, which turns Child Of into a rest-relative follow. |
| `RTG-*` helper → ORG bone | `COPY_ROTATION` | default | default | World copy, exact because the helper carries the corrected rest. |
| Hips location (Mocap→copy-org-mch)   | `TRANSFORM` | `LOCAL_OWNER_ORIENT` | `LOCAL` | Location→location, `mix_mode='ADD'`, `[-1,1] → [-k,k]` with extrapolation, so `k` is a plain gain. |
| copy-org-mch → *-copy (torso/hand/foot MCH) | `COPY_LOCATION` + `COPY_ROTATION` | default | default | Drives the MCH parents. |
| copy-org-mch → *-copy (neck / head) | `COPY_ROTATION` | default | default | The head control sits exactly on the last ORG spine bone, so a world copy is exact. |
| *-copy → original Rigify (control bones) | `COPY_ROTATION` | `LOCAL` | `LOCAL` | `mix_mode = 'AFTER'`, so your own keys layer on top. |
| *-copy → original Rigify (IK bones) | `COPY_LOCATION` | `LOCAL_WITH_PARENT` | `LOCAL_WITH_PARENT` | `use_offset = True`. |
| Spine_fk → copy-org-mch spine | `COPY_ROTATION` | default | default | Paired by `head_local`/`tail_local` touching within 0.0001. |

---

## License

GPL-2.0-or-later (see `blender_manifest.toml`).