"""
KPI Intelligence — stakeholder demo chat UI

A Streamlit chat interface that lets anyone query the KPI monitoring system
via Claude + MCP, without needing Claude desktop or Claude Code.

Secrets required (add in Render dashboard or .streamlit/secrets.toml locally):
    ANTHROPIC_API_KEY = "sk-ant-..."
    MCP_SERVER_URL    = "https://kpi-monitor.railway.app/sse"
"""

from __future__ import annotations

import streamlit as st
import anthropic

# ── Config ────────────────────────────────────────────────────────────────────

MODEL = "claude-opus-4-8"
MAX_TOKENS = 8096
MCP_BETA = "mcp-client-2025-04-04"

SUGGESTED_QUESTIONS = [
    "What's wrong today?",
    "Why are net flows down?",
    "Which KPIs improved this week?",
]

DOMAINS = ["All", "Broking", "Wealth", "Clients"]

SYSTEM_BASE = """You are a senior BI analyst at a broking and wealth management firm.
You have access to live KPI data via tools. When the user asks about KPI performance,
anomalies, or trends, always call the relevant tools to ground your answer in actual data.
Keep responses concise and business-focused. Use INR crores for currency where relevant."""

DOMAIN_ADDENDUM = {
    "Broking": "\nFocus this session on Broking KPIs: equity volume, derivatives volume, brokerage revenue, active clients.",
    "Wealth":  "\nFocus this session on Wealth KPIs: AUM, net flows, redemption rate, SIP book.",
    "Clients": "\nFocus this session on Client KPIs: new accounts, activation rate, churn rate.",
}

# ── Page setup ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="KPI Intelligence",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
/* Header */
.kpi-header {
    display: flex;
    align-items: center;
    gap: 12px;
    padding-bottom: 8px;
    border-bottom: 1px solid rgba(0,0,0,0.08);
    margin-bottom: 16px;
}
.kpi-logo {
    width: 36px;
    height: 36px;
    border-radius: 8px;
    background: #185FA5;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 20px;
    flex-shrink: 0;
}
.kpi-title { font-size: 20px; font-weight: 600; margin: 0; }
.kpi-sub   { font-size: 13px; color: #888; margin: 0; }

/* Tool pills */
.tool-pills { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.tool-pill {
    display: inline-block;
    font-size: 11px;
    padding: 2px 10px;
    border-radius: 20px;
    background: #f0f4f8;
    color: #555;
    border: 1px solid #dde3ea;
}

/* Suggested question buttons */
div[data-testid="column"] .stButton > button {
    width: 100%;
    text-align: left;
    font-size: 13px;
    border-radius: 20px;
    padding: 6px 16px;
    border: 1px solid #dde3ea;
    background: white;
    color: #333;
}
div[data-testid="column"] .stButton > button:hover {
    background: #e8f0fb;
    border-color: #a8c4e8;
    color: #185FA5;
}
</style>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────

if "messages" not in st.session_state:
    st.session_state.messages = []
if "domain" not in st.session_state:
    st.session_state.domain = "All"
if "pending_input" not in st.session_state:
    st.session_state.pending_input = None

# ── Client ────────────────────────────────────────────────────────────────────

@st.cache_resource
def get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])


def get_mcp_url() -> str:
    return st.secrets.get("MCP_SERVER_URL", "https://kpi-monitor.railway.app/sse")

# ── Header ────────────────────────────────────────────────────────────────────

header_col, domain_col = st.columns([3, 2])

with header_col:
    st.markdown("""
    <div class="kpi-header">
        <div class="kpi-logo">📊</div>
        <div>
            <p class="kpi-title">KPI Intelligence</p>
            <p class="kpi-sub">Powered by Claude + live KPI data</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

with domain_col:
    selected = st.radio(
        "Domain focus",
        DOMAINS,
        index=DOMAINS.index(st.session_state.domain),
        horizontal=True,
        label_visibility="collapsed",
    )
    if selected != st.session_state.domain:
        st.session_state.domain = selected

# ── Suggested questions ───────────────────────────────────────────────────────

cols = st.columns(3)
for i, (col, q) in enumerate(zip(cols, SUGGESTED_QUESTIONS)):
    with col:
        if st.button(q, key=f"sq_{i}"):
            st.session_state.pending_input = q

st.divider()

# ── Chat history ──────────────────────────────────────────────────────────────

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg.get("tools"):
            pills = "".join(
                f'<span class="tool-pill">⚙ {t}</span>' for t in msg["tools"]
            )
            st.markdown(
                f'<div class="tool-pills">{pills}</div>',
                unsafe_allow_html=True,
            )
        st.markdown(msg["content"])

# ── Input & response ──────────────────────────────────────────────────────────

user_input = st.chat_input("Ask about any KPI, region, or anomaly…")

if st.session_state.pending_input:
    user_input = st.session_state.pending_input
    st.session_state.pending_input = None

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    system_prompt = SYSTEM_BASE + DOMAIN_ADDENDUM.get(st.session_state.domain, "")

    api_messages = [
        {"role": m["role"], "content": m["content"]}
        for m in st.session_state.messages
    ]

    with st.chat_message("assistant"):
        with st.spinner("Analysing KPI data…"):
            try:
                client = get_client()
                response = client.messages.create(
                    model=MODEL,
                    max_tokens=MAX_TOKENS,
                    system=system_prompt,
                    messages=api_messages,
                    extra_headers={"anthropic-beta": MCP_BETA},
                    extra_body={"mcp_servers": [{"type": "url", "url": get_mcp_url(), "name": "kpi-monitor"}]},
                )

                tool_names = [
                    block.name
                    for block in response.content
                    if block.type == "tool_use"
                ]
                reply_text = " ".join(
                    block.text
                    for block in response.content
                    if block.type == "text"
                ).strip()

                if not reply_text:
                    reply_text = "_No response text returned. The MCP server may be unavailable._"

            except Exception as exc:
                tool_names = []
                reply_text = f"⚠ Error calling Claude API: `{exc}`"

        if tool_names:
            pills = "".join(
                f'<span class="tool-pill">⚙ {t}</span>' for t in tool_names
            )
            st.markdown(
                f'<div class="tool-pills">{pills}</div>',
                unsafe_allow_html=True,
            )

        st.markdown(reply_text)

    st.session_state.messages.append({
        "role": "assistant",
        "content": reply_text,
        "tools": tool_names,
    })

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### About")
    st.markdown(
        "Ask questions in plain English. Claude calls live KPI tools and "
        "reasons over your firm's data to answer."
    )
    st.markdown("**Tools available**")
    st.markdown("- `detect_anomalies`\n- `get_kpi_data`\n- `get_kpi_summary`\n- `list_kpis`")
    st.divider()
    if st.button("Clear conversation"):
        st.session_state.messages = []
        st.rerun()
