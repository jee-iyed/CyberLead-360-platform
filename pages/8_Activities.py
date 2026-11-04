"""Activities: log interactions, manage follow-ups and meetings."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

import pandas as pd
import streamlit as st

from cyberlead360.database.repositories.activities import ActivityRepository, MeetingRepository
from cyberlead360.database.repositories.companies import CompanyRepository
from cyberlead360.database.repositories.contacts import ContactRepository
from cyberlead360.domain.enums import ActivityDirection, ActivityType, MeetingStatus
from cyberlead360.domain.schemas import ActivityCreate, MeetingCreate
from cyberlead360.services.pipeline_service import PipelineService
from cyberlead360.ui.bootstrap import actor, db, flash, page_setup, run_action
from cyberlead360.ui.components import company_selector, empty_state

page_setup("Activities", "🗓️")
flash()

with db().session() as s:
    options = CompanyRepository(s).options()
if not options:
    empty_state("No companies yet.")
    st.stop()

LOGGABLE = [t for t in ActivityType if t not in (ActivityType.STAGE_CHANGE, ActivityType.MEETING)]
tab_log, tab_fu, tab_meet, tab_feed = st.tabs(
    ["📝 Log interaction", "⏰ Follow-ups", "🤝 Meetings", "📜 Activity feed"]
)


def _dt(d, t) -> datetime | None:  # type: ignore[no-untyped-def]
    return datetime.combine(d, t, tzinfo=UTC) if d else None


with tab_log:
    cid = company_selector(options, key="activity_company")
    with db().session() as s:
        contacts = [(c.id, c.full_name) for c in ContactRepository(s).for_company(cid)]
    with st.form("log_activity"):
        c1, c2 = st.columns(2)
        atype = c1.selectbox(
            "Type",
            [t.value for t in LOGGABLE],
            format_func=lambda v: v.replace("_", " ").capitalize(),
        )
        contact_id = c2.selectbox(
            "Contact",
            [None] + [c[0] for c in contacts],
            format_func=lambda i: "—" if i is None else dict(contacts)[i],
        )
        subject = st.text_input("Subject")
        notes = st.text_area("Notes (avoid unnecessary personal data)")
        c1, c2, c3 = st.columns(3)
        occurred_d = c1.date_input("Date", value=datetime.now(UTC).date())
        follow = c2.checkbox("Schedule follow-up")
        follow_d = c3.date_input(
            "Follow-up date", value=datetime.now(UTC).date() + timedelta(days=7)
        )
        auto = st.checkbox(
            "Advance the company stage automatically (contacted / replied)", value=True
        )
        if st.form_submit_button("Log activity", type="primary"):
            run_action(
                lambda s: PipelineService(s, actor()).log_activity(
                    ActivityCreate(
                        company_id=cid,
                        activity_type=ActivityType(atype),
                        contact_id=contact_id,
                        direction=ActivityDirection.OUTBOUND,
                        subject=subject or None,
                        notes=notes or None,
                        occurred_at=_dt(occurred_d, datetime.now(UTC).time()),
                        follow_up_at=_dt(follow_d, time(9)) if follow else None,
                    ),
                    auto_advance=auto,
                ),
                "Activity logged.",
                rerun=True,
            )
    st.caption("Outbound touches to suppressed or objected contacts are refused.")

with tab_fu:
    with db().session() as s:
        fus = [
            {
                "id": a.id,
                "due": a.follow_up_at,
                "company": name,
                "type": a.activity_type,
                "subject": a.subject,
            }
            for a, name in ActivityRepository(s).open_follow_ups()
        ]
    if not fus:
        st.success("No open follow-ups.")
    else:
        now = datetime.now(UTC)
        df = pd.DataFrame(fus)
        df["status"] = df["due"].map(lambda d: "⚠️ overdue" if d < now else "upcoming")
        st.dataframe(
            df,
            hide_index=True,
            width="stretch",
            column_config={"due": st.column_config.DatetimeColumn(format="YYYY-MM-DD")},
        )
        done = st.selectbox(
            "Mark follow-up as done",
            [f["id"] for f in fus],
            format_func=lambda i: next(
                f"#{f['id']} {f['company']} — {f['subject'] or ''}" for f in fus if f["id"] == i
            ),
        )
        if st.button("Complete follow-up"):
            run_action(
                lambda s: PipelineService(s, actor()).complete_follow_up(done),
                "Follow-up completed.",
                rerun=True,
            )

with tab_meet:
    left, right = st.columns([1, 1], gap="large")
    with left:
        mcid = company_selector(options, key="meeting_company")
        with db().session() as s:
            mcontacts = [(c.id, c.full_name) for c in ContactRepository(s).for_company(mcid)]
        with st.form("meeting"):
            st.subheader("Record a meeting")
            st.caption("No calendar invitation is sent — schedule it in your own calendar.")
            m_contact = st.selectbox(
                "Contact",
                [None] + [c[0] for c in mcontacts],
                format_func=lambda i: "—" if i is None else dict(mcontacts)[i],
            )
            c1, c2 = st.columns(2)
            m_date = c1.date_input("Date", value=datetime.now(UTC).date() + timedelta(days=3))
            m_time = c2.time_input("Time (UTC)", value=time(10))
            c1, c2 = st.columns(2)
            m_dur = c1.number_input("Duration (min)", 5, 480, 45, step=15)
            m_type = c2.selectbox("Type", ["discovery", "scoping", "proposal review", "follow-up"])
            m_loc = st.text_input("Location / link", "Video call")
            if st.form_submit_button("Save meeting", type="primary"):
                run_action(
                    lambda s: PipelineService(s, actor()).schedule_meeting(
                        MeetingCreate(
                            company_id=mcid,
                            contact_id=m_contact,
                            scheduled_at=_dt(m_date, m_time),
                            duration_minutes=int(m_dur),
                            meeting_type=m_type,
                            location=m_loc or None,
                        )
                    ),
                    "Meeting recorded.",
                    rerun=True,
                )
    with right:
        with db().session() as s:
            meetings = [
                {
                    "id": m.id,
                    "when": m.scheduled_at,
                    "company": name,
                    "type": m.meeting_type,
                    "status": m.status,
                    "minutes": m.duration_minutes,
                }
                for m, name in MeetingRepository(s).list()
            ]
        if meetings:
            st.dataframe(
                pd.DataFrame(meetings),
                hide_index=True,
                width="stretch",
                height=300,
                column_config={"when": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm")},
            )
            c1, c2 = st.columns(2)
            mid = c1.selectbox(
                "Meeting",
                [m["id"] for m in meetings],
                format_func=lambda i: next(
                    f"#{m['id']} {m['company']}" for m in meetings if m["id"] == i
                ),
            )
            new_status = c2.selectbox("New status", [x.value for x in MeetingStatus])
            if st.button("Update meeting status"):
                run_action(
                    lambda s: PipelineService(s, actor()).set_meeting_status(
                        mid, MeetingStatus(new_status)
                    ),
                    "Meeting updated.",
                    rerun=True,
                )
        else:
            empty_state("No meetings recorded.")

with tab_feed:
    types = st.multiselect("Types", [t.value for t in ActivityType])
    with db().session() as s:
        feed = [
            {
                "when": a.occurred_at,
                "company": company,
                "type": a.activity_type,
                "direction": a.direction,
                "contact": contact or "—",
                "subject": a.subject,
                "by": a.created_by,
            }
            for a, company, contact in ActivityRepository(s).recent(limit=200, types=types or None)
        ]
    if feed:
        st.dataframe(
            pd.DataFrame(feed),
            hide_index=True,
            width="stretch",
            column_config={"when": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm")},
        )
    else:
        empty_state("No activity yet.")
