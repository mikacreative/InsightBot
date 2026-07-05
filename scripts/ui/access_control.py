from __future__ import annotations

from copy import deepcopy

import streamlit as st

from insightbot.audit_log import append_audit_event, list_audit_events
from insightbot.subscribers import hash_token, load_subscribers, make_subscriber_record, save_subscribers


def _parse_audiences(text: str) -> list[str]:
    return [
        item.strip()
        for item in str(text or "").replace("，", ",").split(",")
        if item.strip()
    ]


def render_access_control_page(*, bot_dir: str, actor: dict | None = None) -> None:
    actor = actor or {}
    st.subheader("权限与订阅者")
    st.caption("管理员在这里维护访问 token、角色和 audience。订阅者页面会按 token 对应的 audience 过滤内容。")

    data = load_subscribers(bot_dir)
    subscribers = deepcopy(data.get("subscribers", {}) or {})
    role_options = ["subscriber", "operator", "admin"]

    if not subscribers:
        st.info("还没有配置任何 token。可以先创建一个 operator 或 subscriber。")

    token_to_delete = None
    for token, payload in subscribers.items():
        display_token = token if not str(token).startswith("sha256:") else "sha256:..."
        with st.expander(f"{payload.get('name', display_token)} · {payload.get('role', 'subscriber')}"):
            name = st.text_input("名称", value=payload.get("name", display_token), key=f"acl_name::{token}")
            current_role = payload.get("role", "subscriber")
            if current_role not in role_options:
                current_role = "subscriber"
            role = st.selectbox(
                "角色",
                options=role_options,
                index=role_options.index(current_role),
                key=f"acl_role::{token}",
            )
            audiences = st.text_input(
                "Audience",
                value=", ".join(payload.get("audiences", []) or []),
                key=f"acl_audiences::{token}",
            )
            col1, col2 = st.columns(2)
            with col1:
                if st.button("保存", key=f"acl_save::{token}", use_container_width=True):
                    subscribers[token] = {
                        "name": name.strip() or token,
                        "role": role,
                        "audiences": _parse_audiences(audiences) or ["public"],
                    }
                    save_subscribers({"subscribers": subscribers}, bot_dir=bot_dir)
                    append_audit_event(
                        bot_dir,
                        actor=actor,
                        action="subscribers.update",
                        target={"type": "subscriber", "id": token},
                        changes=subscribers[token],
                    )
                    st.success("已保存。")
                    st.rerun()
            with col2:
                if st.button("删除", key=f"acl_delete::{token}", use_container_width=True):
                    token_to_delete = token

    if token_to_delete:
        subscribers.pop(token_to_delete, None)
        save_subscribers({"subscribers": subscribers}, bot_dir=bot_dir)
        append_audit_event(
            bot_dir,
            actor=actor,
            action="subscribers.delete",
            target={"type": "subscriber", "id": token_to_delete},
            changes={},
        )
        st.success("已删除。")
        st.rerun()

    st.divider()
    st.markdown("**新增访问 token**")
    with st.form("acl_add_subscriber"):
        token = st.text_input("Token", placeholder="例如：team-ops-token").strip()
        name = st.text_input("名称", placeholder="例如：运营同事").strip()
        role = st.selectbox("角色", options=role_options, index=0)
        audiences = st.text_input("Audience", value="public")
        submitted = st.form_submit_button("创建", use_container_width=True)

    if submitted:
        if not token:
            st.error("Token 不能为空。")
            return
        if token in subscribers:
            st.error("Token 已存在。")
            return
        storage_key = f"sha256:{hash_token(token)}"
        if storage_key in subscribers:
            st.error("Token 已存在。")
            return
        subscribers[storage_key] = make_subscriber_record(
            token=token,
            name=name or token,
            role=role,
            audiences=_parse_audiences(audiences) or ["public"],
        )
        save_subscribers({"subscribers": subscribers}, bot_dir=bot_dir)
        append_audit_event(
            bot_dir,
            actor=actor,
            action="subscribers.create",
            target={"type": "subscriber", "id": storage_key},
            changes=subscribers[storage_key],
        )
        st.success("Token 已创建。")
        st.rerun()

    st.divider()
    st.markdown("**最近权限审计**")
    events = list_audit_events(bot_dir=bot_dir, limit=10)
    if not events:
        st.caption("暂无审计记录。")
    else:
        for event in events:
            st.caption(
                f"{event.get('created_at', '')} · {event.get('actor', {}).get('name', '')}"
                f" · {event.get('action', '')} · {event.get('target', {}).get('id', '')}"
            )
