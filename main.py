"""
OEM Remote Support - Session Service
=====================================

One API call:
  - creates a video channel (Agora)
  - generates a join token/link
  - starts cloud recording for that channel
  - emails the join link to the OEM rep
  - returns the join link in the response (for the mechanic's app)

Run locally:
    uvicorn main:app --reload --port 8000

Required env vars are documented in .env.example.
"""

import os
import time
import uuid
import base64
import smtplib
import logging
from email.mime.text import MIMEText
from typing import Optional
from urllib.parse import quote

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr
from agora_token_builder import RtcTokenBuilder

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("oem_video_service")

# ---------------------------------------------------------------------------
# Config (all from environment - see .env.example)
# ---------------------------------------------------------------------------

AGORA_APP_ID = os.environ["AGORA_APP_ID"]
AGORA_APP_CERTIFICATE = os.environ["AGORA_APP_CERTIFICATE"]

# These are different from App ID/Certificate - they come from
# Agora Console -> RESTful API keys, and are used to call the
# Cloud Recording REST API (Basic Auth).
AGORA_CUSTOMER_ID = os.environ["AGORA_CUSTOMER_ID"]
AGORA_CUSTOMER_SECRET = os.environ["AGORA_CUSTOMER_SECRET"]

TOKEN_EXPIRE_SECONDS = int(os.environ.get("TOKEN_EXPIRE_SECONDS", 3600))

# Cloud Recording requires a card on file on Agora's side. Until that's set
# up, set ENABLE_CLOUD_RECORDING=false in .env to skip it - the service will
# still create the channel/token and email the join link, it just won't
# record. Flip back to true once recording is ready to test.
ENABLE_CLOUD_RECORDING = os.environ.get("ENABLE_CLOUD_RECORDING", "true").lower() == "true"

# Base URL of the small web page the OEM rep / mechanic actually open
# to join the call (see static/join.html for a minimal example).
JOIN_PAGE_BASE_URL = os.environ["JOIN_PAGE_BASE_URL"]

# Fixed UIDs: recording bot needs its own uid distinct from participants.
RECORDING_UID = int(os.environ.get("RECORDING_UID", 999))

SMTP_HOST = os.environ["SMTP_HOST"]
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASSWORD = os.environ["SMTP_PASSWORD"]
FROM_EMAIL = os.environ.get("FROM_EMAIL", SMTP_USER)

AGORA_REST_BASE = f"https://api.agora.io/v1/apps/{AGORA_APP_ID}/cloud_recording"


def _agora_auth_header() -> dict:
    creds = f"{AGORA_CUSTOMER_ID}:{AGORA_CUSTOMER_SECRET}".encode("utf-8")
    return {
        "Authorization": f"Basic {base64.b64encode(creds).decode('utf-8')}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="OEM Remote Support - Session Service")
app.mount("/static", StaticFiles(directory="static"), name="static")


class CreateSessionRequest(BaseModel):
    oem_email: EmailStr
    repair_order_id: Optional[str] = None


class CreateSessionResponse(BaseModel):
    join_link: str
    oem_join_link: str
    channel_name: str
    recording_resource_id: Optional[str] = None
    recording_sid: Optional[str] = None
    recording_enabled: bool


def generate_channel_name(repair_order_id: Optional[str]) -> str:
    suffix = uuid.uuid4().hex[:12]
    if repair_order_id:
        return f"ro-{repair_order_id}-{suffix}"
    return f"session-{suffix}"


def generate_rtc_token(channel_name: str, uid: int) -> str:
    expire_at = int(time.time()) + TOKEN_EXPIRE_SECONDS
    # role=1 -> PUBLISHER (can send + receive audio/video)
    return RtcTokenBuilder.buildTokenWithUid(
        AGORA_APP_ID,
        AGORA_APP_CERTIFICATE,
        channel_name,
        uid,
        1,
        expire_at,
    )


def start_cloud_recording(channel_name: str) -> dict:
    """Acquire a recording resource, then start recording. Returns
    {resourceId, sid} which you need later to call the /stop endpoint."""

    recording_token = generate_rtc_token(channel_name, RECORDING_UID)

    # 1. Acquire
    acquire_resp = requests.post(
        f"{AGORA_REST_BASE}/acquire",
        headers=_agora_auth_header(),
        json={
            "cname": channel_name,
            "uid": str(RECORDING_UID),
            "clientRequest": {},
        },
        timeout=10,
    )
    if not acquire_resp.ok:
        logger.error("Agora acquire failed: %s", acquire_resp.text)
        raise HTTPException(status_code=502, detail="Failed to acquire recording resource")
    resource_id = acquire_resp.json()["resourceId"]

    # 2. Start (mix mode = single composed recording file; use "individual"
    # if you want separate files per participant)
    start_resp = requests.post(
        f"{AGORA_REST_BASE}/resourceid/{resource_id}/mode/mix/start",
        headers=_agora_auth_header(),
        json={
            "cname": channel_name,
            "uid": str(RECORDING_UID),
            "clientRequest": {
                "token": recording_token,
                "recordingConfig": {
                    "channelType": 0,  # communication mode (1:1 / small group)
                    "streamTypes": 2,  # audio + video
                    "maxIdleTime": 300,
                },
                "recordingFileConfig": {
                    "avFileType": ["hls", "mp4"],
                },
                # storageConfig omitted here on purpose: point this at your
                # own S3 bucket once you have it (vendor 1 = AWS S3). Until
                # then Agora stores it on its own temporary storage.
            },
        },
        timeout=10,
    )
    if not start_resp.ok:
        logger.error("Agora recording start failed: %s", start_resp.text)
        raise HTTPException(status_code=502, detail="Failed to start recording")

    sid = start_resp.json()["sid"]
    return {"resourceId": resource_id, "sid": sid}


def send_join_email(to_email: str, join_link: str, repair_order_id: Optional[str]) -> None:
    subject = "Remote support session - join link"
    ro_line = f"Repair Order: {repair_order_id}\n\n" if repair_order_id else ""
    body = (
        f"A mechanic has requested remote support.\n\n"
        f"{ro_line}"
        f"Join the live video session here:\n{join_link}\n\n"
        f"This link expires in {TOKEN_EXPIRE_SECONDS // 60} minutes."
    )
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = FROM_EMAIL
    msg["To"] = to_email

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(FROM_EMAIL, [to_email], msg.as_string())
    except Exception as exc:
        logger.error("Failed to send email: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to send email to OEM rep")


@app.post("/sessions", response_model=CreateSessionResponse)
async def create_session(req: CreateSessionRequest):
    channel_name = generate_channel_name(req.repair_order_id)

    # Different uids for mechanic and OEM rep so both can be in the
    # channel at the same time without conflicting.
    mechanic_uid = 1
    oem_uid = 2

    mechanic_token = generate_rtc_token(channel_name, mechanic_uid)
    oem_token = generate_rtc_token(channel_name, oem_uid)

    mechanic_join_link = (
        f"{JOIN_PAGE_BASE_URL}?channel={quote(channel_name)}"
        f"&token={quote(mechanic_token)}&uid={mechanic_uid}"
    )
    oem_join_link = (
        f"{JOIN_PAGE_BASE_URL}?channel={quote(channel_name)}"
        f"&token={quote(oem_token)}&uid={oem_uid}"
    )

    recording = start_cloud_recording(channel_name) if ENABLE_CLOUD_RECORDING else None
    send_join_email(req.oem_email, oem_join_link, req.repair_order_id)

    logger.info(f"DEBUG - mechanic join link: {mechanic_join_link}")
    logger.info(f"DEBUG - oem join link: {oem_join_link}")

    return CreateSessionResponse(
        join_link=mechanic_join_link,
        oem_join_link=oem_join_link,
        channel_name=channel_name,
        recording_resource_id=recording["resourceId"] if recording else None,
        recording_sid=recording["sid"] if recording else None,
        recording_enabled=ENABLE_CLOUD_RECORDING,
    )


@app.get("/health")
async def health():
    return {"status": "ok"}