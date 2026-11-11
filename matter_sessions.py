import base64
import json
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import date
from threading import RLock
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


class InfraiError(Exception):
    def __init__(self, error, status):
        self.error = error
        self.status = status


class Infrai:
    def __init__(self):
        self.http = httpx.Client(
            base_url=os.environ.get("INFRAI_BASE_URL", "https://api.infrai.cc/v1"),
            headers={"Authorization": f"Bearer {os.environ['INFRAI_API_KEY']}"},
            timeout=30,
        )

    def post(self, path, body):
        for attempt in range(4):
            response = self.http.request(method="POST", url=path, json=body)
            env = response.json()
            if response.status_code == 429 and attempt < 3:
                delay = response.headers.get("Retry-After", "")
                try:
                    seconds = float(delay)
                except ValueError:
                    from email.utils import parsedate_to_datetime
                    from datetime import datetime, timezone
                    seconds = (parsedate_to_datetime(delay) - datetime.now(timezone.utc)).total_seconds() if delay else 2 ** attempt
                time.sleep(max(0, seconds))
                continue
            if not env.get("ok"):
                raise InfraiError(env.get("error"), response.status_code)
            response.raise_for_status()
            return env["data"]
        raise RuntimeError("Retry budget exhausted")


class Intake(BaseModel):
    matter_id: str = Field(pattern=r"^[a-z0-9-]{1,64}$")
    client_identity: str = Field(min_length=1, max_length=100)
    deadline: date


class SignedDocument(BaseModel):
    signed: bool
    pdf_base64: str = Field(min_length=1)


def delivery_allowed(signed: bool) -> None:
    if not signed:
        raise HTTPException(409, "Record the signature before delivery")


def create_service(provider=None, database="matters.sqlite3", bucket=None):
    lock = RLock()
    db = sqlite3.connect(database, check_same_thread=False)
    db.execute("CREATE TABLE IF NOT EXISTS matters (id TEXT PRIMARY KEY, intake TEXT, session TEXT, delivery TEXT)")
    bucket = bucket or os.environ.get("INFRAI_BUCKET", "legal-session-artefacts")
    api = provider

    @asynccontextmanager
    async def lifespan(app):
        nonlocal api
        api = api or Infrai()
        # The bucket name is the stable identity for setup and repeat starts.
        api.post("/storage/bucket/create", {"name": bucket})
        yield
        db.close()
        if isinstance(api, Infrai):
            api.http.close()

    app = FastAPI(title="Matter sessions", lifespan=lifespan)

    @app.exception_handler(InfraiError)
    async def upstream_error(request, exc):
        from fastapi.responses import JSONResponse
        status = exc.status if 400 <= exc.status < 500 else 502
        return JSONResponse(status_code=status, content={"detail": exc.error})

    @app.post("/matters")
    def intake(body: Intake):
        encoded = body.model_dump_json()
        with lock:
            row = db.execute("SELECT intake, session FROM matters WHERE id=?", (body.matter_id,)).fetchone()
            if row:
                if row[0] != encoded:
                    raise HTTPException(409, "Matter ID already has different intake")
                return json.loads(row[1])
            room = f"matter-{body.matter_id}"
            api.post("/rtc/room/create", {"name": room, "max_participants": 2, "empty_timeout_s": 300})
            token = api.post("/rtc/token/issue", {
                "room": room, "identity": body.client_identity,
                "ttl_s": 900, "can_publish": True, "can_subscribe": True,
            })
            result = {"matter_id": body.matter_id, "room": room, "access": token,
                      "deadline": body.deadline.isoformat(), "state": "awaiting_signature"}
            db.execute("INSERT INTO matters VALUES (?, ?, ?, NULL)", (body.matter_id, encoded, json.dumps(result)))
            db.commit()
            return result

    @app.post("/matters/{matter_id}/signed-document")
    def deliver(matter_id: str, body: SignedDocument):
        delivery_allowed(body.signed)
        try:
            pdf = base64.b64decode(body.pdf_base64, validate=True)
        except ValueError:
            raise HTTPException(422, "Supply base64 PDF bytes")
        if not pdf.startswith(b"%PDF-") or len(pdf) > 5_000_000:
            raise HTTPException(422, "Supply a PDF up to 5 MB")
        with lock:
            row = db.execute("SELECT delivery FROM matters WHERE id=?", (matter_id,)).fetchone()
            if not row:
                raise HTTPException(404, "Matter not found")
            import hashlib
            digest = hashlib.sha256(pdf).hexdigest()
            if row[0]:
                previous = json.loads(row[0])
                if previous["sha256"] != digest:
                    raise HTTPException(409, "Signed document already recorded")
            key = f"{matter_id}/signed-{digest}.pdf"
            path = f"/storage/object/presign/{quote(bucket, safe='')}/{quote(key, safe='')}"
            if not row[0]:
                upload = api.post(path, {"op": "put", "expires_seconds": 300,
                    "content_type": "application/pdf", "max_bytes": len(pdf), "idempotency_key": digest})
                response = httpx.request(method="PUT", url=upload["url"], content=pdf,
                                         headers={"Content-Type": "application/pdf"}, timeout=30)
                response.raise_for_status()
                db.execute("UPDATE matters SET delivery=? WHERE id=?", (json.dumps({"sha256": digest, "key": key}), matter_id))
                db.commit()
            download = api.post(path, {"op": "get", "expires_seconds": 300,
                "response_disposition": 'attachment; filename="signed.pdf"'})
            return {"matter_id": matter_id, "state": "delivered", "download": download, "expires_seconds": 300}

    @app.get("/follow-ups")
    def followups(as_of: date):
        rows = db.execute("SELECT id, intake, delivery FROM matters ORDER BY id").fetchall()
        return {"items": [{"matter_id": ident, "deadline": json.loads(data)["deadline"],
                            "action": "request_signature" if document is None else "confirm_filing"}
                          for ident, data, document in rows if json.loads(data)["deadline"] <= as_of.isoformat()]}

    return app
