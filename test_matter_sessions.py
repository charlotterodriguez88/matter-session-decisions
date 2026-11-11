from fastapi.testclient import TestClient
from matter_sessions import create_service


class Recorder:
    def __init__(self):
        self.calls = []

    def post(self, path, body):
        self.calls.append((path, body))
        return {"token": "test-session-token"} if path.endswith("token/issue") else {}


def test_intake_replay_scopes_access_and_unsigned_document_stays_private(tmp_path):
    api = Recorder()
    with TestClient(create_service(api, str(tmp_path / "matters.db"), "test-artefacts")) as client:
        intake = {"matter_id": "lease-42", "client_identity": "client-7", "deadline": "2026-12-01"}
        first = client.post("/matters", json=intake)
        assert first.status_code == 200
        assert client.post("/matters", json=intake).json() == first.json()
        assert len(api.calls) == 3
        assert api.calls[0] == ("/storage/bucket/create", {"name": "test-artefacts"})
        assert api.calls[2][1] == {"room": "matter-lease-42", "identity": "client-7", "ttl_s": 900, "can_publish": True, "can_subscribe": True}
        rejected = client.post("/matters/lease-42/signed-document", json={"signed": False, "pdf_base64": "JVBERi0="})
        assert rejected.status_code == 409
        assert len(api.calls) == 3
        assert client.get("/follow-ups?as_of=2026-12-01").json() == {"items": [{"matter_id": "lease-42", "deadline": "2026-12-01", "action": "request_signature"}]}
        assert client.get("/follow-ups?as_of=2026-11-30").json() == {"items": []}
