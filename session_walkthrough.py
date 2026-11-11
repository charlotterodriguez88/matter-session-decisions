import base64
import json
from pathlib import Path
import sys

import httpx


if __name__ == "__main__":
    pdf = Path(sys.argv[1]).read_bytes()
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=60) as client:
        for method, path, payload in [
            ("POST", "/matters", {"matter_id": "lease-42", "client_identity": "client-7", "deadline": "2026-12-01"}),
            ("POST", "/matters/lease-42/signed-document", {"signed": True, "pdf_base64": base64.b64encode(pdf).decode()}),
            ("GET", "/follow-ups?as_of=2026-12-01", None),
        ]:
            response = client.request(method=method, url=path, json=payload)
            response.raise_for_status()
            print(json.dumps(response.json(), indent=2))
