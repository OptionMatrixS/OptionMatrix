"""quiz.py — Tab 9: NISM-style practice quiz (uses quiz_data.QUESTIONS)."""

from __future__ import annotations

import random

import streamlit as st

import styles
from quiz_data import QUESTIONS

P = styles.PALETTE


def _topics():
    return ["All"] + sorted({q["topic"] for q in QUESTIONS})


def render(user):
    st.caption("Practice questions to reinforce core concepts. These are "
               "original study questions, not actual NISM exam items.")

    c = st.columns([1.3, 1, 1])
    topic = c[0].selectbox("Topic", _topics(), key="qz_topic")
    pool = [q for q in QUESTIONS if topic == "All" or q["topic"] == topic]
    n = c[1].number_input("Questions", 1, len(pool), min(10, len(pool)),
                          key="qz_n")
    if c[2].button("🎯 Start / Restart", key="qz_start"):
        idxs = list(range(len(pool)))
        random.shuffle(idxs)
        st.session_state["qz_set"] = [pool[i] for i in idxs[:int(n)]]
        st.session_state["qz_submitted"] = False
        for k in list(st.session_state.keys()):
            if k.startswith("qz_ans_"):
                del st.session_state[k]

    qs = st.session_state.get("qz_set")
    if not qs:
        st.info("Choose a topic and press **Start**.")
        return

    submitted = st.session_state.get("qz_submitted", False)

    st.markdown(styles.section(f"{len(qs)} questions"), unsafe_allow_html=True)
    for i, q in enumerate(qs):
        st.markdown(f"**Q{i+1}. {q['q']}**")
        st.radio("Select", q["options"], key=f"qz_ans_{i}", index=None,
                 label_visibility="collapsed", disabled=submitted)
        if submitted:
            chosen = st.session_state.get(f"qz_ans_{i}")
            correct = q["options"][q["answer"]]
            if chosen == correct:
                st.markdown(f"<span style='color:{P['GREEN']};'>✓ Correct</span> "
                            f"— {q['exp']}", unsafe_allow_html=True)
            else:
                st.markdown(
                    f"<span style='color:{P['RED']};'>✗ Incorrect.</span> "
                    f"Answer: <b>{correct}</b> — {q['exp']}",
                    unsafe_allow_html=True)
        st.markdown("---")

    if not submitted:
        if st.button("✅ Submit", key="qz_submit"):
            st.session_state["qz_submitted"] = True
            st.rerun()
    else:
        score = sum(1 for i, q in enumerate(qs)
                    if st.session_state.get(f"qz_ans_{i}") ==
                    q["options"][q["answer"]])
        pct = score / len(qs) * 100
        color = P["GREEN"] if pct >= 60 else P["RED"]
        st.markdown(styles.chips_row([
            ("Score", f"{score}/{len(qs)}", color),
            ("Percentage", f"{pct:.0f}%", color),
            ("Pass mark", "60%", P["MUTED"]),
        ]), unsafe_allow_html=True)
