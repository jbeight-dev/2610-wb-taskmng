"""내 Epic 일감 현황 — Streamlit 단일 페이지."""
from __future__ import annotations

import logging
import re

import streamlit as st

import dashboard_service as svc
from models import DONE, IN_PROGRESS, TODO, DashboardResult
from settings import SettingsError, load_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

PAGE_TITLE = "내 Epic 일감 현황"
ALL = "__all__"
STATUS_CHOICES = [IN_PROGRESS, DONE, TODO, svc.STATUS_ALL]
STATUS_CHOICE_LABELS = {IN_PROGRESS: "진행 중", DONE: "완료", TODO: "대기", svc.STATUS_ALL: "전체"}
EMPTY_FILTER_MESSAGE = "선택한 조건에 해당하는 일감이 없습니다."

_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~$:])")

st.set_page_config(page_title=PAGE_TITLE, layout="wide")


def md(text: str) -> str:
    """Jira 문자열을 Markdown 해석 없이 일반 텍스트로 표시하기 위한 이스케이프."""
    return _MD_SPECIAL.sub(r"\\\1", str(text))


def _read_secrets() -> dict:
    try:
        return {key: st.secrets[key] for key in st.secrets.keys()}
    except Exception:  # secrets.toml이 없으면 환경변수만 사용한다.
        return {}


def _request_load() -> None:
    st.session_state.load_requested = True


def _run_load(settings) -> None:
    ss = st.session_state
    error = None
    try:
        with st.spinner("Jira에서 일감을 조회하는 중입니다…"):
            result = svc.load_dashboard(settings)
    except svc.DashboardLoadError as err:
        error = err.message
    except Exception:
        log.exception("예기치 않은 조회 오류")
        error = "예기치 않은 오류로 조회에 실패했습니다. 터미널 로그를 확인하세요."
    else:
        ss.result = result
        ss.load_error = None
        ss.refresh_error = None
    finally:
        ss.load_requested = False
    if error:
        # 기존 성공 결과가 있으면 유지하고 새로고침 실패로만 안내한다.
        if ss.get("result") is not None:
            ss.refresh_error = error
        else:
            ss.load_error = error


def _remember_filter(name: str) -> None:
    st.session_state[f"sel_{name}"] = st.session_state[f"f_{name}"]


def _sanitize_filters(epic_keys: list[str], assignee_ids: list[str]) -> None:
    """보존 키(sel_*)를 검증해 위젯 키(f_*)에 반영한다.

    위젯이 렌더링되지 않는 조회 중 실행에서 Streamlit이 위젯 상태를 지우므로 선택값은 별도 키로 유지한다.
    """
    ss = st.session_state
    ss.setdefault("sel_epic", ALL)
    ss.setdefault("sel_assignee", ALL)
    ss.setdefault("sel_status", IN_PROGRESS)
    notices = []
    if ss.sel_epic != ALL and ss.sel_epic not in epic_keys:
        notices.append(f"선택했던 Epic({ss.sel_epic})이 더 이상 조회되지 않아 Epic 필터를 전체로 바꿨습니다.")
        ss.sel_epic = ALL
    if ss.sel_assignee != ALL and ss.sel_assignee not in assignee_ids:
        notices.append("선택했던 담당자의 일감이 더 이상 조회되지 않아 담당자 필터를 전체로 바꿨습니다.")
        ss.sel_assignee = ALL
    if ss.sel_status not in STATUS_CHOICES:
        ss.sel_status = IN_PROGRESS
    ss.f_epic = ss.sel_epic
    ss.f_assignee = ss.sel_assignee
    ss.f_status = ss.sel_status
    for notice in notices:
        st.info(notice)


def _render_header(result: DashboardResult | None, busy: bool) -> None:
    ss = st.session_state
    if result is not None:
        st.caption(
            f"조회 기준 사용자: **{md(result.viewer.display_name)}** ({md(result.viewer.jira_user_id)})  ·  "
            f"마지막 조회 완료: {svc.format_kst(result.fetched_at)} (Asia/Seoul)  ·  조회 가능한 일감 기준"
        )
    label = "다시 조회" if result is None and ss.get("load_error") else "새로고침"
    st.button(label, disabled=busy, on_click=_request_load, help="Jira에서 최신 상태를 다시 조회합니다.")


def _render_summary(summary, is_partial: bool) -> None:
    help_text = "일부 조회 결과 기준입니다." if is_partial else None
    cols = st.columns(5)
    cols[0].metric("대상 Epic", summary.epic_count, help=help_text)
    cols[1].metric("전체 Task", summary.task_count, help=help_text)
    cols[2].metric("진행 중", summary.in_progress_count, help=help_text)
    cols[3].metric("완료", summary.done_count, help=help_text)
    cols[4].metric("대기", summary.todo_count, help=help_text)
    if summary.unknown_count:
        st.warning(
            f"분류 확인 필요 {summary.unknown_count}건 — 상태 카테고리를 확인할 수 없는 일감입니다. "
            "'전체' 보기에서 원본 상태와 함께 확인하세요."
        )


def _render_dashboard(result: DashboardResult) -> None:
    ss = st.session_state
    if result.is_partial:
        st.warning(
            "**일부 조회 결과** — 일부 Epic을 조회하지 못해 건수가 실제보다 적을 수 있습니다.\n\n"
            + "\n".join(f"- {md(w.message)}" for w in result.warnings)
        )
    elif result.warnings:
        st.info("\n".join(f"- {md(w.message)}" for w in result.warnings))

    if not result.epics:
        st.info("담당자로 지정된 Epic이 없습니다.")
        return

    df = svc.issues_frame(result.issues)
    epic_titles = {e.key: e.summary for e in result.epics}
    labels = svc.assignee_labels(df)
    _sanitize_filters(list(epic_titles), list(labels))

    col_epic, col_assignee, col_status = st.columns([3, 2, 3])
    with col_epic:
        epic_choice = st.selectbox(
            "Epic",
            [ALL, *epic_titles],
            key="f_epic",
            on_change=_remember_filter,
            args=("epic",),
            format_func=lambda k: "전체" if k == ALL else f"{k} · {epic_titles[k]}",
        )
    with col_assignee:
        assignee_choice = st.selectbox(
            "담당자",
            [ALL, *labels],
            key="f_assignee",
            on_change=_remember_filter,
            args=("assignee",),
            format_func=lambda a: "전체" if a == ALL else labels[a],
        )
    with col_status:
        status_choice = st.radio(
            "상태",
            STATUS_CHOICES,
            key="f_status",
            on_change=_remember_filter,
            args=("status",),
            format_func=STATUS_CHOICE_LABELS.get,
            horizontal=True,
        )

    epic_key = None if epic_choice == ALL else epic_choice
    assignee_id = None if assignee_choice == ALL else assignee_choice
    scoped = svc.scope_frame(df, epic_key, assignee_id)
    _render_summary(svc.summarize(scoped, 1 if epic_key else len(result.epics)), result.is_partial)

    if df.empty or (epic_key and assignee_id is None and scoped.empty):
        st.info("해당 Epic에 조회 가능한 Task가 없습니다.")
        return
    if scoped.empty:
        st.info(EMPTY_FILTER_MESSAGE)
        return

    groups = svc.assignee_groups(scoped, status_choice, labels)
    if not groups or all(g.rows.empty for g in groups):
        st.info(EMPTY_FILTER_MESSAGE)
        return

    column_config = {
        "일감": st.column_config.LinkColumn(
            "일감", display_text=r"https?://.*/browse/(.*)", help="Jira 원본 일감 열기"
        ),
    }
    st.divider()
    for group in groups:
        st.subheader(md(group.label))
        counts = f"전체 {group.total} · 진행 중 {group.in_progress} · 완료 {group.done} · 대기 {group.todo}"
        if group.unknown:
            counts += f" · 분류 확인 필요 {group.unknown}"
        st.caption(counts)
        if group.rows.empty:
            st.caption(f"'{STATUS_CHOICE_LABELS[status_choice]}' 상태의 일감이 없습니다.")
            continue
        st.dataframe(
            svc.display_table(group.rows, epic_titles),
            hide_index=True,
            column_config=column_config,
        )


def main() -> None:
    st.title(PAGE_TITLE)

    try:
        settings = load_settings(secrets=_read_secrets())
    except SettingsError as err:
        st.error(
            "설정이 올바르지 않아 Jira 조회를 실행하지 않았습니다.\n\n"
            + "\n".join(f"- {md(p)}" for p in err.problems)
            + "\n\n환경변수 또는 `.streamlit/secrets.toml`을 확인한 뒤 앱을 재시작하세요."
        )
        st.stop()

    ss = st.session_state
    fingerprint = settings.fingerprint()
    if ss.get("settings_fp") != fingerprint:
        # 인증·조회 설정이 바뀌면 이전 결과를 재사용하지 않는다.
        for key in ("result", "load_error", "refresh_error"):
            ss.pop(key, None)
        ss.settings_fp = fingerprint
        ss.load_requested = True

    busy = bool(ss.get("load_requested"))
    _render_header(ss.get("result"), busy)

    if busy:
        _run_load(settings)
        st.rerun()

    result = ss.get("result")
    if ss.get("refresh_error") and result is not None:
        st.warning(
            f"새로고침에 실패했습니다. {md(ss.refresh_error)}\n\n"
            f"아래는 이전 조회 결과입니다(마지막 조회 완료: {svc.format_kst(result.fetched_at)})."
        )
    if result is None:
        if ss.get("load_error"):
            st.error(md(ss.load_error))
            st.caption("'다시 조회' 버튼으로 재시도할 수 있습니다.")
        return

    _render_dashboard(result)


main()
