import unittest

from pydantic import ValidationError

from app.api.identity_assessments import IdentityDriftClaimRequest


class IdentityDriftWorkerClaimValidationTests(unittest.TestCase):
    def test_trims_worker_id_before_use(self):
        request = IdentityDriftClaimRequest(worker_id="  identity-worker-1  ")

        self.assertEqual(request.worker_id, "identity-worker-1")

    def test_rejects_whitespace_only_worker_id(self):
        with self.assertRaises(ValidationError):
            IdentityDriftClaimRequest(worker_id="   ")


if __name__ == "__main__":
    unittest.main()
