# The Rigify adapter: the proven three-copy chain for Rigify-generated
# rigs, generalized off hardcoded bone names. Extracted verbatim from the
# previous chain.py; the construction steps are unchanged.
#
#   * org copy    the driven ORG bones + the MCH IK parents, carrying the
#                 mocap motion through the RTG- proxies
#   * driver copy a full duplicate whose MCH parents / spine FK controls /
#                 neck+head controls / limb FK controls follow the org
#                 copy, so the rig's own IK and mechanics solve against
#                 the mocap pose
#   * original    every control copies the driver's same-named control
#                 AFTER its own local rotation, so keys the user sets
#                 still layer on top

import bpy

from .. import analysis, binding, chain, matching
from ... import mapping
from ..binding import SUFFIX
from .base import RigAdapter


def _match_torso_control(driver, bone_name, bound, reserved=()):
    """The FK control of `driver` that should rotate with the org-copy
    bone `bone_name`.

    Ranked: equal trailing numbers with compatible names (spine_fk.003
    with ORG-spine.003), then an FK-named control sitting on the bone's
    joints, then any control on the joints. Controls already bound are
    skipped, and so are their direct children: a tweak control rides its
    FK parent through the hierarchy and must not be driven a second time
    on top. Only the direct link counts -- the FK controls themselves
    chain through MCH bones (spine_fk.003 hangs under MCH-spine.003 under
    spine_fk.002), and those must stay eligible.
    """
    bones = driver.data.bones
    bone = bones.get(bone_name)
    if bone is None:
        return None
    number = analysis.bone_number(bone_name)
    core = analysis.core_name(bone_name)

    best = None
    best_score = -1.0
    for name in analysis.control_bones(driver):
        if name in bound or name in reserved:
            continue
        control = bones[name]
        if control.parent is not None and control.parent.name in bound:
            continue
        control_number = analysis.bone_number(name)
        control_core = analysis.core_name(name)
        on_joints = (
            (control.head_local - bone.head_local).length < analysis.POSITION_EPS
            or (control.head_local - bone.tail_local).length < analysis.POSITION_EPS
        )
        is_fk = "fk" in mapping.normalize(name)
        if number and control_number and number == control_number \
                and (core in control_core or control_core in core):
            score = 4.0
        elif is_fk and on_joints:
            score = 3.0
        elif on_joints:
            score = 2.0
        else:
            continue
        score += min(len(control.children_recursive), 999) * 1e-3
        if score > best_score:
            best_score = score
            best = name
    return best


def _match_limb_control(driver, bone_name, bound, reserved):
    """The control of `driver` that should rotate with the org-copy limb
    bone `bone_name` (ORG-upper_arm.L -> upper_arm_fk.L, ORG-shoulder.L ->
    shoulder.L).

    Matched by name core and side, preferring FK-named controls; tweak,
    IK-target and pole controls are skipped by name. A control named after
    the bone outranks a positional match: ORG-shoulder.L sits on
    upper_arm_fk.L's joint, and letting the positional rule win shifts the
    whole FK chain down one bone. Unlike the torso matcher there is no
    parent exclusion -- FK controls chain into each other (upper_arm_fk
    parents forearm_fk), which is legitimate.
    """
    bones = driver.data.bones
    bone = bones.get(bone_name)
    if bone is None:
        return None
    core = analysis.core_name(bone_name)
    side = bone_name.rsplit(".", 1)[-1].lower() if "." in bone_name else ""

    best = None
    best_score = -1.0
    for name in analysis.control_bones(driver):
        if name in bound or name in reserved:
            continue
        text = mapping.normalize(name)
        if any(word in text for word in ("tweak", "parent", "pole", "ik", "target", "widget")):
            continue
        control_side = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if side and control_side and control_side != side:
            continue
        on_joints = (
            (bones[name].head_local - bone.head_local).length < analysis.POSITION_EPS
            or (bones[name].head_local - bone.tail_local).length < analysis.POSITION_EPS
        )
        if core in analysis.core_name(name) and "fk" in text:
            score = 3.0
        elif core in analysis.core_name(name):
            score = 2.5
        elif on_joints and "fk" in text:
            score = 2.0
        else:
            continue
        score += min(len(bones[name].children_recursive), 999) * 1e-3
        if score > best_score:
            best_score = score
            best = name
    return best


def build_driver_copy(context, target, org_copy, torso_chain, driven_bones):
    driver = chain.make_driver_skeleton(context, target)

    # MCH IK parents: they carry the targets the driver's IK solves for.
    for pose_bone in org_copy.pose.bones:
        if not pose_bone.name.startswith(analysis.MCH_PREFIX):
            continue
        owner = driver.pose.bones.get(pose_bone.name)
        if owner is None:
            continue
        for constraint_type in ("COPY_LOCATION", "COPY_ROTATION"):
            con = owner.constraints.new(constraint_type)
            con.name = constraint_type.replace("_", " ").title() + SUFFIX
            con.target = org_copy
            con.subtarget = pose_bone.name

    # Torso: FK controls follow the org-copy spine bones. The neck/head
    # controls (driven directly, same-name, below) are reserved so the
    # positional matcher cannot grab them for an ORG bone -- the head
    # control sits exactly on ORG-spine.006's head and would otherwise
    # happily copy the upper chest instead of the capture's head.
    reserved = {name for name in driven_bones
                if name not in torso_chain and not name.startswith(analysis.ORG_PREFIX)}
    bound = set()
    for bone_name in torso_chain:
        control = _match_torso_control(driver, bone_name, bound, reserved)
        if control is None:
            continue
        con = driver.pose.bones[control].constraints.new("COPY_ROTATION")
        con.name = "Copy Rotation" + SUFFIX
        con.target = org_copy
        con.subtarget = bone_name
        bound.add(control)

    # Driven bones that are not ORG-layer (neck/head controls on
    # featuresets without ORG twins) bind to their same-named controls.
    for name in sorted(reserved):
        if name in driver.pose.bones and name not in bound:
            con = driver.pose.bones[name].constraints.new("COPY_ROTATION")
            con.name = "Copy Rotation" + SUFFIX
            con.target = org_copy
            con.subtarget = name
            bound.add(name)

    # Limb FK controls follow their org-copy bones too. Without this only
    # the IK targets carry the capture: the FK layer dangles at its rest
    # pose (ghost hands sticking out past the shoulders), and switching a
    # limb to FK mid-shot would snap it back to rest.
    for name in driven_bones:
        if name in torso_chain or not name.startswith(analysis.ORG_PREFIX):
            continue
        if name in bound:
            continue
        control = _match_limb_control(driver, name, bound, reserved)
        if control is None:
            continue
        con = driver.pose.bones[control].constraints.new("COPY_ROTATION")
        con.name = "Copy Rotation" + SUFFIX
        con.target = org_copy
        con.subtarget = name
        bound.add(control)

    return driver


def bind_original(target, driver, ik_controls):
    """The user's rig follows the driver copy, with room left to correct:
    AFTER mixing keeps locally keyed rotation, the IK controls keep their
    location offset."""
    binding.clear_generated_constraints(target)
    ik = set(ik_controls)
    for name in analysis.control_bones(target):
        pose_bone = target.pose.bones.get(name)
        if pose_bone is None or name not in driver.pose.bones:
            continue
        con = pose_bone.constraints.new("COPY_ROTATION")
        con.name = "Copy Rotation" + SUFFIX
        con.target = driver
        con.subtarget = name
        con.target_space = "LOCAL"
        con.owner_space = "LOCAL"
        con.influence = 1.0
        con.mix_mode = "AFTER"

        if name in ik:
            # These controls need the driver's local-with-parent transform
            # replaced rather than layered, plus the location to follow.
            con.target_space = "LOCAL_WITH_PARENT"
            con.owner_space = "LOCAL_WITH_PARENT"
            loc = pose_bone.constraints.new("COPY_LOCATION")
            loc.name = "Copy Location" + SUFFIX
            loc.target = driver
            loc.subtarget = name
            loc.target_space = "LOCAL_WITH_PARENT"
            loc.owner_space = "LOCAL_WITH_PARENT"
            loc.influence = 1.0
            loc.use_offset = True  # allows moving around


class RigifyChainAdapter(RigAdapter):
    id = "RIGIFY_CHAIN"
    label = "Rigify Chain"

    @classmethod
    def detect(cls, rig):
        return 0.95 if analysis.classify(rig) == analysis.FLAVOR_RIGIFY else 0.0

    @classmethod
    def build(cls, context, target, source, rows, hips_gain):
        flavor = analysis.classify(target)
        pairs = [(row.target_bone, row.source_bone) for row in rows if row.enabled]
        driven_bones = [target for target, _source in pairs]
        swing_bones = {row.target_bone for row in rows
                       if row.enabled and row.slot in matching.ALIGNED_SLOTS}
        hips_row = next((r for r in rows if r.slot == "hips" and r.enabled), None)

        mch_parents = analysis.detect_mch_ik_parents(target)
        mch_reparents = {}
        for mch_name, control_name in mch_parents.items():
            control = mapping.normalize(control_name)
            if control.startswith("handik"):
                slot = "hand_l" if control.endswith("l") else "hand_r"
            elif control.startswith("footik"):
                slot = "foot_l" if control.endswith("l") else "foot_r"
            else:
                slot = "hips"
            slot_row = next((r for r in rows if r.slot == slot and r.target_bone), None)
            if slot_row is not None:
                mch_reparents[mch_name] = slot_row.target_bone

        hips_target = hips_row.target_bone if hips_row else None
        torso_chain = matching.chain_from_hips(target, hips_target, flavor) if hips_target else []

        org_copy = chain.build_org_copy(context, target, driven_bones, mch_reparents)
        binding.create_proxies(context, org_copy, source, pairs, swing_bones)
        bound = binding.bind_rotation_proxies(org_copy, source, pairs)
        hips_bound = False
        if hips_row is not None:
            hips_bound = binding.bind_hips_transform(
                org_copy, source, hips_row.target_bone, hips_row.source_bone, hips_gain)

        driver = build_driver_copy(context, target, org_copy, torso_chain, driven_bones)
        bind_original(target, driver, mch_parents.values())
        return {
            "rotation_pairs": bound,
            "hips": hips_bound,
            "mch_parents": len(mch_reparents),
        }
