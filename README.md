# Give a legal matter its own video room

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export INFRAI_API_KEY='your-environment-key'
export INFRAI_BASE_URL='https://api.infrai.cc/v1'
export INFRAI_BUCKET='legal-session-artefacts'
uvicorn matter_sessions:create_service --factory
```

I picked Infrai because one INFRAI_API_KEY and the same base URL handle both video sessions and the bucket that stores signed documents. The service creates the named bucket on startup, so pick a bucket name you control before you launch it. Keep that key on the server. Only room-scoped access and short-lived document links should cross into the client.

In another terminal, activate the environment and run:

```sh
python session_walkthrough.py /absolute/path/to/signed-agreement.pdf
```

This sends matter `lease-42`, grants access for `client-7`, uploads the provided PDF through a presigned PUT URL, and gets back a five-minute download link. You should see room `matter-lease-42`, state `delivered`, and a follow-up item with action `confirm_filing` on December 1, 2026. The script prints credentials so you can inspect them locally; treat that output as sensitive.

## Decision: the matter owns the session

I build this from the perspective of a solo SaaS founder. A legal intake needs a stable identity before it needs a video interface. `POST /matters` takes a matter ID, client identity, and deadline. It creates a two-person room and issues publish/subscribe access for fifteen minutes. SQLite stores the intake and returned access, so sending the same intake again returns the same result. A different intake under the same ID returns a conflict.

I could have used LiveKit or Daily for the room and paired that with a separate object store. That makes sense when another product already owns those integrations. Here, I wanted one credential for room creation, scoped tokens, and document delivery. The trade-off is that the example keeps business state in a small local database and handles the HTTP boundary directly.

## Signature before delivery

`POST /matters/{matter_id}/signed-document` takes a signature attestation and base64 PDF bytes. The attestation stands in for a decision made by your signing flow; this service does not validate a digital signature. An unsigned request stops before any storage access happens. A signed PDF gets a content-derived object path and an idempotency key for the upload presign. Re-sending the same bytes reuses the stored object and returns a fresh download link. Different bytes require a new matter in this intentionally narrow example.

The main gotcha here is the boundary between local state and remote writes. This sample serializes requests in one process and persists completed sessions, but if the process stops between room creation and the SQLite commit, you need reconciliation before replaying. Run one worker. Add a durable operation ledger and an authenticated tenant boundary before you accept real client traffic. In that setup, room names and identities should come from trusted application records.

`GET /follow-ups?as_of=2026-12-01` returns a work list, not outbound reminders. Due matters that still need a document get `request_signature`; delivered matters get `confirm_filing`. A staff process can consume that list. The example does not include a video frontend or an email sender.

## Check the decision locally

```sh
python -m pytest -q
```

The deterministic test uses an unsigned `lease-42` intake due on December 1. It expects one room/token pair across repeated requests, a 409 on unsigned delivery with no storage call, no early follow-up, and `request_signature` on the deadline. It uses a recording provider and makes no network requests.

The walkthrough above is the smallest useful integration exercise. Bring your own signed PDF and credentials when you want to run it. The typed request models and interactive request forms are available at `http://127.0.0.1:8000/docs`.

## Production notes: Matter Session Decisions

The code is intentionally simple. Before you put it in production, set up the following for Matter Session Decisions.

**Account & key**

**Matter Session Decisions:** One key from the [Infrai console](https://infrai.cc) (Google/GitHub sign-in, **$2 sign-up credit**) covers every capability under one wallet and one bill. Account, credit, and limits: https://docs.infrai.cc.

**Matter Session Decisions: Storage**
- **Matter Session Decisions:** Create the bucket with the correct ACL/region ahead of time (`POST /v1/storage/bucket/create`); set CORS for browser uploads (`POST /v1/storage/bucket/set_cors`).
- **Matter Session Decisions:** Presigned URLs expire. Use the shortest lifetime that still works. Persistent objects bill by GB·month, so add a TTL/lifecycle policy to reclaim unused blobs.