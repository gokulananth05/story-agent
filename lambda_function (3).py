"""Bedtime story agent, running on AWS Lambda.

Input  (JSON): {"idea": "a lion who is afraid of the dark", "minutes": 5,
                "language": "en", "code": "<passcode>"}
Output (JSON): {"audio_url": "...", "words": 436, "language": "en", "parts": ["...", "...", "..."]}
"""
import hmac
import json
import os
import re
import uuid
from xml.sax.saxutils import escape

import boto3
from botocore.config import Config

REGION = "us-east-1"
MODEL_ID = "us.amazon.nova-lite-v1:0"   # use the same ID that worked on your laptop
BUCKET_NAME = os.environ["BUCKET_NAME"]  # set in Lambda > Configuration > Environment variables
ACCESS_CODE = os.environ.get("ACCESS_CODE", "")  # the passcode people must send with a request

# One entry per language the page offers.
#   write_in = how the model is told to write
#   voice / polly_lang = which Polly voice narrates it
#   wpm = words per minute for that language (tune by timing your own audio)
LANGUAGES = {
    "en": {"write_in": "English", "voice": "Joanna", "polly_lang": "en-US", "wpm": 100},
    "hi": {"write_in": "Hindi, using Devanagari script", "voice": "Kajal",
           "polly_lang": "hi-IN", "wpm": 100},
}
DEFAULT_LANGUAGE = "en"

MAX_RETRIES = 2
MIN_LENGTH_RATIO = 0.85

# Limits protect your credits from very long or very many requests.
MAX_IDEA_CHARS = 100
MIN_MINUTES, MAX_MINUTES = 1, 10

PARTS = [
    {"name": "opening", "share": 0.35, "rate": "slow", "pause_ms": 300,
     "style": "Gentle and curious. Introduce the main character and the setting."},
    {"name": "middle", "share": 0.40, "rate": "slow", "pause_ms": 700,
     "style": "Warm and slow. A small, safe adventure with a kind surprise."},
    {"name": "winding down", "share": 0.25, "rate": "x-slow", "pause_ms": 1300,
     "style": "Very quiet and sleepy. Everyone gets cozy and yawns. "
              "End with a soft goodnight."},
]

# Created once when Lambda starts, and reused on later calls (faster).
bedrock = boto3.client("bedrock-runtime", region_name=REGION)
polly = boto3.client("polly", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION, config=Config(signature_version="s3v4"))


def system_prompt(lang: dict) -> str:
    return (
        "You are a gentle bedtime storyteller for children aged 5 and under. "
        f"Write the story in {lang['write_in']}. "
        "Use short, simple sentences and soft, familiar words. "
        "Never include anything scary, violent or sad. "
        "Return only the story text, with no titles, labels or notes."
    )


def ask_model(prompt: str, lang: dict) -> str:
    response = bedrock.converse(
        modelId=MODEL_ID,
        system=[{"text": system_prompt(lang)}],
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 2000, "temperature": 0.7},
    )
    return response["output"]["message"]["content"][0]["text"].strip()


def count_words(text: str) -> int:
    return len(text.split())


def write_part(idea: str, part: dict, target: int, story_so_far: str, lang: dict) -> str:
    prompt = (
        f"We are writing a bedtime story about {idea}, in 3 parts.\n"
        f"Story so far:\n{story_so_far or '(nothing yet)'}\n\n"
        f"Now write ONLY the next part: the {part['name']}.\n"
        f"Target length: about {target} words.\n"
        f"Style: {part['style']}"
    )
    text = ask_model(prompt, lang)
    for _ in range(MAX_RETRIES):
        if count_words(text) >= target * MIN_LENGTH_RATIO:
            break
        text = ask_model(
            f"Here is part of a bedtime story:\n\n{text}\n\n"
            f"Rewrite it to be about {target} words long by adding calm, "
            "gentle details. Keep the same style, the same language and the "
            "same ending. Return only the rewritten text.",
            lang,
        )
    return text


def write_story(idea: str, minutes: int, lang: dict) -> list[str]:
    total_words = minutes * lang["wpm"]
    parts: list[str] = []
    for cfg in PARTS:
        target = int(total_words * cfg["share"])
        parts.append(write_part(idea, cfg, target, "\n\n".join(parts), lang))
    return parts


def to_ssml(text: str, rate: str, pause_ms: int) -> str:
    # Sentences end with . ! ? or the Hindi full stop "।"
    sentences = re.split(r"(?<=[.!?।])\s+", text.strip())
    pause = f'<break time="{pause_ms}ms"/>'
    body = pause.join(escape(s) for s in sentences)
    return f'<speak><prosody rate="{rate}">{body}</prosody></speak>'


def narrate(parts: list[str], lang: dict) -> bytes:
    audio = b""
    for i, text in enumerate(parts):
        cfg = PARTS[min(i, len(PARTS) - 1)]
        response = polly.synthesize_speech(
            Text=to_ssml(text, cfg["rate"], cfg["pause_ms"]),
            TextType="ssml",
            OutputFormat="mp3",
            VoiceId=lang["voice"],
            LanguageCode=lang["polly_lang"],
            Engine="neural",
        )
        audio += response["AudioStream"].read()
    return audio


def save_and_link(audio: bytes) -> str:
    """Save the mp3 in S3 and return a temporary link that lets one person play it."""
    key = f"stories/{uuid.uuid4()}.mp3"
    s3.put_object(Bucket=BUCKET_NAME, Key=key, Body=audio, ContentType="audio/mpeg")
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": BUCKET_NAME, "Key": key},
        ExpiresIn=3600,  # one hour
    )


def reply(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def lambda_handler(event, context):
    # A web request puts the data in event["body"] as text.
    # A test in the Lambda console passes the data directly in event.
    body = event.get("body")
    data = json.loads(body) if isinstance(body, str) else (body or event)

    # Check the passcode first. If no code is configured, refuse everything.
    given = str(data.get("code", ""))
    if not ACCESS_CODE or not hmac.compare_digest(ACCESS_CODE.encode(), given.encode()):
        return reply(401, {"error": "That passcode doesn't look right. Please check it and try again."})

    idea = str(data.get("idea", "")).strip()[:MAX_IDEA_CHARS]
    if not idea:
        return reply(400, {"error": "Please tell me what the story should be about."})
    try:
        minutes = int(data.get("minutes", 3))
    except (TypeError, ValueError):
        return reply(400, {"error": "Minutes must be a number."})
    minutes = max(MIN_MINUTES, min(MAX_MINUTES, minutes))

    language = str(data.get("language", DEFAULT_LANGUAGE))
    if language not in LANGUAGES:
        return reply(400, {"error": "That language isn't available yet."})
    lang = LANGUAGES[language]

    try:
        parts = write_story(idea, minutes, lang)
        audio_url = save_and_link(narrate(parts, lang))
    except Exception as error:
        print(f"Story failed: {error}")  # shows up in CloudWatch logs
        return reply(500, {"error": "Sorry, the storyteller fell asleep. Please try again."})

    return reply(200, {
        "audio_url": audio_url,
        "words": sum(count_words(p) for p in parts),
        "language": language,
        "parts": parts,
    })
