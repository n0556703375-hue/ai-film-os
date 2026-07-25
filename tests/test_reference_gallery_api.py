import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.api.assets import grouped_approved_references


class ReferenceGalleryApiTests(unittest.TestCase):
    @patch("app.api.assets.repo.get_asset")
    def test_returns_only_approved_references_grouped_by_view_and_expression(self, get_asset):
        get_asset.return_value = {
            "id": 12,
            "reference_images": [
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
                    "metadata": {"expression": "focused"},
                },
                {
                    "id": 3,
                    "view_type": "profile",
                    "approved": False,
                    "metadata": {"expression": "neutral"},
                },
            ],
        }

        result = grouped_approved_references(12)

        self.assertEqual(result["asset_id"], 12)
        self.assertEqual(result["groups"]["front"]["neutral"][0]["id"], 1)
        self.assertEqual(result["groups"]["front"]["focused"][0]["id"], 2)
        self.assertNotIn("profile", result["groups"])
        get_asset.assert_called_once_with(12)

    @patch("app.api.assets.repo.get_asset", return_value=None)
    def test_missing_asset_returns_404(self, _get_asset):
        with self.assertRaises(HTTPException) as raised:
            grouped_approved_references(404)

        self.assertEqual(raised.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
