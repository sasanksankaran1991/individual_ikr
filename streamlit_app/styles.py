"""Shared Streamlit layout helpers and CSS."""

from __future__ import annotations

import streamlit as st


def card_container():
    """Bordered container on newer Streamlit; plain container on older versions."""
    try:
        return st.container(border=True)
    except TypeError:
        return st.container()


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        /* Desktop — comfortable reading width, not edge-to-edge */
        @media (min-width: 769px) {
            .main .block-container {
                max-width: 760px !important;
                padding-top: 1.25rem !important;
                padding-bottom: 2rem !important;
            }
            [data-testid="stTabs"] [data-baseweb="tab-list"] {
                width: 100% !important;
            }
            [data-testid="stTabs"] button[data-baseweb="tab"] {
                flex: 1 1 0 !important;
                min-width: 0 !important;
            }
        }

        /* Cards */
        [data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 12px !important;
            padding: 0.85rem 1rem !important;
            margin-bottom: 0.65rem !important;
        }

        /* Tabs — scroll & tap-friendly on mobile */
        [data-testid="stTabs"] [data-baseweb="tab-list"] {
            overflow-x: auto !important;
            overflow-y: hidden !important;
            flex-wrap: nowrap !important;
            gap: 0.25rem !important;
            -webkit-overflow-scrolling: touch;
        }
        [data-testid="stTabs"] button[data-baseweb="tab"] {
            min-height: 2.75rem !important;
            padding: 0.5rem 1rem !important;
            white-space: nowrap !important;
            flex: 0 0 auto !important;
        }

        /* Full-width primary actions on small screens */
        .ikr-goal-title {
            font-size: 1.05rem;
            font-weight: 600;
            line-height: 1.35;
            margin: 0;
        }
        .ikr-meta {
            font-size: 0.82rem;
            opacity: 0.72;
            margin: 0.15rem 0 0 0;
        }
        .ikr-pill {
            display: inline-block;
            font-size: 0.75rem;
            font-weight: 600;
            padding: 0.18rem 0.55rem;
            border-radius: 999px;
            letter-spacing: 0.02em;
        }
        .ikr-pill-done {
            background: rgba(33, 195, 84, 0.18);
            color: rgb(21, 128, 61);
        }
        .ikr-pill-progress {
            background: rgba(255, 171, 0, 0.18);
            color: rgb(180, 83, 9);
        }
        .ikr-pill-todo {
            background: rgba(128, 128, 128, 0.14);
            color: inherit;
            opacity: 0.85;
        }
        html[data-theme="dark"] .ikr-pill-done { color: rgb(134, 239, 172); }
        html[data-theme="dark"] .ikr-pill-progress { color: rgb(253, 186, 116); }

        /* Comfortable padding on phones */
        @media (max-width: 768px) {
            .block-container {
                padding-top: 1rem !important;
                padding-left: 0.75rem !important;
                padding-right: 0.75rem !important;
                max-width: 100% !important;
            }
            [data-testid="stVerticalBlockBorderWrapper"] {
                padding: 0.75rem !important;
            }
            [data-testid="stMetric"] {
                padding: 0.25rem 0 !important;
            }
            [data-testid="stMetricValue"] {
                font-size: 1.25rem !important;
            }
            .ikr-goal-title {
                font-size: 1rem;
            }
            /* Slightly larger inputs for touch */
            input, textarea, select {
                font-size: 16px !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
