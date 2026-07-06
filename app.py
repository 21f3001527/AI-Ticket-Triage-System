"""
Frontend: a Streamlit dashboard for support agents.

Run it with (backend must already be running in another terminal):
    uv run streamlit run app.py
"""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import streamlit as st

from database import init_db, save_results, load_history

API_URL = "http://127.0.0.1:8000/analyze"
MAX_TICKET_LENGTH = 2000  # guard against accidental huge pastes

st.set_page_config(page_title="Ticket Triage", layout="wide")
init_db()

st.markdown(
    """
    <h1 style="background: linear-gradient(90deg, #7C5CFC, #4EA8FF);
               -webkit-background-clip: text; -webkit-text-fill-color: transparent;
               font-size: 2.4em; margin-bottom: 0;">
        🎫 AI Support Ticket Triage
    </h1>
    """,
    unsafe_allow_html=True,
)
st.caption("Paste tickets (one per line), analyze, and route by priority.")

# --- Step 1: Input ---
tickets_text = st.text_area(
    "Paste tickets here (one per line):",
    height=180,
    placeholder="My order #4521 hasn't arrived in 10 days, I need a refund immediately\n"
                "I can't login to my account, keeps saying invalid password\n"
                "Just wanted to say the new update looks great!",
)

if st.button("Analyze tickets", type="primary"):
    raw_tickets = [t.strip() for t in tickets_text.split("\n") if t.strip()]

    # --- Input validation ---
    tickets = []
    skipped = 0
    for t in raw_tickets:
        if len(t) > MAX_TICKET_LENGTH:
            skipped += 1
        else:
            tickets.append(t)

    if skipped:
        st.warning(f"Skipped {skipped} ticket(s) longer than {MAX_TICKET_LENGTH} characters.")

    if not tickets:
        st.warning("Paste at least one valid ticket first.")
    else:
        def analyze_one(ticket_text: str):
            try:
                response = requests.post(API_URL, json={"text": ticket_text}, timeout=90)
                response.raise_for_status()
                data = response.json()
                return {
                    "ticket_text": ticket_text,
                    "category": data["category"],
                    "priority": data["priority"],
                    "sentiment": data["sentiment"],
                    "suggested_reply": data["suggested_reply"],
                }
            except requests.exceptions.ConnectionError:
                return {
                    "ticket_text": ticket_text,
                    "category": "error", "priority": "error", "sentiment": "error",
                    "suggested_reply": "Backend not reachable — is api.py running?",
                }
            except Exception:
                return {
                    "ticket_text": ticket_text,
                    "category": "error", "priority": "error", "sentiment": "error",
                    "suggested_reply": "Could not analyze this ticket. Try again.",
                }

        results = [None] * len(tickets)
        progress = st.progress(0, text="Analyzing tickets...")
        done = 0

        # Run tickets concurrently instead of one-by-one — much faster for batches.
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_index = {
                executor.submit(analyze_one, ticket): i for i, ticket in enumerate(tickets)
            }
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                results[index] = future.result()
                done += 1
                progress.progress(done / len(tickets), text=f"Analyzed {done}/{len(tickets)}")

        # Auto-save immediately after analysis — no separate save step needed.
        save_results(results)
        st.session_state["results"] = results
        st.session_state["just_saved_count"] = len(results)

# --- Step 2: Show results ---
PRIORITY_COLOR = {
    "urgent": "#ff4b4b", "high": "#ff9d45", "medium": "#f0d43a",
    "low": "#3dd56d", "error": "#888888",
}
PRIORITY_EMOJI = {
    "urgent": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢", "error": "⚪",
}

if "results" in st.session_state:
    results = st.session_state["results"]

    # --- Summary metric cards ---
    total = len(results)
    urgent_count = sum(1 for r in results if r["priority"] == "urgent")
    frustrated_count = sum(1 for r in results if r["sentiment"] == "frustrated")
    top_category = Counter(r["category"] for r in results).most_common(1)
    top_category_name = top_category[0][0] if top_category else "-"

    st.markdown(
        """
        <style>
        div[data-testid="stMetric"] {
            background: linear-gradient(135deg, rgba(124,92,252,0.12), rgba(78,168,255,0.08));
            border: 1px solid rgba(124,92,252,0.3);
            border-radius: 10px;
            padding: 12px 16px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total tickets", total)
    m2.metric("🔴 Urgent", urgent_count)
    m3.metric("😠 Frustrated", frustrated_count)
    m4.metric("Top category", top_category_name)

    st.divider()

    left, right = st.columns([3, 2])

    with left:
        st.subheader("Results")
        # Sort so urgent tickets show first
        priority_rank = {"urgent": 0, "high": 1, "medium": 2, "low": 3, "error": 4}
        sorted_results = sorted(results, key=lambda r: priority_rank.get(r["priority"], 5))

        for r in sorted_results:
            color = PRIORITY_COLOR.get(r["priority"], "#888888")
            emoji = PRIORITY_EMOJI.get(r["priority"], "⚪")

            st.markdown(
                f"""
                <div style="border-left: 4px solid {color}; padding: 10px 14px;
                            margin-bottom: 8px; background-color: rgba(255,255,255,0.03);
                            border-radius: 4px;">
                    <b>{emoji} {r['priority'].upper()}</b> · {r['category']} · {r['sentiment']}
                    <br><span style="opacity:0.85;">{r['ticket_text']}</span>
                    <br><i style="opacity:0.7;">↳ {r['suggested_reply']}</i>
                </div>
                """,
                unsafe_allow_html=True,
            )

    with right:
        st.subheader("Tickets by category")
        counts = Counter(r["category"] for r in results)
        st.bar_chart(counts)

        st.subheader("Tickets by priority")
        priority_counts = Counter(r["priority"] for r in results)
        st.bar_chart(priority_counts)

    if st.session_state.get("just_saved_count"):
        st.success(f"✅ {st.session_state['just_saved_count']} ticket(s) automatically saved to the queue.")
        st.session_state["just_saved_count"] = None  # only show once, right after analysis

# --- Step 3: Saved history with priority filter ---
st.divider()
st.subheader("📋 Saved ticket queue")

filter_choice = st.selectbox(
    "Filter by priority:",
    ["all", "urgent", "high", "medium", "low"],
)

history = load_history(priority_filter=filter_choice)

if history:
    # --- CSV export ---
    import csv
    import io

    csv_buffer = io.StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerow(["ticket_text", "category", "priority", "sentiment", "suggested_reply", "created_at"])
    writer.writerows(history)

    st.download_button(
        label="⬇️ Export to CSV",
        data=csv_buffer.getvalue(),
        file_name=f"tickets_{filter_choice}.csv",
        mime="text/csv",
    )

    for ticket_text, category, priority, sentiment, suggested_reply, created_at in history:
        color = PRIORITY_COLOR.get(priority, "#888888")
        emoji = PRIORITY_EMOJI.get(priority, "⚪")
        st.markdown(
            f"""
            <div style="border-left: 4px solid {color}; padding: 10px 14px;
                        margin-bottom: 8px; background-color: rgba(255,255,255,0.03);
                        border-radius: 4px;">
                <b>{emoji} {priority.upper()}</b> · {category} · {sentiment}
                <span style="opacity:0.6; font-size: 0.85em;"> · {created_at}</span>
                <br><span style="opacity:0.85;">{ticket_text}</span>
                <br><i style="opacity:0.7;">↳ {suggested_reply}</i>
            </div>
            """,
            unsafe_allow_html=True,
        )
else:
    st.info("No saved tickets yet for this filter.")