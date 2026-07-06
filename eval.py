"""
Evaluation script: measures how accurate the Gemini triage model is.

Why this matters: in a real system you never just "trust" an LLM's output.
You build a small golden set (tickets where you already know the correct
answer) and periodically check the model against it. This catches:
- Prompt changes that accidentally break accuracy
- Model version upgrades that change behavior
- Silent drift over time

Run it with (backend must be running first):
    uv run python eval.py
"""

import time

import requests

API_URL = "http://127.0.0.1:8000/analyze"

# --- Golden test set ---
# Each entry: the ticket text, and the correct (human-labeled) answer.
# Keep this small and clear-cut on purpose — ambiguous cases make a bad eval set.
GOLDEN_SET = [
    {
        "text": "My order #4521 hasn't arrived in 10 days, I need a refund immediately",
        "expected_category": "delivery",
        "expected_priority": "urgent",
        "expected_sentiment": "frustrated",
    },
    {
        "text": "I can't login to my account, keeps saying invalid password even after reset",
        "expected_category": "account",
        "expected_priority": "high",
        "expected_sentiment": "frustrated",
    },
    {
        "text": "Just wanted to say the new update looks great, love the dark mode!",
        "expected_category": "feature-request",
        "expected_priority": "low",
        "expected_sentiment": "satisfied",
    },
    {
        "text": "Billing charged me twice this month, please fix this",
        "expected_category": "billing",
        "expected_priority": "high",
        "expected_sentiment": "frustrated",
    },
    {
        "text": "Can you add a feature to export my data as CSV?",
        "expected_category": "feature-request",
        "expected_priority": "low",
        "expected_sentiment": "neutral",
    },
    {
        "text": "This is the third time I'm contacting you about my missing package, I want a manager",
        "expected_category": "delivery",
        "expected_priority": "urgent",
        "expected_sentiment": "frustrated",
    },
    {
        "text": "The app crashes every time I try to upload a photo",
        "expected_category": "technical",
        "expected_priority": "high",
        "expected_sentiment": "frustrated",
    },
    {
        "text": "Your customer service replied really fast, thank you!",
        "expected_category": "feature-request",
        "expected_priority": "low",
        "expected_sentiment": "satisfied",
    },
]


def run_eval():
    total = len(GOLDEN_SET)
    category_correct = 0
    priority_correct = 0
    sentiment_correct = 0
    failures = []

    for i, case in enumerate(GOLDEN_SET, 1):
        print(f"[{i}/{total}] Testing: {case['text'][:50]}...", flush=True)
        time.sleep(1)  # small pause to stay under free-tier rate limits
        try:
            response = requests.post(API_URL, json={"text": case["text"]}, timeout=90)
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.HTTPError:
            # Show the actual error message from our backend, not just the status code.
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            print(f"  -> FAILED ({response.status_code})", flush=True)
            failures.append((case["text"], f"Request failed ({response.status_code}): {detail}"))
            continue
        except Exception as e:
            print(f"  -> FAILED: {e}", flush=True)
            failures.append((case["text"], f"Request failed: {e}"))
            continue

        print("  -> done", flush=True)

        cat_match = data.get("category") == case["expected_category"]
        pri_match = data.get("priority") == case["expected_priority"]
        sen_match = data.get("sentiment") == case["expected_sentiment"]

        category_correct += cat_match
        priority_correct += pri_match
        sentiment_correct += sen_match

        if not (cat_match and pri_match and sen_match):
            failures.append((
                case["text"],
                f"Expected: category={case['expected_category']}, "
                f"priority={case['expected_priority']}, sentiment={case['expected_sentiment']} | "
                f"Got: category={data.get('category')}, priority={data.get('priority')}, "
                f"sentiment={data.get('sentiment')}",
            ))

    # --- Report ---
    print("=" * 60)
    print(f"EVAL RESULTS ({total} test cases)")
    print("=" * 60)
    print(f"Category accuracy:  {category_correct}/{total} ({category_correct/total*100:.0f}%)")
    print(f"Priority accuracy:  {priority_correct}/{total} ({priority_correct/total*100:.0f}%)")
    print(f"Sentiment accuracy: {sentiment_correct}/{total} ({sentiment_correct/total*100:.0f}%)")

    if failures:
        print("\n--- Mismatches ---")
        for text, detail in failures:
            print(f"\nTicket: {text}")
            print(f"  {detail}")
    else:
        print("\nAll test cases matched expected labels.")


if __name__ == "__main__":
    run_eval()