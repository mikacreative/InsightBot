from __future__ import annotations

from contextlib import contextmanager
from html import escape
import re
from typing import Iterator

import streamlit as st


def render_workbench_styles() -> None:
    st.markdown(
        """
        <style>
        .ib-page-map {
            border: 1px solid rgba(36, 55, 70, 0.10);
            border-radius: 16px;
            padding: 14px 16px;
            background: #fbfaf6;
            margin: 0.4rem 0 1rem;
        }
        .ib-page-map-title {
            font-size: 0.92rem;
            font-weight: 800;
            color: #243746;
            margin-bottom: 0.45rem;
        }
        .ib-page-map-items {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }
        .ib-page-map-item {
            display: inline-flex;
            border: 1px solid rgba(36, 55, 70, 0.12);
            border-radius: 999px;
            padding: 6px 10px;
            background: #fff;
            color: #34495e;
            font-size: 0.84rem;
            font-weight: 700;
            text-decoration: none;
            transition: border-color 120ms ease, background 120ms ease, transform 120ms ease;
        }
        .ib-page-map-item:hover {
            border-color: rgba(112, 84, 39, 0.32);
            background: #fff7e8;
            color: #243746;
            transform: translateY(-1px);
        }
        .ib-section-heading {
            margin: 1.1rem 0 0.45rem;
            scroll-margin-top: 5rem;
        }
        .ib-section-heading-label {
            font-size: 1.04rem;
            font-weight: 850;
            color: #1f2d3d;
        }
        .ib-panel-title {
            font-size: 1.04rem;
            font-weight: 850;
            color: #1f2d3d;
            margin-bottom: 4px;
        }
        .ib-section-heading-copy {
            color: #637083;
            font-size: 0.91rem;
            line-height: 1.45;
            margin-top: 0.2rem;
        }
        .ib-section-note {
            border-left: 3px solid #c9a66b;
            padding: 8px 12px;
            background: #fff9eb;
            color: #5b4b2e;
            border-radius: 0 10px 10px 0;
            margin: 0.5rem 0 0.75rem;
            font-size: 0.9rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def make_anchor_id(label: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", label).strip("-").lower()
    return slug or "section"


def _normalize_page_map_item(item: str | tuple[str, str]) -> tuple[str, str]:
    if isinstance(item, tuple):
        return item
    return item, make_anchor_id(item)


def render_page_map(title: str, items: list[str | tuple[str, str]]) -> None:
    chips = "".join(
        f'<a class="ib-page-map-item" href="#{escape(anchor)}">{escape(label)}</a>'
        for label, anchor in (_normalize_page_map_item(item) for item in items)
    )
    st.markdown(
        f"""
        <div class="ib-page-map">
          <div class="ib-page-map-title">{escape(title)}</div>
          <div class="ib-page-map-items">{chips}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_section_heading(title: str, copy: str = "", anchor: str | None = None) -> None:
    copy_html = f'<div class="ib-section-heading-copy">{escape(copy)}</div>' if copy else ""
    anchor_attr = f' id="{escape(anchor)}"' if anchor else ""
    st.markdown(
        f"""
        <div class="ib-section-heading"{anchor_attr}>
          <div class="ib-section-heading-label">{escape(title)}</div>
          {copy_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_section_note(text: str) -> None:
    st.markdown(f'<div class="ib-section-note">{escape(text)}</div>', unsafe_allow_html=True)


@contextmanager
def bordered_section(title: str, copy: str = "", anchor: str | None = None) -> Iterator[None]:
    render_section_heading(title, copy, anchor=anchor)
    with st.container(border=True):
        yield
