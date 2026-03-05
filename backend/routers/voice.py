"""Voice router — Nova Sonic bidirectional speech."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio, json, os, sys, base64, boto3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logger import get_logger

log = get_logger(__name__)
router = APIRouter()


@router.websocket("/ws")
async def voice_websocket(websocket: WebSocket):
    """
    Bidirectional WebSocket for Nova Sonic voice interaction.

    Client sends: { "type": "audio_chunk", "data": "<base64 PCM>" }
    Server sends: { "type": "transcript", "text": "..." }
                  { "type": "audio_response", "data": "<base64 PCM>" }
                  { "type": "done" }

    Nova Sonic handles:
    - Speech-to-text (user speaks route / product name)
    - Text-to-speech (announces the winner)
    - Barge-in (user can interrupt the announcement)
    """
    await websocket.accept()
    log.info("Voice WebSocket connected")

    bedrock = boto3.client(
        "bedrock-runtime",
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
    )

    try:
        # Nova Sonic bidirectional streaming
        # See: https://docs.aws.amazon.com/nova/latest/userguide/speech.html
        async for message in websocket.iter_json():
            msg_type = message.get("type")

            if msg_type == "speak":
                text = message.get("text", "")
                log.info("TTS request: text='%s'", text[:80])
                await _speak(websocket, bedrock, text)

            elif msg_type == "listen":
                # STT: stream audio chunks back as transcript
                # In practice, browser Web Speech API handles this client-side
                # This endpoint is for mobile PWA fallback
                await websocket.send_json({
                    "type":    "info",
                    "message": "Use Web Speech API on client for STT"
                })

    except WebSocketDisconnect:
        log.info("Voice WebSocket disconnected")
    except Exception as e:
        log.error("Voice WebSocket error: %s", e)
        await websocket.send_json({"type": "error", "message": str(e)})
    finally:
        await websocket.close()


async def _speak(websocket: WebSocket, bedrock, text: str):
    """
    Call Nova Sonic to convert text to speech and stream audio back.
    Nova Sonic uses invoke_model_with_response_stream for TTS.
    """
    try:
        body = {
            "inputText": text,
            "voiceConfig": {
                "language": "en-IN",
                "voiceId":  "Raveena",   # Indian English voice
                "engine":   "neural",
            },
            "audioConfig": {
                "audioType": "AUDIO",
                "codec":     "PCM",
                "sampleRate": 16000,
            },
        }

        # Nova Sonic TTS (model ID TBD — using Amazon Polly as fallback for hackathon)
        polly = boto3.client("polly", region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
        response = polly.synthesize_speech(
            Text=text,
            VoiceId="Aditi",       # Indian English
            OutputFormat="mp3",
            Engine="neural",
        )

        audio_bytes = response["AudioStream"].read()
        audio_b64   = base64.b64encode(audio_bytes).decode()

        await websocket.send_json({
            "type":   "audio_response",
            "format": "mp3",
            "data":   audio_b64,
        })
        await websocket.send_json({"type": "done"})

    except Exception as e:
        log.error("TTS failed, falling back to text: %s", e)
        # Fallback: just send transcript for client-side TTS
        await websocket.send_json({
            "type":    "text_fallback",
            "text":    text,
            "message": f"TTS unavailable: {e}",
        })
        await websocket.send_json({"type": "done"})
