from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from backends.blender.examples.armored_vehicle_spec import make_armored_vehicle_spec
from backends.blender.runtime.graph import validate_graph
from backends.blender.runtime.intake import adapt_object_sculpt_spec
from forge.stage2_spec.validate_sculpt_spec import validate_spec


class ArmoredVehicleGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.spec_path = Path(self.temporary.name) / "vehicle.spec.json"
        self.spec = make_armored_vehicle_spec()
        self.spec_path.write_text(json.dumps(self.spec), encoding="utf-8")
        self.graph = adapt_object_sculpt_spec(self.spec_path)

    def test_source_spec_and_graph_pass_strict_validation(self) -> None:
        errors, warnings = validate_spec(self.spec)
        self.assertEqual([], errors)
        self.assertEqual([], warnings)
        self.assertEqual([], validate_graph(self.graph))

    def test_proof_contract_is_exact(self) -> None:
        self.assertEqual(
            {"materials": 1, "nodes": 3, "pivots": 1, "sockets": 2, "collisions": 1, "lods": 1},
            {name: len(self.graph[name]) for name in ("materials", "nodes", "pivots", "sockets", "collisions", "lods")},
        )
        self.assertEqual(["hull", "turret", "weapon"], [node["id"] for node in self.graph["nodes"]])
        self.assertEqual(["hull", "turret", "weapon"], self.graph["lods"][0]["sourceNodeIds"])
        self.assertEqual(["mirror", "bevel"], [modifier["operation"] for modifier in self.graph["nodes"][0]["modifiers"]])
        self.assertEqual([0.0, 0.0, 2.8], self.graph["sockets"][1]["translation"])

    def test_unknown_operation_fails_closed(self) -> None:
        graph = copy.deepcopy(self.graph)
        graph["nodes"][0]["operation"] = "agent_python"
        self.assertTrue(any("unsupported" in error for error in validate_graph(graph)))

    def test_parent_must_be_topologically_ordered(self) -> None:
        graph = copy.deepcopy(self.graph)
        graph["nodes"] = [graph["nodes"][1], graph["nodes"][0], graph["nodes"][2]]
        self.assertTrue(any("earlier node" in error for error in validate_graph(graph)))

    def test_non_identity_scale_and_duplicate_tags_fail(self) -> None:
        graph = copy.deepcopy(self.graph)
        graph["nodes"][0]["transform"]["scale"] = [2.0, 1.0, 1.0]
        graph["sockets"][0]["tags"] = ["weapon", "weapon"]
        errors = validate_graph(graph)
        self.assertTrue(any("identity" in error for error in errors))
        self.assertTrue(any("tags must be unique" in error for error in errors))

    def test_pivot_axis_and_modifier_order_fail(self) -> None:
        graph = copy.deepcopy(self.graph)
        graph["pivots"][0]["axis"] = [0.0, 2.0, 0.0]
        graph["nodes"][0]["modifiers"].reverse()
        errors = validate_graph(graph)
        self.assertTrue(any("unit vector" in error for error in errors))
        self.assertTrue(any("mirror then bevel" in error for error in errors))

    def test_taper_is_not_silently_discarded(self) -> None:
        spec = copy.deepcopy(self.spec)
        spec["componentTree"][2]["attachment"]["endRadius"] = 0.12
        self.spec_path.write_text(json.dumps(spec), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "tapered"):
            adapt_object_sculpt_spec(self.spec_path)


if __name__ == "__main__":
    unittest.main()
