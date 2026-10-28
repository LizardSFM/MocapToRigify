# The adapter registry. Order matters as well as confidence: Auto mode
# asks every adapter to detect() and takes the highest confidence, with
# ties going to the earlier entry. To add a rig family, append its class
# here.

from . import direct, fk_chain, rigify
from .base import RigAdapter

ADAPTERS = (
    rigify.RigifyChainAdapter,
    fk_chain.FKChainAdapter,
    direct.DirectAdapter,
)

BY_ID = {adapter.id: adapter for adapter in ADAPTERS}


def auto_pick(target):
    """The adapter with the highest detection confidence for `target`."""
    best = None
    best_confidence = 0.0
    for adapter in ADAPTERS:
        confidence = adapter.detect(target)
        if confidence > best_confidence:
            best = adapter
            best_confidence = confidence
    return best


def resolve(mode, target):
    """The adapter for a panel choice: a concrete id, or Auto."""
    if mode != "AUTO" and mode in BY_ID:
        return BY_ID[mode]
    return auto_pick(target)


def enum_items():
    items = [("AUTO", "Auto",
              "Pick by rig type: Rigify chain for Rigify-generated rigs, "
              "FK chain for plain skeletons, direct constraints otherwise")]
    for adapter in ADAPTERS:
        items.append((adapter.id, adapter.label, ""))
    return items
