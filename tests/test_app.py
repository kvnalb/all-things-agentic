import unittest

from fastapi.testclient import TestClient

from studyagent.main import app


class AppTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_health(self) -> None:
        self.assertEqual(self.client.get("/api/health").json(), {"status": "ok"})

    def test_setup_status_starts_disconnected(self) -> None:
        response = self.client.get("/api/setup/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 4)
        self.assertTrue(all(item["state"] == "not_connected" for item in response.json()))


if __name__ == "__main__":
    unittest.main()
