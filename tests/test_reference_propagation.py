import copy
import unittest

from app.services.reference_propagation import (
    apply_scene_reference_propagation,
    select_generation_references,
)


class ReferencePropagationTests(unittest.TestCase):
    def test_scene_location_variant_precedes_master_reference(self):
        asset = {
            "asset_type": "לוקיישן",
            "reference_images": ["https://cdn.example/master-location.png"],
            "scene_variant": {
                "state_name": "לילה",
                "reference_url": "https://cdn.example/location-night.png",
            },
        }

        self.assertEqual(
            select_generation_references(asset),
            [
                "https://cdn.example/location-night.png",
                "https://cdn.example/master-location.png",
            ],
        )

    def test_scene_wardrobe_variant_falls_back_to_master_when_empty(self):
        asset = {
            "asset_type": "wardrobe",
            "reference_images": ["https://cdn.example/master-coat.png"],
            "scene_variant": {"state_name": "wet", "reference_url": "   "},
        }

        self.assertEqual(
            select_generation_references(asset),
            ["https://cdn.example/master-coat.png"],
        )

    def test_character_never_uses_scene_variant_as_identity_reference(self):
        asset = {
            "asset_type": "דמות",
            "reference_images": ["https://cdn.example/locked-character.png"],
            "scene_variant": {
                "state_name": "scene look",
                "reference_url": "https://cdn.example/untrusted-character.png",
            },
        }

        self.assertEqual(
            select_generation_references(asset),
            ["https://cdn.example/locked-character.png"],
        )

    def test_propagation_deduplicates_and_does_not_mutate_assets(self):
        assets = [{
            "id": 8,
            "asset_type": "location",
            "reference_images": ["https://cdn.example/room.png"],
            "reference_url": "https://cdn.example/room.png",
            "scene_variant": {"reference_url": "https://cdn.example/room.png"},
        }]
        original = copy.deepcopy(assets)

        result = apply_scene_reference_propagation(assets)

        self.assertEqual(assets, original)
        self.assertIsNot(result[0], assets[0])
        self.assertEqual(
            result[0]["generation_reference_images"],
            ["https://cdn.example/room.png"],
        )


if __name__ == "__main__":
    unittest.main()
