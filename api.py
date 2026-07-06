
import os
import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import ServerError, ClientError

load_dotenv()

if not os.getenv("GOOGLE_API_KEY"):
    raise RuntimeError(
        "GOOGLE_API_KEY not found. Copy sample.env to .env and add your key "
        "(get a free one at https://aistudio.google.com)."
    )

client = genai.Client()

app = FastAPI()


# What the caller must SEND us
class Ticket(BaseModel):
    text: str


# What Gemini gives back, and what we SEND to the caller.
class Analysis(BaseModel):
    category: str          # "billing", "technical", "delivery", "account", "feature-request"
    priority: str           # "urgent", "high", "medium", "low"
    sentiment: str          # "frustrated", "neutral", "satisfied"
    suggested_reply: str    # a short draft reply, 1-2 sentences


def call_gemini_with_retry(prompt: str, max_retries: int = 3):
    """
    Gemini can fail transiently in two ways:
    - ServerError (503): the model is overloaded.
    - ClientError with status 429: you've hit the free-tier rate limit
      (e.g. more than ~10 requests/minute on Gemini 2.5 Flash).
    Both are worth retrying with a short wait instead of failing immediately.
    """
    for attempt in range(max_retries):
        try:
            return client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=Analysis,
                ),
            )
        except ServerError:
            if attempt == max_retries - 1:
                raise
            time.sleep(2 * (attempt + 1))  # 2s, 4s, 6s
        except ClientError as e:
            is_rate_limit = getattr(e, "code", None) == 429 or "429" in str(e)
            if not is_rate_limit or attempt == max_retries - 1:
                raise
            # Rate limit hit — wait longer since the free-tier window is per-minute.
            time.sleep(15 * (attempt + 1))  # 15s, 30s, 45s
    raise RuntimeError("Unreachable")  # safety net, loop always returns or raises


@app.post("/analyze")
def analyze(ticket: Ticket):
    prompt = (
        "You are a support ticket triage assistant.\n"
        "Analyze this customer support ticket and return:\n"
        "category: one of 'billing', 'technical', 'delivery', 'account', 'feature-request'.\n"
        "priority: one of 'urgent', 'high', 'medium', 'low'. Use these strict definitions:\n"
        "  - urgent: the customer has NO way to use the product/service at all right now "
        "(e.g. total outage, security breach), OR they are explicitly escalating — asking "
        "for a manager, saying this is a repeated/Nth contact about the same issue, "
        "threatening legal action or to cancel/leave, OR a paid delivery is significantly "
        "overdue and they are demanding an immediate refund.\n"
        "  - high: a real problem that needs fixing soon but there is no explicit escalation "
        "and the customer isn't fully blocked (e.g. incorrect billing, a failed login without "
        "escalation language, a moderately late delivery with no refund demand).\n"
        "  - medium: a minor bug or inconvenience with an easy workaround.\n"
        "  - low: positive feedback or a feature request, nothing broken.\n"
        "sentiment: one of 'frustrated', 'neutral', 'satisfied'.\n"
        "If the ticket is positive feedback with no problem to fix, use category "
        "'feature-request', priority 'low', and sentiment 'satisfied'.\n"
        "suggested_reply: a short, polite, 1-2 sentence draft reply to send the customer.\n"
        f"Ticket: {ticket.text}"
    )

    try:
        response = call_gemini_with_retry(prompt)
    except ServerError:
        raise HTTPException(
            status_code=503,
            detail="Gemini is currently overloaded. Please try again in a moment.",
        )
    except ClientError as e:
        raise HTTPException(
            status_code=429,
            detail=f"Gemini rate limit hit (free tier allows ~10 requests/minute). "
                   f"Wait a minute and try again. Details: {e}",
        )
    except Exception as e:
        # Catch anything else (network issues, unexpected API errors, etc.)
        # so the client always gets a clean JSON error instead of a raw crash.
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error while analyzing ticket: {e}",
        )

    if response.parsed is None:
        # Happens rarely if Gemini's output didn't match our schema
        # (e.g. blocked by a safety filter, or an empty response).
        raise HTTPException(
            status_code=502,
            detail="Model did not return a valid structured response for this ticket.",
        )

    return response.parsed