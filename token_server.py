import os
import random

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from livekit import api

load_dotenv()

ROOM_NAME = "voice-agent-demo"

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/token")
def get_token() -> dict:
    identity = f"user-{random.randint(1000, 9999)}"
    token = (
        api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
        .with_identity(identity)
        .with_grants(api.VideoGrants(room_join=True, room=ROOM_NAME))
        .to_jwt()
    )
    return {
        "token": token,
        "url": os.environ["LIVEKIT_URL"],
        "room": ROOM_NAME,
        "identity": identity,
    }
