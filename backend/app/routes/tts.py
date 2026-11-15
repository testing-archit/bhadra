import asyncio
import base64
import hashlib
from collections import OrderedDict

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.database.models import User
from app.dependencies import get_current_user
from app.rate_limit import limiter
from app.config import settings
from app.services import gemini_service, tts_service, usage_ledger

router = APIRouter(prefix="/api/tts", tags=["speech"])


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    language: str | None = None


@router.post("")
@limiter.limit("30/minute")
async def speak(request: Request, body: SpeechRequest, user: User = Depends(get_current_user)) -> Response:
    """Read text aloud with Gnani Timbre. Returns MP3 audio."""
    try:
        audio = await tts_service.synthesize(body.text, body.language)
    except tts_service.SpeechNotConfigured as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail="Wilco couldn't read this aloud right now. Try again.") from error
    return Response(content=audio, media_type="audio/mpeg", headers={"Cache-Control": "private, max-age=86400"})


# Languages a summary can be heard in, and what to ask the translator for.
LISTEN_LANGUAGES = {
    "en-IN": "English", "hi-en": "Hinglish (Hindi and English mixed, in Roman script)", "hi-IN": "Hindi, in Devanagari script",
    "ta-IN": "Tamil, in Tamil script", "te-IN": "Telugu, in Telugu script", "kn-IN": "Kannada, in Kannada script",
    "ml-IN": "Malayalam, in Malayalam script", "mr-IN": "Marathi, in Devanagari script", "bn-IN": "Bengali, in Bengali script",
    "gu-IN": "Gujarati, in Gujarati script", "pa-IN": "Punjabi, in Gurmukhi script",
}
TRANSLATE_PROMPT = """Translate the meeting notes you are given into {language}, to be read aloud.
Keep every name, number, date, product and company name exactly as written.
Write plain sentences only: no markdown, bullets, headings or emoji.
Keep it natural and spoken, as a colleague would say it. Return only the translation."""
_translations: OrderedDict[tuple[str, str], str] = OrderedDict()


class TranslatedSpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=6_000)
    language: str = Field(min_length=2, max_length=8)


def _translate(text: str, language: str) -> str:
    key = (hashlib.sha256(text.encode()).hexdigest(), language)
    if key in _translations:
        _translations.move_to_end(key)
        return _translations[key]
    translated, _ = gemini_service.generate_text(
        TRANSLATE_PROMPT.format(language=LISTEN_LANGUAGES[language]), text,
        max_output_tokens=1500, temperature=0.2, thinking_budget=0, feature="speech_translation",
        model=settings.gemini_fast_model, timeout_seconds=20,
    )
    translated = translated.strip()
    if translated:
        _translations[key] = translated
        while len(_translations) > 256:
            _translations.popitem(last=False)
    return translated


@router.post("/translated")
@limiter.limit("20/minute")
async def speak_translated(request: Request, body: TranslatedSpeechRequest, user: User = Depends(get_current_user)) -> dict:
    """Notes read aloud in an Indian language of the listener's choice:
    Gemini translates, Gnani Timbre speaks. Returns the text it read too."""
    if body.language not in LISTEN_LANGUAGES:
        raise HTTPException(status_code=422, detail="Pick one of the listed languages.")
    usage_ledger.attribute(user_id=user.id)
    text = body.text
    if not (body.language == "en-IN" and body.text.isascii()):
        try:
            text = await asyncio.to_thread(_translate, body.text, body.language) or body.text
        except Exception as error:
            raise HTTPException(status_code=502, detail="Wilco couldn't translate this right now. Try again.") from error
    # The translation is useful on its own: keep it even if speech fails.
    try:
        audio = base64.b64encode(await tts_service.synthesize(text, body.language)).decode()
        speech_error = None
    except Exception:
        audio, speech_error = None, "Couldn't play the audio right now. Here's the text."
    model, voice = tts_service.voice_for(body.language)
    return {"language": body.language, "text": text, "audio": audio, "speech_error": speech_error,
            "translated": text != body.text, "model": model, "voice": voice}
