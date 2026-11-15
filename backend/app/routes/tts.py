from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.database.models import User
from app.dependencies import get_current_user
from app.rate_limit import limiter
from app.services import tts_service

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
