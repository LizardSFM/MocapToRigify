# MocapToRigify

A Blender add-on that binds a **Mocap Fusion** motion-capture rig to a **Rigify** rig non-destructively, so the Rigify rig follows the mocap animation while remaining fully pose-correctable.

> **Audience:** This document is written as a technical context brief for AI assistants and contributors taking over the project. It is intentionally dense.

> **New in 1.3.0 — Universal Retarget.** A second, rig-agnostic pipeline now lives in `animation/universal/`: pick any two armatures from dropdowns, press **Analyze** to auto-detect the bone mapping (no typed bone names), review/fix it in a bone-search list, and **Bind**. Rigify-generated targets automatically get the full correction chain (§3 generalized off hardcoded bone names); plain FK rigs get a direct bind. Sections 1–10 below describe the original rigify-specific pipeline, which is unchanged and still registered alongside. See §11 for the universal system.

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
- **`fix_def_parents`** - step 1 option (checkbox above the *Create ORG/MCH Copy* button): once the copy is created, `rigify_def_parent_fix()` re-parents DEF bones on the **original** rig that hang under an ORG bone. The new parent is found by walking up the ORG parent's ancestor chain and taking the first usable match: an ancestor that is itself a DEF bone, or a DEF bone occupying exactly the same head/tail positions as that ancestor (its positional twin, `ORG-spine.003` -> `DEF-spine.003`). A DEF bone hanging under its own ORG counterpart cannot match itself, so that level is skipped and the walk continues further up (`DEF-shoulder.L` under `ORG-shoulder.L` under `ORG-spine.003` lands on `DEF-spine.003`).

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

## 11. Universal Retarget (1.3.0)

`animation/universal/` — any rig → any rig, mapping detected instead of typed. Same philosophy as the original pipeline (rotation-only, hips location, non-destructive correction), generalized past hardcoded Rigify names. Since v2 the target-specific behaviour lives in **adapters** (below); the core (detection, matching, constraint math) is rig-agnostic.

### Modules

| Module | Role |
|--------|------|
| `analysis.py` | Rig classification (`RIGIFY` when ORG-+MCH- mechanic bones exist, else `GENERIC`), CamelCase-aware name normalization (`UpperArm_L` → `upper arm l`, bare trailing digits stripped so Source-style `Spine0`–`Spine3` still name-match), control-bone detection, MCH IK-parent detection, **`deform_bones()`** — the objective "bones that matter" set read from the vertex groups of armature-modified meshes — and the positional `walk_spine`. |
| `matching.py` | Slot detection v2: synonym names → deform-set preference → structural fallback, then `verify_and_repair` — a topology pass that re-reads legs as "the thigh chain descending from each side of the hips", re-anchors arms on *forearm.parent = upper arm, forearm's continuing child = hand*, and re-derives hips as the common ancestor of both thighs. This is what decoded the Source/SFM naming on the Crusader rig, where `Shoulder.L` is an upper arm, `Hip.L` a thigh and `Pelvis` a side deform bone — pure name matching cannot. Produces the mapping rows; the rows UI stays the manual safety net. |
| `binding.py` | The constraint core, ported verbatim from the original pipeline: `RTG-*` proxies, Child-Of with the mocap rest inverse, Copy Rotation. Limb/neck/head proxies take the mocap bone's **full rest frame** — direction *and* roll, the roll solved by closed-loop candidate search with read-back comparison — so the driven bone's world orientation equals the mocap bone's outright. Wrong rolls don't show on a straight limb but rotate the plane the child bends in (elbows/knees folding twisted); swing-only alignment is only right when both rigs share a twist convention, which a Source port against BVH does not. The hips `TRANSFORM` maps **world→world, rest-anchored on both sides** (`out = target_rest + gain × (in − mocap_rest)`), so no hips-bone orientation can skew the travel. Constraint suffix `-urt`. |
| `adapters/` | The adapter registry (`base.py` defines `RigAdapter`: `detect(rig) → confidence`, `build(...) → summary`). `RigifyChainAdapter` (detects ORG-+MCH-), `FKChainAdapter` (any humanoid skeleton), `DirectAdapter` (last resort). The panel's mode dropdown lists them plus **Auto**, which picks the highest-confidence adapter. Adding a rig family later = one new file in `adapters/`, nothing else changes. |
| `chain.py` | Shared correction-layer machinery: the verified `duplicate_rig` (raises unless it got a *new* object back), the org-copy builder from an **exact copy of the target's armature datablock with the non-driven bones deleted** — no duplication or separation of the user's rig (a mid-operator failure can never damage it), and no bone reconstruction either: recreating bones from head/tail/roll is a trap, `align_roll()` degenerates when a bone's rest Z runs along its length (hips, thighs) and returns 180°-off rolls that ride the world-space Copy Rotations out as a backwards pelvis. Also `make_driver_skeleton` and the role-tagged `remove_setup` every adapter reuses. |
| `adapters/rigify.py` | **Rigify Chain**: org copy (driven ORG bones + MCH IK parents) → driver duplicate whose MCH parents / spine FK controls / neck+head controls / **limb FK controls** follow the org copy → every original control binds `LOCAL/LOCAL AFTER`, IK controls `LOCAL_WITH_PARENT` + location offset. Driving the limb FK controls matters twice over: the FK layer no longer dangles at rest with ghost hands sticking out past the shoulders, and switching a limb to FK mid-shot keeps the captured pose instead of snapping to rest. |
| `adapters/fk_chain.py` | **FK Chain** — the same three-copy correction chain for plain-FK rigs (metarigs used as final rigs, Mixamo, game-skeleton exports): org copy carries the mocap via proxies; the driver's same-name bones Copy-Rotate (world) off the org copy plus the hips `TRANSFORM`; then *every* original bone that exists in the driver gets `COPY_ROTATION LOCAL/LOCAL mix AFTER` ← driver, hips also `TRANSFORM`. Your keys layer on top of the mocap exactly like on Rigify; Keyframe Influence / Bake work unchanged. The rig's own **IK constraints are muted while bound** (recorded, restored by Remove): an IK is a chain solver that rewrites its whole chain's rotations — forearm IK owns the upper arm too — so it cannot layer with the AFTER-mix copy and instead fought it, leaving limbs 50–220° off while torso and head stayed exact. |
| `adapters/direct.py` | **Direct**: proxies and constraints straight on the target's bones. No helper rigs, no correction layer. |
| `props.py` / `operators.py` / `panel.py` | Scene state (`scene.universal_retarget`), the Analyze / Bind / Remove Setup operators, and the "Universal Retarget" N-panel. Analyze reports the auto-picked adapter, the deform-bone coverage and any repaired slots in its status line. |

### What Analyze does

1. Reads the target's deform set from mesh vertex groups (when meshes carry an armature modifier) and detects the 22 canonical slots on **both** rigs (shared synonym table + deform preference + structural fallback), then runs the structural verify-and-repair pass. On rigify-like targets an ORG- twin beats a same-named control.
2. Picks the adapter (reported in the status line; override with the mode dropdown).
3. Builds the target torso chain with a positional, direction-filtered walk (the ORG bones parent to tweak controls, not to each other; and `ORG-shoulder.L` starts exactly on `ORG-spine.003`'s tail, so "most descendants" walks into the arm — direction alignment does not).
4. Pairs the chains around three anchors (hips, the bone the shoulders hang off, head). Target torso bones the capture lacks (a long anime upper chest vs a single UpperChest joint) follow the anchor's rotation; slot-labeled rows come from the distribution.
5. On rigs without ORG neck/head twins (Ochako-style featuresets), the neck/head **controls** become driven bones directly.

### Notes for the generic path

- The hips bone of a BVH rig is a root stub that may point downward; the walk's first hop relaxes the direction rule and takes the most upward continuation.
- Direct mode assumes a target at rest. A target with baked pose location on its hips will double the hips travel (the `TRANSFORM` adds on top); use a clean rig or the Remove button first.
- Bind auto-switches a source parked in armature *Rest Position* display back to *Pose* — otherwise every constraint targeting it reads a constant and the retarget appears frozen.

### Verified against

**Ochako-Rig** (Rigify-generated, 532 bones, no ORG-neck/ORG-head, skirt/penis/face extras) ← BVH-style `mocap` rig (54 bones, object scale 1.116, 120-frame action), Rigify Chain adapter: 23 pairs detected unattended, auto hip gain 5.22 (world rest-height ratio), hips travel maps with **zero** world error at every frame, all 14 limb FK controls paired to their exact ORG bones, frame-1 normalized pose error −0.001, re-bind idempotent, Remove restores the scene exactly. Direct mode verified on a stripped duplicate (hips delta 0.0 at all frames).

**Crusader Rig** (Source/SFM-style port, 161 bones, 148 deform bones, plain FK plus four baked-in limb IK constraints) ← the same `mocap` rig, FK Chain adapter: all 20 slots auto-detected after the structural repair decoded the SFM naming (`Shoulder.L`=upper arm, `Hip.L`=thigh, `Pelvis`=side bone), **0.0°** world-orientation error through the *entire* chain — mocap → org copy → driver → the user's own rig — on shoulders, forearms, hands, thighs, knees, shins, feet, spine, neck and head at frames 1/30/60/90; hips travel exactly proportional (12,371mm vs the capture's 278.5mm = the 44.4 rest-height gain to 0.05%); bind→rebind→remove→bind idempotent with the rig's IK muted while bound and fully restored by Remove. The frame-60 render shows a natural animated stance — no frozen limbs, no twisted bend planes, feet planted.

### Honest boundaries

- Rotation-only transfer cannot reproduce positions when skeleton proportions differ (a capture with proportionally longer limbs lands its hands wider than a stockier target). The AFTER-mix correction layer is the intended fix — that is the addon's whole workflow.
- Rigs with heavy mechanics (Auto-Rig Pro, facial wire rigs, non-humanoids) need a dedicated adapter; the registry is the extension point.
- A target whose hips carry baked pose location will double the hips travel (the `TRANSFORM` adds on top); use a clean rig or the Remove button first.

### Notes on the remaining ~1% hips offset

The original rig's own ORG-spine can sit ~0.13 units (≈1% of height) off the org copy's hips once the spine bends: the original reconstructs its pelvis through the MCH-spine chain from the torso control down, and chain-geometry differences accumulate. The mapping itself is exact (the org copy's ORG-spine lands with 0.000 error); this residue is rigify-internal and is what the non-destructive hips correction keys are for.

---

## License

GPL-2.0-or-later (see `blender_manifest.toml`).