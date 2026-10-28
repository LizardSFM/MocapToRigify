# Slot detection and pairing for any rig.
#
# Names come first: the shared synonym table already covers BVH, Mixamo,
# VRM, Unreal, 3ds Max Biped and Rigify ORG- bones, and a stripped-prefix
# second index catches `ORG-shoulder.L` -> `shoulder.L` even where the
# plain synonym is absent. Topology fills what names cannot: hips by
# branching, legs as the downward chains off the hips, the spine by the
# positional walk in analysis.walk_spine.
#
# Then verify_and_repair() trusts structure over names: conventions
# disagree about what a word means (Source Filmmaker rigs call the upper
# arm 'Shoulder', the calf 'Knee' and the foot 'Shin'), but nobody's
# thigh connects to anything but their shin. Limb slots are re-read off
# the positional chains and the hips off the legs' common ancestor.
#
# The pairing then spreads one rig's torso over the other's around three
# anchors (hips, the bone the shoulders hang off, the head), which is what
# makes a 7-bone spine follow a 4-bone capture without any typed names.

from .. import mapping
from ..mapping import MOCAP_SYNONYMS, SLOTS
from . import analysis

CONF_ORG = 3        # matched an ORG- bone of a rigify-like target
CONF_NAME = 2       # matched a synonym by name
CONF_STRUCTURAL = 1  # recovered from the hierarchy
CONF_NONE = 0

TORSO_SLOTS = ("hips", "spine", "chest", "upper_chest", "neck", "head")

# Slots whose proxy gets rest-swung onto the mocap bone's rest direction.
# Torso excluded: spine bones agree between rigs and a swung hips bone can
# end up upside down by convention (the VRM hips points down).
SWING_SLOTS = (
    "shoulder_l", "upper_arm_l", "forearm_l", "hand_l",
    "shoulder_r", "upper_arm_r", "forearm_r", "hand_r",
    "thigh_l", "shin_l", "foot_l",
    "thigh_r", "shin_r", "foot_r",
)

# Slots whose proxy takes the mocap bone's full rest frame (direction and
# roll). The limbs, and the neck/head: a wrong roll rotates the plane the
# child bends in, and head bones never carry the hips' flip risk.
ALIGNED_SLOTS = SWING_SLOTS + ("neck", "head")

LIMB_SLOT_ORDER = (
    ("shoulder_l", "shoulder_r"),
    ("upper_arm_l", "upper_arm_r"),
    ("forearm_l", "forearm_r"),
    ("hand_l", "hand_r"),
    ("thigh_l", "thigh_r"),
    ("shin_l", "shin_r"),
    ("foot_l", "foot_r"),
)

REQUIRED_SLOTS = ("hips", "head", "hand_l", "hand_r", "foot_l", "foot_r")


def detect_slots(obj, prefer_org=False, deform=None):
    """{slot: (bone_name, confidence)} for this armature.

    `prefer_org` should be set for rigify-like targets: an ORG- twin beats
    the same-named control, because the ORG bone is where mocap rotation
    has to land for the rig's own mechanics to carry it out to the
    controls. `deform` is the vertex-group deform bone set; when several
    bones share a name, a deform bone wins.
    """
    bones = obj.data.bones
    exact = {}
    org = {}
    for bone in bones:
        exact.setdefault(analysis.normalize_name(bone.name), []).append(bone.name)
        if bone.name.startswith(analysis.ORG_PREFIX):
            stripped = analysis.normalize_name(bone.name[len(analysis.ORG_PREFIX):])
            org.setdefault(stripped, []).append(bone.name)

    def pick(candidates):
        for name in candidates:
            if deform and name in deform:
                return name
        return candidates[0]

    resolved = {}
    used = set()

    def claim(slot, name, confidence):
        if slot in resolved:
            return True
        if name and name not in used and name in bones:
            resolved[slot] = (name, confidence)
            used.add(name)
            return True
        return False

    for slot in SLOTS:
        synonyms = MOCAP_SYNONYMS.get(slot, ())
        if prefer_org:
            for synonym in synonyms:
                if synonym in org:
                    if claim(slot, pick(org[synonym]), CONF_ORG):
                        break
        for synonym in synonyms:
            if synonym in exact:
                if claim(slot, pick(exact[synonym]), CONF_NAME):
                    break

    # Structural torso recovery (hips found, some spine slots not): walk
    # hips -> neck and hand out the free chain bones.
    plain = {slot: name for slot, (name, _conf) in resolved.items()}
    mapping._fill_torso_gaps(obj, plain)
    for slot, name in plain.items():
        claim(slot, name, CONF_STRUCTURAL)

    _structural_fill(obj, resolved, deform)
    return resolved


# ------------------------------------------------- structural verification

def _keep_for(rig, deform):
    """Which bones the repair walks may pass through: the ORG layer on
    rigify-like rigs, the deform skeleton anywhere else, and never the
    IK-target / jiggle helpers."""
    if analysis.classify(rig) == analysis.FLAVOR_RIGIFY:
        return lambda b: b.name.startswith(analysis.ORG_PREFIX)
    def keep(bone):
        if deform is not None and bone.name not in deform:
            return False
        name = mapping.normalize(bone.name)
        return not any(word in name for word in ("ik", "jiggle", "pole", "widget"))
    return keep


def _common_ancestor(bones):
    if not bones:
        return None
    chains = []
    for bone in bones:
        chain = []
        current = bone.parent
        while current is not None:
            chain.append(current)
            current = current.parent
        chains.append(chain)
    shortest = min(chains, key=len)
    for candidate in shortest:
        if all(candidate in chain for chain in chains):
            return candidate
    return None


def verify_and_repair(rig, slots, deform=None):
    """Re-read the limb and hips slots off the bone hierarchy, in place.

    Name conventions lie; topology does not. The forearm's parent is the
    upper arm whatever anybody calls it, the thigh's continuing child is
    the shin, and the bone both thighs descend from is the hips -- even
    when a bone *named* Pelvis is just a side deform bone (Source
    Filmmaker rigs). Only slots whose name match contradicts the chain
    move, and those drop to structural confidence.
    """
    bones = rig.data.bones
    keep = _keep_for(rig, deform)

    def bone_of(slot):
        entry = slots.get(slot)
        return bones.get(entry[0]) if entry else None

    def set_slot(slot, bone, confidence=CONF_STRUCTURAL):
        current = slots.get(slot)
        if current and current[0] == bone.name:
            return
        slots[slot] = (bone.name, confidence)

    # Legs: the thigh's positional chain *is* thigh/shin/foot, in order.
    for side in ("l", "r"):
        thigh = bone_of(f"thigh_{side}")
        if thigh is None:
            continue
        chain = analysis.walk_spine(thigh, keep)
        for index, slot in enumerate(("thigh", "shin", "foot")):
            if index < len(chain):
                set_slot(f"{slot}_{side}", chain[index])

    # Hips: the common ancestor of both thighs, as long as the spine
    # actually continues upward from there; otherwise climb the ancestors
    # until it does.
    thighs = [bone_of("thigh_l"), bone_of("thigh_r")]
    thighs = [t for t in thighs if t is not None]
    hips = bone_of("hips")
    head = bone_of("head")
    if thighs:
        candidate = _common_ancestor(thighs) or hips
        for _ in range(4):
            if candidate is None:
                break
            chain = analysis.walk_spine(candidate, keep)
            reaches_head = head is not None and any(b.name == head.name for b in chain)
            if len(chain) >= 3 or reaches_head:
                if hips is None or hips.name != candidate.name:
                    set_slot("hips", candidate)
                break
            candidate = candidate.parent

    # Arms: anchor on the forearm -- the most honestly named bone on any
    # rig. Its parent is the upper arm, its continuing child the hand,
    # and the upper arm's parent the shoulder.
    for side in ("l", "r"):
        forearm = bone_of(f"forearm_{side}")
        if forearm is None:
            continue
        upper = forearm.parent
        while upper is not None and not keep(upper):
            upper = upper.parent
        if upper is not None:
            set_slot(f"upper_arm_{side}", upper)
            hand = analysis.continuing_child(forearm, keep)
            if hand is not None:
                set_slot(f"hand_{side}", hand)
            clavicle = upper.parent
            while clavicle is not None and not keep(clavicle):
                clavicle = clavicle.parent
            if clavicle is not None:
                set_slot(f"shoulder_{side}", clavicle)
    return slots


def _structural_fill(obj, resolved, deform=None):
    """Best-effort topology recovery for slots the names did not give us."""
    bones = obj.data.bones
    if not bones:
        return
    missing = [s for s in SLOTS if s not in resolved]
    if not missing:
        return

    def world_z(bone):
        return (obj.matrix_world @ bone.head_local).z

    if "hips" in missing:
        # The hips is the low branching bone everything descends from.
        ranked = sorted(bones, key=lambda b: (-len(b.children_recursive), world_z(b)))
        for bone in ranked:
            downward = [c for c in bone.children if world_z(c) < world_z(bone)]
            if len(downward) >= 2:
                resolved["hips"] = (bone.name, CONF_STRUCTURAL)
                missing.remove("hips")
                break

    hips_name = resolved.get("hips", (None,))[0]
    hips = bones.get(hips_name) if hips_name else None
    if hips is None:
        return

    def keep(bone):
        if deform is not None and bone.name not in deform:
            return False
        if bone.name.startswith((analysis.MCH_PREFIX, analysis.DEF_PREFIX,
                                 *analysis.NOISE_PREFIXES)):
            return False
        name = mapping.normalize(bone.name)
        return not any(word in name for word in ("ik", "jiggle", "pole", "widget"))

    # Legs: downward children of the hips, split by side. +X is the
    # character's left in Blender convention.
    for child in hips.children:
        if (child.tail_local - child.head_local).z >= -1e-6:
            continue
        side = "l" if child.head_local.x >= 0 else "r"
        chain = analysis.walk_spine(child, keep)
        for index, slot in enumerate(("thigh", "shin", "foot")):
            key = f"{slot}_{side}"
            if index < len(chain) and key in missing:
                resolved[key] = (chain[index].name, CONF_STRUCTURAL)
                missing.remove(key)

    # Spine: the upward continuation, head at the top, neck just under it.
    upward = None
    for child in hips.children:
        vec = child.tail_local - child.head_local
        if vec.z > 1e-6 and abs(child.head_local.x - hips.head_local.x) < 1e-3:
            upward = child
            break
    if upward is not None:
        chain = analysis.walk_spine(upward, keep)
        if "head" in missing and chain:
            resolved["head"] = (chain[-1].name, CONF_STRUCTURAL)
            missing.remove("head")
        if "neck" in missing and len(chain) >= 2:
            resolved["neck"] = (chain[-2].name, CONF_STRUCTURAL)
            missing.remove("neck")
        # Shoulders and arms: sideways branches off the spine chain.
        for spine_bone in chain:
            for child in spine_bone.children:
                vec = child.tail_local - child.head_local
                if abs(vec.x) <= abs(vec.z) or abs(vec.x) < 1e-3:
                    continue
                side = "l" if child.head_local.x >= 0 else "r"
                if f"shoulder_{side}" in missing:
                    resolved[f"shoulder_{side}"] = (child.name, CONF_STRUCTURAL)
                    missing.remove(f"shoulder_{side}")
                arm = analysis.walk_spine(child, keep)
                for index, slot in enumerate(("upper_arm", "forearm", "hand")):
                    key = f"{slot}_{side}"
                    if index + 1 < len(arm) and key in missing:
                        resolved[key] = (arm[index + 1].name, CONF_STRUCTURAL)
                        missing.remove(key)


# ------------------------------------------------------------------ pairing

def _source_torso_chain(obj, slots):
    """Ordered source torso bones, hips first, head last.

    The mocap hierarchy is trusted: walk the parents from the head slot
    down to the hips slot. When that walk is disconnected (a rig where the
    head does not descend from the hips), fall back to the named slots in
    canonical order.
    """
    bones = obj.data.bones
    hips = bones.get(slots.get("hips", (None,))[0]) if slots.get("hips") else None
    top = bones.get(slots.get("head", (None,))[0]) or bones.get(slots.get("neck", (None,))[0])

    if hips is not None and top is not None:
        chain = []
        current = top
        while current is not None:
            chain.append(current.name)
            if current == hips:
                break
            current = current.parent
        if current == hips:
            chain.reverse()
            return chain

    chain = [slots[slot][0] for slot in ("hips", "spine", "chest", "upper_chest", "neck", "head")
             if slots.get(slot)]
    return chain


def _anchor_index(chain, shoulder_parent_name, slots, fallback_slots):
    if shoulder_parent_name in chain:
        return chain.index(shoulder_parent_name)
    for slot in fallback_slots:
        name = slots.get(slot, (None,))[0] if slots.get(slot) else None
        if name in chain:
            return chain.index(name)
    return max(1, (len(chain) * 2) // 3)


def _distribute(target_list, source_list):
    """Spread the source bones over the target bones, keeping order."""
    out = []
    if not target_list or not source_list:
        return out
    count = len(source_list)
    for index, name in enumerate(target_list):
        out.append((name, source_list[min(count - 1, index * count // len(target_list))]))
    return out


def chain_from_hips(obj, hips_name, flavor):
    """The driven torso chain of a target rig, starting at the hips bone.

    For rigify-like targets the chain stays on the ORG bones (that is the
    layer mocap rotation belongs on); the neck/head controls that some
    featuresets generate *without* ORG twins are deliberately not walked
    onto -- they are driven as slot bones instead.
    """
    bones = obj.data.bones
    start = bones.get(hips_name)
    if start is None:
        return []
    if flavor == analysis.FLAVOR_RIGIFY:
        keep = lambda b: b.name.startswith(analysis.ORG_PREFIX)
    else:
        keep = lambda b: not b.name.startswith(
            (analysis.MCH_PREFIX, analysis.DEF_PREFIX, *analysis.NOISE_PREFIXES))
    return [b.name for b in analysis.walk_spine(start, keep)]


def pair_all(source, target, source_slots, target_slots):
    """Build the retarget pairs as an ordered list of row dicts.

    Each row: slot ("" for surplus torso bones), label, source bone, target
    bone, both confidences, required flag. The order is the panel's order:
    torso first, then limbs per segment.
    """
    flavor = analysis.classify(target)
    prefer = flavor == analysis.FLAVOR_RIGIFY
    target_bones = target.data.bones

    # The chain root: for rigify-like targets the ORG bone the thighs hang
    # off, which is the real hips even when a control called "hips" exists.
    root_name = target_slots.get("hips", (None,))[0] if target_slots.get("hips") else None
    if prefer:
        thigh = (target_slots.get("thigh_l", (None,))[0] if target_slots.get("thigh_l") else None) \
            or (target_slots.get("thigh_r", (None,))[0] if target_slots.get("thigh_r") else None)
        thigh_bone = target_bones.get(thigh) if thigh else None
        if thigh_bone is not None and thigh_bone.parent is not None \
                and thigh_bone.parent.name.startswith(analysis.ORG_PREFIX):
            root_name = thigh_bone.parent.name

    chain = chain_from_hips(target, root_name, flavor) if root_name else []
    source_chain = _source_torso_chain(source, source_slots)

    # slot -> target bone name, filled from the pairing below.
    slot_target = {}
    pairs = []  # (target_bone, source_bone) in chain order

    if chain and source_chain:
        shoulder = (target_slots.get("shoulder_l", (None,))[0] if target_slots.get("shoulder_l") else None) \
            or (target_slots.get("shoulder_r", (None,))[0] if target_slots.get("shoulder_r") else None)
        shoulder_bone = target_bones.get(shoulder) if shoulder else None
        t_anchor_parent = shoulder_bone.parent.name if (shoulder_bone and shoulder_bone.parent) else None

        src_shoulder = (source_slots.get("shoulder_l", (None,))[0] if source_slots.get("shoulder_l") else None) \
            or (source_slots.get("shoulder_r", (None,))[0] if source_slots.get("shoulder_r") else None)
        src_shoulder_bone = source.data.bones.get(src_shoulder) if src_shoulder else None
        s_anchor_parent = src_shoulder_bone.parent.name if (src_shoulder_bone and src_shoulder_bone.parent) else None

        t_anchor = _anchor_index(chain, t_anchor_parent, target_slots, ("upper_chest", "chest"))
        s_anchor = _anchor_index(source_chain, s_anchor_parent, source_slots, ("upper_chest", "chest", "spine"))

        pairs.append((chain[0], source_chain[0]))
        slot_target["hips"] = chain[0]

        lower = _distribute(chain[1:t_anchor], source_chain[1:s_anchor])
        upper_source = source_chain[s_anchor + 1:]
        if prefer:
            # The neck and head bind through their own rows on rigify-like
            # targets; the upper chest must not eat their motion.
            neck_entry = source_slots.get("neck")
            neck_name = neck_entry[0] if neck_entry else None
            if neck_name in source_chain:
                upper_source = source_chain[s_anchor + 1:source_chain.index(neck_name)]
        upper = _distribute(chain[t_anchor + 1:], upper_source)
        if chain[t_anchor + 1:] and not upper_source:
            # The target has torso bones the capture does not (a long anime
            # upper chest against a plain UpperChest joint): they follow the
            # shoulder anchor's rotation rather than being left at rest.
            upper = [(name, source_chain[s_anchor]) for name in chain[t_anchor + 1:]]

        pairs.extend(lower)
        if t_anchor < len(chain):
            pairs.append((chain[t_anchor], source_chain[s_anchor]))
            slot_target.setdefault("upper_chest", chain[t_anchor])
        pairs.extend(upper)

        # Name the distributed rows after the source slot they follow.
        source_slot_of = {}
        for slot in ("spine", "chest", "upper_chest", "neck", "head"):
            entry = source_slots.get(slot)
            if entry:
                source_slot_of[entry[0]] = slot
        assigned = {t for t, _s in pairs}
        for tgt, src in pairs:
            if tgt in slot_target.values():
                continue
            slot = source_slot_of.get(src)
            if slot and slot not in slot_target:
                slot_target[slot] = tgt

    rows = []
    used_targets = set()

    def row(slot, tgt, src, required=False):
        if not tgt or not src or tgt in used_targets:
            return
        used_targets.add(tgt)
        t_conf = target_slots.get(slot, (None, CONF_NONE))
        s_conf = source_slots.get(slot, (None, CONF_NONE))
        rows.append({
            "slot": slot,
            "label": mapping.SLOT_LABELS.get(slot, tgt),
            "target_bone": tgt,
            "source_bone": src,
            "conf_target": t_conf[1] if t_conf[1] else CONF_NAME,
            "conf_source": s_conf[1] if s_conf[1] else CONF_NAME,
            "required": required,
        })

    slot_source_of = {}
    for slot in SLOTS:
        entry = source_slots.get(slot)
        if entry:
            slot_source_of[slot] = entry[0]

    for tgt, src in pairs:
        slot = next((s for s, t in slot_target.items() if t == tgt), "")
        row(slot, tgt, src, required=(slot == "hips" or slot == "head"))

    # Rigify-like targets drive the neck/head through their controls when
    # no ORG twin exists (this rig has none). Generic targets normally get
    # them through the chain distribution; if the chain was too short to
    # reach them, fall back to the plain slot pair.
    for slot in ("neck", "head"):
        if not prefer and any(r["slot"] == slot for r in rows):
            continue
        t_entry = target_slots.get(slot)
        s_entry = source_slots.get(slot)
        if t_entry and s_entry:
            row(slot, t_entry[0], s_entry[0], required=(slot == "head"))

    for left_slot, right_slot in LIMB_SLOT_ORDER:
        for slot in (left_slot, right_slot):
            t_entry = target_slots.get(slot)
            s_entry = source_slots.get(slot)
            if t_entry and s_entry:
                row(slot, t_entry[0], s_entry[0],
                    required=slot in ("hand_l", "hand_r", "foot_l", "foot_r"))

    return rows
