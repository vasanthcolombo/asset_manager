"""Shared Money Manager UI helpers (reused across Stats and Transactions pages)."""

import streamlit as st


def account_filter_widget(key_prefix: str, all_groups: list, all_accounts: list) -> set[int]:
    """
    Two-level account selector: popover → group expanders → account checkboxes.
    Returns the set of selected account IDs (empty = all accounts).
    """
    grp_map: dict[str, list] = {}
    for g in all_groups:
        accs = sorted(
            [a for a in all_accounts if a["group_name"] == g["name"]],
            key=lambda x: x["name"],
        )
        if accs:
            grp_map[g["name"]] = accs

    sel_ids: set[int] = {
        a["id"]
        for accs in grp_map.values()
        for a in accs
        if st.session_state.get(f"{key_prefix}_{a['id']}", False)
    }

    if sel_ids:
        names = [a["name"] for a in all_accounts if a["id"] in sel_ids]
        btn_label = ", ".join(names[:2]) + (f"  +{len(names) - 2} more" if len(names) > 2 else "")
    else:
        btn_label = "All accounts  ▾"

    with st.popover(btn_label, use_container_width=True):
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Clear all", key=f"{key_prefix}_clear", use_container_width=True):
                for accs in grp_map.values():
                    for a in accs:
                        st.session_state[f"{key_prefix}_{a['id']}"] = False
                st.rerun()
        with c2:
            if st.button("Select all", key=f"{key_prefix}_selall", use_container_width=True):
                for accs in grp_map.values():
                    for a in accs:
                        st.session_state[f"{key_prefix}_{a['id']}"] = True
                st.rerun()

        for g_name, accs in grp_map.items():
            n_sel = sum(1 for a in accs if st.session_state.get(f"{key_prefix}_{a['id']}", False))
            exp_label = f"{g_name}  ({n_sel}/{len(accs)} selected)" if n_sel else g_name
            with st.expander(exp_label, expanded=(n_sel > 0)):
                for a in accs:
                    st.checkbox(a["name"], key=f"{key_prefix}_{a['id']}")

    return sel_ids
