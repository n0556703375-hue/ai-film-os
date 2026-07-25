import unittest

from app.services.reference_gallery import group_approved_references


class ReferenceGalleryGroupingTests(unittest.TestCase):
    def test_groups_only_approved_references_by_view_and_expression(self):
        references = [
            {
                "id": 1,
                "view_type": "front",
                "approved": True,
                "metadata": {"expression": "neutral"},
            },
            {
                "id": 2,
                "view_type": "front",
                "approved": True,
                "metadata": {"expression": "concerned"},
            },
            {
                "id": 3,
                "view_type": "profile",
                "approved": False,
                "metadata": {"expression": "neutral"},
            },
        ]

        grouped = group_approved_references(references)

        self.assertEqual(grouped["front"]["neutral"][0]["id"], 1)
        self.assertEqual(grouped["front"]["concerned"][0]["id"], 2)
        self.assertNotIn("profile", grouped)

    def test_missing_labels_receive_stable_defaults(self):
        grouped = group_approved_references(
            [{"id": 7, "view_type": " ", "approved": True, "metadata": {}}]
        )

        self.assertEqual(grouped["unspecified"]["neutral"][0]["id"], 7)

    def test_does_not_mutate_reference_records(self):
        reference = {
            "id": 9,
            "view_type": "three-quarter",
            "approved": True,
            "metadata": {"expression": "focused"},
        }
        original = {**reference, "metadata": dict(reference["metadata"])}

        group_approved_references([reference])

        self.assertEqual(reference, original)


if __name__ == "__main__":
    unittest.main()
