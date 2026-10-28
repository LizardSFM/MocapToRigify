# The adapter contract. An adapter is one rig family's answer to "how
# does this rig receive motion and still stay correctable" -- everything
# rig-agnostic (proxies, constraint math, slot detection, org-copy
# construction, cleanup) lives in the shared modules and is not the
# adapter's business.
#
# To add a rig family: new file in adapters/, subclass RigAdapter, set
# id/label/detect(), implement build() using the shared machinery, add the
# class to ADAPTERS in adapters/__init__.py. Nothing else changes.


class RigAdapter:
    # Enum identifier in the panel and the label shown next to it.
    id = ""
    label = ""

    @classmethod
    def detect(cls, rig):
        """How confidently this adapter handles `rig`, 0.0 - 1.0. The
        highest confidence wins in Auto mode."""
        return 0.0

    @classmethod
    def build(cls, context, target, source, rows, hips_gain):
        """Bind `target` to `source` through the mapping `rows`.

        Returns a summary dict (at least 'rotation_pairs' and 'hips' for
        the operator's report). Cleanup is shared: generated objects carry
        the role keys, constraints the -urt suffix.
        """
        raise NotImplementedError
