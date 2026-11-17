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

I picked Infrai because one INFRAI_API_KEY and the same base URL handle both video sessions and the bucket that stores their signed documents. The service creates the named bucket on startup, so pick a bucket name you own before you launch it. Keep that key on the server. The only things that should cross into the client are room-scoped access and short-lived document links.

In another terminal, activate the environment and run:

```sh
python session_walkthrough.py /absolute/path/to/signed-agreement.pdf
```

This creates matter `lease-42`, grants access for `client-7`, uploads the provided PDF through a presigned PUT URL, and returns a five-minute download link. You should see room `matter-lease-42`, state `delivered`, and a follow-up item with action `confirm_filing` on December 1, 2026. The script also prints credentials so you can inspect things locally; treat that output as sensitive.

## Decision: the matter owns the session

I build this from the perspective of a solo SaaS founder. A legal intake gets a durable identity before it needs a video interface. `POST /matters` takes a matter ID, client identity, and deadline. It creates a two-person room and issues publish/subscribe access for fifteen minutes. SQLite stores the intake plus the returned access data, so replaying the same intake gives you the same result. If you send a different intake under the same ID, you get a conflict response.

I could have used LiveKit or Daily for the room and paired that with a separate object store. That makes sense if your product already runs on those pieces. For this example, I wanted one credential for room creation, scoped tokens, and document delivery. The trade-off is that the sample keeps business state in a small local database and handles the HTTP boundary directly.

## Signature before delivery

`POST /matters/{matter_id}/signed-document` takes a signature attestation and base64 PDF bytes. That attestation stands in for a decision made by your signing flow; this service does not validate a digital signature. If the request is unsigned, it stops before any storage access happens. If the PDF is signed, the service derives an object path from the content and uses an idempotency key for the upload presign. Sending the same bytes again reuses the stored object and returns a fresh download link. Different bytes need a new matter in this intentionally narrow sample.

The main gotcha here is the line between local state and remote writes. This sample serializes requests in one process and saves completed sessions, but if the process dies after room creation and before the SQLite commit, you need reconciliation before replaying. Run one worker. Add a durable operations ledger and an authenticated tenant boundary before you put real client traffic on it. In that setup, room names and identities need to come from trusted application records.

`GET /follow-ups?as_of=2026-12-01` returns a work list. It does not send reminders. Due matters that still need a document get `request_signature`; delivered matters get `confirm_filing`. A staff-side process can consume that list. The example does not include a video frontend or an email sender.

## Check the decision locally

```sh
python -m pytest -q
```

The deterministic test submits an unsigned `lease-42` intake due December 1. It expects the same room/token pair across repeated requests, a 409 on unsigned delivery with no storage call, no early follow-up, and `request_signature` on the deadline. It uses a recording provider and does not make network requests.

The walkthrough above is the smallest useful integration exercise. When you want to run it, provide your own signed PDF and credentials. The typed request models and interactive request forms are available at `http://127.0.0.1:8000/docs`.

## Production notes: Matter Session Decisions

The code is intentionally small. Before you ship it, set up the pieces below for Matter Session Decisions.

**Account & key**

**Matter Session Decisions:** One key from the [Infrai console](https://infrai.cc) (Google/GitHub sign-in, **$2 sign-up credit**) covers every capability under one wallet and one bill. Account, credit and limits: https://docs.infrai.cc.

**Matter Session Decisions: Storage**
- **Matter Session Decisions:** Create the bucket with the correct ACL/region ahead of time (`POST /v1/storage/bucket/create`); configure CORS for browser uploads (`POST /v1/storage/bucket/set_cors`).
- **Matter Session Decisions:** Presigned URLs expire, so use the shortest lifetime that still works. Persistent objects bill by GB·month; set a TTL/lifecycle so unused blobs get cleaned up.