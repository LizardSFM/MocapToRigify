# Rig analysis for the universal retargeter. Classifies armatures and pulls
# out the structural facts (rest positions, hierarchy, rigify internals) the
# matcher and the binding chain need.
#
# Everything here reads rest data only (`data.bones`, `matrix_local`,
# `head_local`) -- never `pose.bones` -- so it does not matter what pose the
# rigs happen to be parked in while the user sets up the retarget.

import re

import bpy
from mathutils import Vector

from .. import mapping

FLAVOR_GENERIC = "GENERIC"
FLAVOR_RIGIFY = "RIGIFY"

ORG_PREFIX = "ORG-"
MCH_PREFIX = "MCH-"
DEF_PREFIX = "DEF-"
INTERNAL_PREFIXES = (ORG_PREFIX, MCH_PREFIX, DEF_PREFIX)

NOISE_PREFIXES = ("VIS_", "WGT-")

_TRAILING_NUMBER = re.compile(r"\.(\d+)$")
_CAMEL_CASE = re.compile(r"(?<=[a-z])([A-Z])")
_BARE_NUMBER = re.compile(r"(?<=[a-zA-Z])(\d+)$")


def normalize_name(name):
    """Name folding for slot matching: CamelCase split apart, a bare
    trailing number dropped, then the shared normalize().

    `Spine0` and `Spine2` fold to `spine` (the shared normalize only
    strips dot-separated `.001` suffixes), `UpperArm_L` folds to
    `upperarml`, `LeftHand` stays `lefthand`.
    """
    text = _CAMEL_CASE.sub(r"_\1", name)
    text = _BARE_NUMBER.sub("", text)
    return mapping.normalize(text)


def deform_bones(rig):
    """Names of the rig's bones that actually skin the meshes: the vertex
    group names of every mesh deformed by this armature. The objective
    'bones that matter' set -- IK helpers, jiggle bones and widgets never
    appear in it."""
    names = set()
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        skinned = any(m.type == "ARMATURE" and m.object == rig for m in obj.modifiers)
        if not skinned and obj.parent != rig:
            continue
        for group in obj.vertex_groups:
            names.add(group.name)
    return {name for name in names if name in rig.data.bones.keys()}

# Bones whose world head/tail must line up this exactly to count as
# "the chain continues through here".
POSITION_EPS = 1e-4


def classify(obj):
    """RIGIFY when the armature carries the mechanic bone layers of a
    Rigify-generated rig, GENERIC for anything else."""
    if obj is None or obj.type != "ARMATURE":
        return FLAVOR_GENERIC
    names = obj.data.bones.keys()
    has_org = any(n.startswith(ORG_PREFIX) for n in names)
    has_mch = any(n.startswith(MCH_PREFIX) for n in names)
    return FLAVOR_RIGIFY if has_org and has_mch else FLAVOR_GENERIC


def bone_number(name):
    """The trailing .001-style number, or None. `spine_fk.003` -> '003'."""
    match = _TRAILING_NUMBER.search(name)
    return match.group(1) if match else None


def core_name(name):
    """Normalized name with the rigify layer words burned off, for loose
    comparisons between an ORG bone and its controls."""
    text = mapping.normalize(name)
    for word in ("org", "mch", "def", "tweak", "drv", "widget"):
        text = text.replace(word, "")
    return text


def control_bones(obj):
    """Names of the bones an animator is meant to pose.

    With bone collections: any bone that lives in at least one collection
    other than ORG/MCH/DEF (a bone in both ORG and Torso still counts -- it
    is reachable from a visible collection). Without collections: everything
    that is not an internal prefix bone.
    """
    internal = {"ORG", "MCH", "DEF"}
    if obj.data.collections:
        out = []
        for bone in obj.data.bones:
            if any(c.name not in internal for c in bone.collections):
                out.append(bone.name)
        return out
    return [
        b.name for b in obj.data.bones
        if not b.name.startswith(INTERNAL_PREFIXES)
        and not b.name.startswith(NOISE_PREFIXES)
    ]


def detect_mch_ik_parents(obj):
    """{mch_bone: control_bone} for root MCH bones that directly parent the
    torso or the hand/foot IK controls.

    These are the bones the org copy must carry so the driver copy's IK
    targets can be placed: `MCH-torso.parent`, `MCH-hand_ik.parent.L`,
    `MCH-foot_ik.parent.R` and friends. `thigh_ik_target` and other
    secondary targets are deliberately left out -- the original rig only
    ever needed the torso and the two limb IK chains per side.
    """
    out = {}
    for bone in obj.data.bones:
        if not bone.name.startswith(MCH_PREFIX) or bone.parent is not None:
            continue
        for child in bone.children:
            name = mapping.normalize(child.name)
            if name == "torso" or name.startswith(("handik", "footik")):
                out[bone.name] = child.name
                break
    return out


def direction(bone):
    vec = bone.tail_local - bone.head_local
    length = vec.length
    if length < 1e-12:
        return Vector((0.0, 0.0, 1.0))
    return vec / length


def continuing_children(bone, keep):
    """Children that start exactly where this bone ends."""
    out = []
    for child in bone.children:
        if not keep(child):
            continue
        if (child.head_local - bone.tail_local).length < POSITION_EPS:
            out.append(child)
    return out


def continuing_child(bone, keep):
    """The child that carries this bone's chain on: starts on its tail and
    points closest to the parent's own direction."""
    best = None
    best_dot = -2.0
    parent_dir = direction(bone)
    for child in continuing_children(bone, keep):
        dot = direction(child).dot(parent_dir)
        if dot > best_dot:
            best_dot = dot
            best = child
    if best is not None and best_dot <= 0:
        return None
    return best


def walk_spine(start, keep, stop=(), max_length=64):
    """Follow the torso chain upward from `start`, by joint position.

    In a generated rig the ORG bones parent to tweak controls, not to each
    other, so the chain cannot be walked through the parent links -- the
    kept bones are indexed by where they start and the walk hops from
    joint to joint instead.

    Limbs attach to the spine's joints too (ORG-shoulder.L starts exactly
    on ORG-spine.003's tail), so "the branch with the most descendants"
    walks straight out into an arm. Continuing in the parent's direction
    keeps the walk on the spine: the next vertebra points the way the
    current one does, a shoulder does not.
    """
    kept = [b for b in start.id_data.bones if keep(b) and b.name not in stop]
    by_head = {}
    for bone in kept:
        key = _position_key(bone.head_local)
        by_head.setdefault(key, []).append(bone)

    chain = [start]
    visited = {start.name}
    current = start
    first_hop = True
    for _ in range(max_length):
        kids = [k for k in by_head.get(_position_key(current.tail_local), [])
                if k.name not in visited]
        if not kids:
            break
        parent_dir = direction(current)
        kids.sort(key=lambda k: -direction(k).dot(parent_dir))
        best = kids[0]
        if direction(best).dot(parent_dir) <= 0:
            if not first_hop:
                break
            # The hips bone is a root stub pointing wherever the convention
            # says (BVH hips point down); the spine still continues upward
            # from its tail. Take the most upward continuation once.
            best = max(kids, key=lambda k: direction(k).z)
            if direction(best).z <= 0:
                break
        chain.append(best)
        visited.add(best.name)
        current = best
        first_hop = False
    return chain


def _position_key(vector):
    return (round(vector.x, 5), round(vector.y, 5), round(vector.z, 5))
