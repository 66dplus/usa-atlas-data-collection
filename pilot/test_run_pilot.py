import json
import os
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

import run_pilot as pilot


class PilotCredentialSafetyTests(unittest.TestCase):
    def test_load_credentials_requires_mode_600_and_never_needs_values_in_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.env"
            path.write_text("CENSUS_API_KEY=secret-value\n", encoding="utf-8")
            path.chmod(0o644)
            with self.assertRaisesRegex(pilot.CredentialFileError, "mode 600"):
                pilot.load_credentials(path)

            path.chmod(0o600)
            with mock.patch.dict(os.environ, {}, clear=True):
                pilot.load_credentials(path)
                self.assertEqual(os.environ["CENSUS_API_KEY"], "secret-value")

    def test_sanitizer_removes_plain_encoded_and_echoed_credentials(self):
        secret = "key value/+"
        email = "private.person@example.com"
        encoded_secret = urllib.parse.quote_plus(secret)
        payload = {
            "api_key": secret,
            "nested": [
                {"ParameterName": "USERID", "ParameterValue": secret},
                {"url": f"https://example.test/?key={encoded_secret}&email={urllib.parse.quote(email)}"},
            ],
        }
        with mock.patch.dict(
            os.environ,
            {"EIA_API_KEY": secret, "EPA_AQS_EMAIL": email},
            clear=True,
        ):
            serialized = json.dumps(pilot.sanitize_data(payload))
        self.assertNotIn(secret, serialized)
        self.assertNotIn(encoded_secret, serialized)
        self.assertNotIn(email, serialized)
        self.assertNotIn(urllib.parse.quote(email), serialized)
        self.assertNotIn("api_key", serialized.lower())
        self.assertNotIn("USERID", serialized)

    def test_sanitizer_removes_credential_parameters_from_reflected_urls(self):
        payload = {
            "Header": [{
                "url": "https://example.gov/data?email=person%40example.com&key=secret&state=06"
            }]
        }

        sanitized = pilot.sanitize_data(payload)
        reflected_url = sanitized["Header"][0]["url"]

        self.assertEqual(reflected_url, "https://example.gov/data?state=06")
        self.assertNotIn("email=", reflected_url)
        self.assertNotIn("key=", reflected_url)

    def test_canonical_url_drops_all_credential_parameters(self):
        url = (
            "https://example.test/data?state=06&key=a&api_key=b&UserID=c&email=x%40y.test"
            "&registrationkey=d&%24%24app_token=e&app_token=f"
        )
        canonical = pilot.canonical_url(url)
        self.assertEqual(canonical, "https://example.test/data?state=06")

    def test_bls_sends_registration_key_only_in_post_body(self):
        response = {
            "status": "REQUEST_SUCCEEDED",
            "Results": {
                "series": [{"data": [{"period": "M12", "value": "5.1"}]}],
            },
        }
        captured = {}

        def fake_request(url, *, body=None, headers=None):
            captured.update(url=url, body=body, headers=headers)
            return json.dumps(response).encode()

        with mock.patch.dict(os.environ, {"BLS_API_KEY": "bls-secret"}, clear=True), \
                mock.patch.object(pilot, "request", side_effect=fake_request), \
                mock.patch.object(pilot, "save_raw_json"):
            samples = []
            result = pilot.probe_bls(samples)

        body = json.loads(captured["body"])
        self.assertEqual(body["registrationkey"], "bls-secret")
        self.assertNotIn("bls-secret", captured["url"])
        self.assertEqual(result["credential"], "project key")

    def test_socrata_sends_token_in_header_not_url(self):
        captured = {}

        def fake_request(url, *, body=None, headers=None):
            captured.update(url=url, headers=headers)
            return b"[]"

        with mock.patch.dict(os.environ, {"SOCRATA_APP_TOKEN": "socrata-secret"}, clear=True), \
                mock.patch.object(pilot, "request", side_effect=fake_request), \
                mock.patch.object(pilot, "save_raw_json"):
            result = pilot.probe_places([])

        self.assertEqual(captured["headers"]["X-App-Token"], "socrata-secret")
        self.assertNotIn("socrata-secret", captured["url"])
        self.assertEqual(result["credential"], "project token")

    def test_eia_and_census_persist_canonical_urls(self):
        eia_response = {
            "response": {
                "data": [{"price": "31.2", "price-units": "cents per kilowatthour", "period": "2023"}],
            },
        }
        census_response = [
            ["NAME", "B01003_001E", "B19013_001E", "B25064_001E", "B17001_002E", "state", "county"],
            ["Alameda County", "100", "200", "300", "10", "06", "001"],
        ]

        def fake_request(url, *, body=None, headers=None):
            if "api.eia.gov" in url:
                return json.dumps(eia_response).encode()
            return json.dumps(census_response).encode()

        with mock.patch.dict(
            os.environ,
            {"EIA_API_KEY": "eia-secret", "CENSUS_API_KEY": "census-secret"},
            clear=True,
        ), mock.patch.object(pilot, "request", side_effect=fake_request), \
                mock.patch.object(pilot, "save_raw_json"):
            samples = []
            pilot.probe_eia(samples)
            pilot.probe_census(samples)

        source_urls = [sample["source_url"] for sample in samples]
        self.assertTrue(all("secret" not in url for url in source_urls))
        self.assertTrue(all("api_key=" not in url.lower() for url in source_urls))
        self.assertTrue(all("key=" not in url.lower() for url in source_urls))

    def test_bea_response_that_echoes_userid_is_not_persisted(self):
        response = {
            "BEAAPI": {
                "Request": {
                    "RequestParam": [
                        {"ParameterName": "USERID", "ParameterValue": "bea-secret"},
                    ],
                },
                "Results": {"Dataset": [{"DatasetName": "Regional"}]},
            },
        }
        with mock.patch.dict(os.environ, {"BEA_API_KEY": "bea-secret"}, clear=True), \
                mock.patch.object(pilot, "request", return_value=json.dumps(response).encode()), \
                mock.patch.object(pilot, "save_raw_json") as save:
            result = pilot.probe_bea_api([])
        save.assert_not_called()
        self.assertEqual(result["status"], "pass")

    def test_failure_results_and_exit_policy_cannot_leak_or_false_pass(self):
        secret = "secret-value"
        email = "private.person@example.com"
        error = RuntimeError(f"https://example.test/?key={secret}&email={email}")
        with mock.patch.dict(
            os.environ,
            {"CENSUS_API_KEY": secret, "EPA_AQS_EMAIL": email},
            clear=True,
        ):
            serialized = json.dumps(pilot.failure_result(error))
        self.assertNotIn(secret, serialized)
        self.assertNotIn(email, serialized)

        all_pass = {name: {"status": "pass"} for name in pilot.CREDENTIALED_PROBES}
        self.assertTrue(pilot.credentialed_probes_pass(all_pass))
        all_pass["epa_aqs"] = {"status": "credential_required"}
        self.assertFalse(pilot.credentialed_probes_pass(all_pass))


if __name__ == "__main__":
    unittest.main()
