# Bone identification. Figures out which bone plays which humanoid role,
# on the mocap side by name and on the Rigify side by hierarchy.

import bpy


# Canonical humanoid slots. Order matters, it drives the UI.
SLOTS = (
    "hips",
    "spine",
    "chest",
    "upper_chest",
    "neck",
    "head",
    "shoulder_l",
    "upper_arm_l",
    "forearm_l",
    "hand_l",
    "shoulder_r",
    "upper_arm_r",
    "forearm_r",
    "hand_r",
    "thigh_l",
    "shin_l",
    "foot_l",
    "toe_l",
    "thigh_r",
    "shin_r",
    "foot_r",
    "toe_r",
)

SLOT_LABELS = {
    "hips": "Hips",
    "spine": "Spine",
    "chest": "Chest",
    "upper_chest": "Upper Chest",
    "neck": "Neck",
    "head": "Head",
    "shoulder_l": "Shoulder L",
    "upper_arm_l": "Upper Arm L",
    "forearm_l": "Forearm L",
    "hand_l": "Hand L",
    "shoulder_r": "Shoulder R",
    "upper_arm_r": "Upper Arm R",
    "forearm_r": "Forearm R",
    "hand_r": "Hand R",
    "thigh_l": "Thigh L",
    "shin_l": "Shin L",
    "foot_l": "Foot L",
    "toe_l": "Toe L",
    "thigh_r": "Thigh R",
    "shin_r": "Shin R",
    "foot_r": "Foot R",
    "toe_r": "Toe R",
}

# Slots the retargeting cannot work without.
REQUIRED_SLOTS = ("hips", "head", "hand_l", "hand_r", "foot_l", "foot_r")

# The property name on MyAddonProperties that holds the mocap bone for a slot.
def mocap_prop_name(slot):
    return "mocap_" + slot


# Known mocap naming conventions, per slot. Compared after normalize().
# Rigs mix conventions freely (Mocap.Run uses J_Bip_C_Hips + Spine + RightArm),
# so this is matched per bone, never as a whole-rig preset.
MOCAP_SYNONYMS = {
    "hips": ("hips", "jbipchips", "pelvis", "bip01pelvis", "hip", "cchips"),
    "spine": ("spine", "jbipcspine", "spine01", "spine1", "bip01spine", "cspine"),
    "chest": ("chest", "jbipcchest", "spine02", "spine2", "bip01spine1", "cchest"),
    "upper_chest": (
        "upperchest", "jbipcupperchest", "spine03", "spine3",
        "bip01spine2", "cupperchest",
    ),
    "neck": ("neck", "jbipcneck", "neck01", "bip01neck", "cneck"),
    "head": ("head", "jbipchead", "bip01head", "chead"),

    "shoulder_l": (
        "leftshoulder", "jbiplshoulder", "shoulderl", "clavicle1", "claviclel",
        "lshoulder", "shoulderleft", "bip01lclavicle", "lclavicle",
    ),
    "upper_arm_l": (
        "leftarm", "jbiplupperarm", "upperarml", "upperarm1", "arml", "larm",
        "orgupperarml", "armleft", "bip01lupperarm", "lupperarm", "shoulderl2",
    ),
    "forearm_l": (
        "leftforearm", "jbipllowerarm", "lowerarml", "lowerarm1", "forearml",
        "lforearm", "orgforearml", "forearmleft", "bip01lforearm", "elbowl",
    ),
    "hand_l": (
        "lefthand", "jbiplhand", "handl", "hand1", "lhand", "orghandl",
        "handleft", "bip01lhand", "wristl",
    ),

    "shoulder_r": (
        "rightshoulder", "jbiprshoulder", "shoulderr", "clavicler", "claviclr",
        "rshoulder", "shoulderright", "bip01rclavicle", "rclavicle",
    ),
    "upper_arm_r": (
        "rightarm", "jbiprupperarm", "upperarmr", "armr", "rarm",
        "orgupperarmr", "armright", "bip01rupperarm", "rupperarm",
    ),
    "forearm_r": (
        "rightforearm", "jbiprlowerarm", "lowerarmr", "forearmr", "rforearm",
        "orgforearmr", "forearmright", "bip01rforearm", "elbowr",
    ),
    "hand_r": (
        "righthand", "jbiprhand", "handr", "rhand", "orghandr",
        "handright", "bip01rhand", "wristr",
    ),

    "thigh_l": (
        "leftupleg", "jbipllipperleg", "jbiplupperleg", "upperlegl", "thighl",
        "lthigh", "orgthighl", "thighleft", "bip01lthigh", "legl", "hipl",
    ),
    "shin_l": (
        "leftleg", "jbipllowerleg", "lowerlegl", "calfl", "shinl", "lshin",
        "orgshinl", "shinleft", "bip01lcalf", "kneel",
    ),
    "foot_l": (
        "leftfoot", "jbiplfoot", "footl", "lfoot", "orgfootl",
        "footleft", "bip01lfoot", "anklel",
    ),
    "toe_l": (
        "lefttoebase", "jbipltoebase", "toebasel", "balll", "toel", "ltoe",
        "orgtoel", "toeleft", "bip01ltoe0", "lefttoe",
    ),

    "thigh_r": (
        "rightupleg", "jbiprupperleg", "upperlegr", "thighr", "rthigh",
        "orgthighr", "thighright", "bip01rthigh", "legr", "hipr",
    ),
    "shin_r": (
        "rightleg", "jbiprlowerleg", "lowerlegr", "calfr", "shinr", "rshin",
        "orgshinr", "shinright", "bip01rcalf", "kneer",
    ),
    "foot_r": (
        "rightfoot", "jbiprfoot", "footr", "rfoot", "orgfootr",
        "footright", "bip01rfoot", "ankler",
    ),
    "toe_r": (
        "righttoebase", "jbiprtoebase", "toebaser", "ballr", "toer", "rtoe",
        "orgtoer", "toeright", "bip01rtoe0", "righttoe",
    ),
}

_PREFIXES = ("mixamorig:", "mixamorig_", "mixamorig", "armature|", "root|")
_JUNK = " _.:-|"


def normalize(name):
    """Fold a bone name down to comparable letters and digits."""
    text = name.lower()
    for prefix in _PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    # Blender's duplicate suffix carries no anatomical meaning.
    if len(text) > 4 and text[-4] == "." and text[-3:].isdigit():
        text = text[:-4]
    for char in _JUNK:
        text = text.replace(char, "")
    return text


def _side_of(normalized):
    """L / R / None, guessed from the usual side markers."""
    if normalized.startswith("left") or normalized.endswith("left"):
        return "L"
    if normalized.startswith("right") or normalized.endswith("right"):
        return "R"
    if normalized.startswith("l") and normalized[1:2].isalpha():
        pass  # too weak on its own, handled by the synonym table
    if normalized.endswith("l"):
        return "L"
    if normalized.endswith("r"):
        return "R"
    return None


def detect_mocap_bones(armature_object):
    """Map every canonical slot onto a bone of this mocap armature.

    Returns {slot: bone_name}; slots that could not be identified are absent.
    """
    if armature_object is None or armature_object.type != "ARMATURE":
        return {}

    by_normalized = {}
    for bone in armature_object.data.bones:
        by_normalized.setdefault(normalize(bone.name), bone.name)

    resolved = {}
    used = set()
    for slot in SLOTS:
        for synonym in MOCAP_SYNONYMS.get(slot, ()):
            bone_name = by_normalized.get(synonym)
            if bone_name is not None and bone_name not in used:
                resolved[slot] = bone_name
                used.add(bone_name)
                break

    _fill_torso_gaps(armature_object, resolved)
    return resolved


def _fill_torso_gaps(armature_object, resolved):
    """Recover unnamed torso joints by walking hips -> neck."""
    if "hips" not in resolved or "neck" not in resolved:
        return
    bones = armature_object.data.bones
    neck = bones.get(resolved["neck"])
    hips_name = resolved["hips"]
    if neck is None:
        return

    # Collect the chain between hips and neck, bottom up.
    chain = []
    current = neck.parent
    while current is not None and current.name != hips_name:
        chain.append(current.name)
        current = current.parent
    if current is None:
        return  # neck is not a descendant of hips, leave it alone
    chain.reverse()

    missing = [s for s in ("spine", "chest", "upper_chest") if s not in resolved]
    free = [name for name in chain if name not in resolved.values()]
    for slot, bone_name in zip(missing, free):
        resolved[slot] = bone_name


def shoulder_anchor(armature_object, resolved):
    """The mocap bone the arms hang off, i.e. the true chest top."""
    bones = armature_object.data.bones
    for slot in ("shoulder_l", "shoulder_r", "upper_arm_l", "upper_arm_r"):
        name = resolved.get(slot)
        bone = bones.get(name) if name else None
        if bone is not None and bone.parent is not None:
            return bone.parent.name
    for slot in ("upper_chest", "chest", "spine"):
        if slot in resolved:
            return resolved[slot]
    return resolved.get("hips")


def is_mocap_armature(obj):
    """A mocap source is any armature we can recognise a humanoid inside.

    Rigify rigs also read as humanoid (they carry `hips`, `head`, `ORG-hand.L`
    and friends), so anything this add-on generates or drives is ruled out
    first -- otherwise both selected objects would qualify.
    """
    if obj is None or obj.type != "ARMATURE":
        return False
    if is_org_copy(obj) or is_driver_copy(obj) or is_original_rigify(obj):
        return False
    resolved = detect_mocap_bones(obj)
    return all(slot in resolved for slot in REQUIRED_SLOTS)


# ---------------------------------------------------------------- Rigify side

def spine_chain(org_copy, root_name):
    """Ordered ORG spine bones, from the hips bone up to the head."""
    bones = org_copy.data.bones
    root = bones.get(root_name)
    if root is None:
        return []
    chain = [root]
    current = root
    while True:
        # Follow the child that continues the chain: it starts where the
        # current bone ends. Limbs branch off sideways and are skipped.
        candidates = [
            child for child in current.children
            if (child.head_local - current.tail_local).length < 1e-4
            and not child.name.startswith("MCH-")
        ]
        if not candidates:
            break
        # Prefer the branch with the most descendants (the real spine).
        current = max(candidates, key=lambda b: len(b.children_recursive))
        chain.append(current)
    return [bone.name for bone in chain]


def _distribute(rigify_bones, mocap_bones):
    """Spread N mocap bones over M rigify bones, keeping their order."""
    pairs = {}
    if not rigify_bones or not mocap_bones:
        return pairs
    count = len(mocap_bones)
    for index, name in enumerate(rigify_bones):
        target = min(count - 1, index * count // len(rigify_bones))
        pairs[name] = mocap_bones[target]
    return pairs


def neck_and_head(org_copy, props):
    """The ORG bones of the neck and the head, found by structure.

    Everything above the bone the shoulders hang off is neck; the tip of the
    chain is the head.
    """
    chain = spine_chain(org_copy, props.org_spine)
    if len(chain) < 2:
        return None, None

    bones = org_copy.data.bones
    shoulder = bones.get(props.org_shoulder_l) or bones.get(props.org_shoulder_r)
    anchor_index = None
    if shoulder is not None and shoulder.parent is not None:
        if shoulder.parent.name in chain:
            anchor_index = chain.index(shoulder.parent.name)
    head_index = len(chain) - 1
    if anchor_index is None or anchor_index >= head_index:
        anchor_index = max(0, head_index - 2)

    neck_name = chain[anchor_index + 1] if anchor_index + 1 < head_index else None
    return neck_name, chain[head_index]


def build_spine_pairs(org_copy, props, mocap_map, mocap_object):
    """Pair the Rigify spine chain with the mocap torso, by structure.

    Three anchors hold the two chains together: the hips at the bottom, the
    bone the shoulders are parented to in the middle, and the head on top.
    Whatever sits between the anchors is distributed proportionally, so a
    7-bone Rigify spine works against a 6-bone mocap spine.
    """
    chain = spine_chain(org_copy, props.org_spine)
    if not chain:
        return {}

    pairs = {}
    if "hips" in mocap_map:
        pairs[chain[0]] = mocap_map["hips"]
    if len(chain) == 1:
        return pairs

    bones = org_copy.data.bones
    shoulder = bones.get(props.org_shoulder_l) or bones.get(props.org_shoulder_r)
    anchor_index = None
    if shoulder is not None and shoulder.parent is not None:
        if shoulder.parent.name in chain:
            anchor_index = chain.index(shoulder.parent.name)

    head_index = len(chain) - 1
    if anchor_index is None or anchor_index >= head_index:
        anchor_index = max(1, head_index - 2)

    mocap_anchor = shoulder_anchor(mocap_object, mocap_map)
    if mocap_anchor:
        pairs[chain[anchor_index]] = mocap_anchor
    if "head" in mocap_map:
        pairs[chain[head_index]] = mocap_map["head"]

    # Torso between hips and the shoulder anchor.
    torso_mocap = [
        mocap_map[slot] for slot in ("spine", "chest", "upper_chest")
        if slot in mocap_map and mocap_map[slot] != mocap_anchor
    ]
    pairs.update(_distribute(chain[1:anchor_index], torso_mocap))

    # Neck between the shoulder anchor and the head.
    neck_mocap = [mocap_map[slot] for slot in ("neck",) if slot in mocap_map]
    pairs.update(_distribute(chain[anchor_index + 1:head_index], neck_mocap))

    return pairs


# ORG bone property on MyAddonProperties for each limb slot.
LIMB_SLOT_PROPS = {
    "shoulder_l": "org_shoulder_l",
    "upper_arm_l": "org_upper_arm_l",
    "forearm_l": "org_forearm_l",
    "hand_l": "org_hand_l",
    "shoulder_r": "org_shoulder_r",
    "upper_arm_r": "org_upper_arm_r",
    "forearm_r": "org_forearm_r",
    "hand_r": "org_hand_r",
    "thigh_l": "org_thigh_l",
    "shin_l": "org_shin_l",
    "foot_l": "org_foot_l",
    "toe_l": "org_toe_l",
    "thigh_r": "org_thigh_r",
    "shin_r": "org_shin_r",
    "foot_r": "org_foot_r",
    "toe_r": "org_toe_r",
}


def limb_org_bones(org_copy, props):
    """ORG bones of the arms and legs.

    These are the ones whose rest direction is allowed to be swung onto the
    mocap's rest direction. The torso is left alone: spine bones already
    agree between rigs, and the hips bone often points the opposite way by
    pure convention (the VRM hips bone points down), which a swing would
    happily turn upside down.
    """
    names = set()
    for slot, prop_name in LIMB_SLOT_PROPS.items():
        org_name = getattr(props, prop_name, "")
        if org_name and org_name in org_copy.data.bones:
            names.add(org_name)
    return names


def build_bone_pairs(org_copy, mocap_object, props, mocap_map):
    """Every {ORG bone: mocap bone} pair to retarget, limbs and spine."""
    pairs = {}
    for slot, prop_name in LIMB_SLOT_PROPS.items():
        org_name = getattr(props, prop_name, "")
        mocap_name = mocap_map.get(slot, "")
        if not org_name or not mocap_name:
            continue
        if org_name not in org_copy.data.bones:
            continue
        if mocap_name not in mocap_object.data.bones:
            continue
        pairs[org_name] = mocap_name

    for org_name, mocap_name in build_spine_pairs(
        org_copy, props, mocap_map, mocap_object
    ).items():
        if org_name in org_copy.data.bones and mocap_name in mocap_object.data.bones:
            pairs[org_name] = mocap_name

    return pairs


def unresolved_slots(mocap_map):
    return [slot for slot in SLOTS if not mocap_map.get(slot)]


# ------------------------------------------------------- rig role identification
# Kept here so both the panels and the operators can use them without importing
# the add-on package back into itself.

GENERATED_ROLE_KEY = "mocap_to_rigify_role"
ROLE_COPY_ORG_MCH = "copy_org_mch"
ROLE_DRIVER_COPY = "driver_copy"


def has_bone_collection(obj, collection_name):
    return (
        obj.type == "ARMATURE"
        and obj.data.collections_all.find(collection_name) != -1
    )


def is_org_copy(obj):
    return (
        obj.type == "ARMATURE"
        and (
            obj.get(GENERATED_ROLE_KEY) == ROLE_COPY_ORG_MCH
            or has_bone_collection(obj, "ORG-mocap")
        )
    )


def is_driver_copy(obj):
    return (
        obj.type == "ARMATURE"
        and not is_org_copy(obj)
        and (
            obj.get(GENERATED_ROLE_KEY) == ROLE_DRIVER_COPY
            or obj.name.endswith("-copy")
            or "-copy." in obj.name
        )
    )


def is_original_rigify(obj):
    return (
        has_bone_collection(obj, "Torso (Tweak)")
        and not is_org_copy(obj)
        and not is_driver_copy(obj)
    )
