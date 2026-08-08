"""
hachi_voice_server.py — Dedicated High-Speed WebSocket Voice Server
===================================================================
Runs on ws://127.0.0.1:5001/ws/voice.
Provides real-time full-duplex audio ingestion, STT, LLM streaming,
and fast TTS audio delivery with instant cancellation support.
"""

import asyncio
import json
import logging
import os
import sys
import tempfile
import time
import uuid
from typing import Set

import websockets

# Add current dir to sys.path
sys.path.insert(0, os.path.dirname(__file__))

from hachi_agent import process_agent_request_stream
from hachi_speech import generate_tts_audio
from hachi_whisper import transcribe_audio_file

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [VoiceServer] - %(levelname)s - %(message)s")

VOICE_PORT = 5001
ACTIVE_CLIENTS: Set = set()


async def handle_voice_client(websocket):
    """
    Handle a single client WebSocket connection.
    Supports real-time audio blob processing and text streaming.
    """
    ACTIVE_CLIENTS.add(websocket)
    logging.info(f"Client connected to Voice WebSocket. Total clients: {len(ACTIVE_CLIENTS)}")
    current_stream_task = None

    try:
        async for message in websocket:
            if isinstance(message, bytes):
                # Binary audio message (Blob from MediaRecorder / WebAudio)
                if len(message) < 500:
                    continue

                tmp_path = os.path.join(tempfile.gettempdir(), f"voice_input_{uuid.uuid4().hex[:8]}.webm")
                with open(tmp_path, "wb") as f:
                    f.write(message)

                try:
                    # Run whisper transcription in thread pool so asyncio loop remains unblocked
                    loop = asyncio.get_running_loop()
                    text = await loop.run_in_executor(None, transcribe_audio_file, tmp_path)
                finally:
                    if os.path.exists(tmp_path):
                        try:
                            os.remove(tmp_path)
                        except OSError:
                            pass

                if text and text.strip():
                    await websocket.send(json.dumps({"type": "stt", "text": text}))
                    # Cancel any prior running LLM response
                    if current_stream_task and not current_stream_task.done():
                        current_stream_task.cancel()

                    current_stream_task = asyncio.create_task(
                        stream_response_to_client(websocket, text)
                    )

            elif isinstance(message, str):
                # JSON text frame from frontend
                try:
                    data = json.loads(message)
                except Exception:
                    continue

                msg_type = data.get("type")

                if msg_type == "cancel" or msg_type == "interrupt":
                    logging.info("Instant cancel received over WebSocket.")
                    if current_stream_task and not current_stream_task.done():
                        current_stream_task.cancel()
                    await websocket.send(json.dumps({"type": "cancelled"}))

                elif msg_type == "chat":
                    user_text = data.get("text", "").strip()
                    mode = data.get("mode", "default")
                    if user_text:
                        if current_stream_task and not current_stream_task.done():
                            current_stream_task.cancel()

                        current_stream_task = asyncio.create_task(
                            stream_response_to_client(websocket, user_text, mode)
                        )

    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        logging.error(f"WebSocket client error: {e}")
    finally:
        ACTIVE_CLIENTS.remove(websocket)
        logging.info("Client disconnected from Voice WebSocket.")


async def stream_response_to_client(websocket, user_text: str, mode: str = "default"):
    """
    Stream LLM response tokens + pre-generated sentence audio buffers over WebSocket.
    """
    loop = asyncio.get_running_loop()
    token_buffer = ""
    full_text = ""
    tools_list = []
    engine = "qwen"
    pomo = None

    try:
        # Step 1: Run agent streaming in thread pool to prevent blocking asyncio loop
        def sync_generator():
            return list(process_agent_request_stream(user_text, mode, voice_mode=True))

        events = await loop.run_in_executor(None, sync_generator)

        for event in events:
            if event.get("done"):
                full_text = event.get("full", "")
                tools_list = event.get("tools", [])
                engine = event.get("engine", "qwen")
                pomo = event.get("pomo")
                break

            token = event.get("token", "")
            if token:
                token_buffer += token
                full_text += token
                await websocket.send(json.dumps({"type": "token", "text": token}))

                # Generate sentence audio eagerly when punctuation or 5+ words accumulate
                if any(p in token_buffer for p in ".!?\n") or len(token_buffer.split()) >= 6:
                    sentence = token_buffer.strip()
                    token_buffer = ""
                    if sentence:
                        audio_path = await loop.run_in_executor(None, generate_tts_audio, sentence)
                        if audio_path and os.path.exists(audio_path):
                            audio_url = f"/api/tts_file?path={os.path.basename(audio_path)}"
                            await websocket.send(json.dumps({
                                "type": "audio",
                                "sentence": sentence,
                                "url": audio_url
                            }))

        # Send tail sentence if remaining
        if token_buffer.strip():
            sentence = token_buffer.strip()
            audio_path = await loop.run_in_executor(None, generate_tts_audio, sentence)
            if audio_path and os.path.exists(audio_path):
                audio_url = f"/api/tts_file?path={os.path.basename(audio_path)}"
                await websocket.send(json.dumps({
                    "type": "audio",
                    "sentence": sentence,
                    "url": audio_url
                }))

        # Send completion frame
        await websocket.send(json.dumps({
            "type": "done",
            "full": full_text,
            "tools": tools_list,
            "engine": engine,
            "pomo": pomo
        }))

    except asyncio.CancelledError:
        logging.info("Response streaming cancelled.")
    except Exception as e:
        logging.error(f"stream_response_to_client error: {e}")


async def main():
    server = await websockets.serve(handle_voice_client, "127.0.0.1", VOICE_PORT)
    logging.info(f"🚀 Hachi Voice WebSocket Server running on ws://127.0.0.1:{VOICE_PORT}/ws/voice")
    await server.wait_closed()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Voice WebSocket server stopped.")
