"""Exercise only the new lab on an isolated OS-assigned loopback port."""
import http.client
import json
import threading
import unittest

from examples.serve_schedule_lab import make_server


class LabHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = make_server(0)
        cls.port = cls.server.server_address[1]
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join(timeout=3)

    def request(self, path):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            return response.status, response.getheader("Content-Type"), response.read()
        finally:
            connection.close()

    def test_page_has_local_form_and_no_external_script_dependency(self):
        status, content_type, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", content_type)
        self.assertIn("训练编排实验台", body.decode())
        self.assertNotIn(b"<script src=\"http", body)

    def test_default_api_and_shortage_case(self):
        status, content_type, body = self.request("/api/schedule")
        self.assertEqual(status, 200)
        self.assertIn("application/json", content_type)
        self.assertEqual(json.loads(body)["summary"]["new"], 6)
        status, _, body = self.request("/api/schedule?new=2&review=12&sources=4&seed=check")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["summary"]["review"], 8)

    def test_invalid_api_inputs_are_client_errors(self):
        for query in ("new=oops", "review=-1", "sources=0", "new=101", "seed=",
                      "new=1&new=2", "unexpected=1"):
            with self.subTest(query=query):
                status, _, body = self.request("/api/schedule?" + query)
                self.assertEqual(status, 400)
                self.assertIn("error", json.loads(body))

    def test_arbitrary_files_are_not_served(self):
        for path in ("/app/training_schedule_v7.py", "/../docs/source-provenance.json", "/missing"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 404)

    def test_production_port_is_explicitly_rejected(self):
        with self.assertRaises(ValueError):
            make_server(8642)


if __name__ == "__main__":
    unittest.main()
