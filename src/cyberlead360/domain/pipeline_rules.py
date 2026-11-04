"""Allowed transitions for prospect stages and opportunity stages.

Kept as data so that the rules are easy to read, document and test.
"""

from __future__ import annotations

from cyberlead360.domain.enums import OpportunityStage, ProspectStage
from cyberlead360.domain.exceptions import InvalidTransitionError

S = ProspectStage

PROSPECT_TRANSITIONS: dict[ProspectStage, frozenset[ProspectStage]] = {
    S.NEW: frozenset({S.RESEARCHING, S.QUALIFIED, S.ARCHIVED}),
    S.RESEARCHING: frozenset({S.QUALIFIED, S.NEW, S.LOST, S.ARCHIVED}),
    S.QUALIFIED: frozenset({S.READY_TO_CONTACT, S.RESEARCHING, S.LOST, S.ARCHIVED}),
    S.READY_TO_CONTACT: frozenset({S.CONTACTED, S.QUALIFIED, S.LOST, S.ARCHIVED}),
    S.CONTACTED: frozenset({S.REPLIED, S.READY_TO_CONTACT, S.LOST, S.ARCHIVED}),
    S.REPLIED: frozenset({S.MEETING_SCHEDULED, S.OPPORTUNITY_OPEN, S.LOST, S.ARCHIVED}),
    S.MEETING_SCHEDULED: frozenset({S.OPPORTUNITY_OPEN, S.REPLIED, S.LOST, S.ARCHIVED}),
    S.OPPORTUNITY_OPEN: frozenset({S.PROPOSAL_SENT, S.WON, S.LOST}),
    S.PROPOSAL_SENT: frozenset({S.WON, S.LOST, S.OPPORTUNITY_OPEN}),
    S.WON: frozenset({S.OPPORTUNITY_OPEN, S.ARCHIVED}),
    S.LOST: frozenset({S.RESEARCHING, S.ARCHIVED}),
    S.ARCHIVED: frozenset({S.NEW}),
}

OPPORTUNITY_TRANSITIONS: dict[OpportunityStage, frozenset[OpportunityStage]] = {
    OpportunityStage.OPEN: frozenset(
        {OpportunityStage.PROPOSAL_SENT, OpportunityStage.WON, OpportunityStage.LOST}
    ),
    OpportunityStage.PROPOSAL_SENT: frozenset(
        {OpportunityStage.OPEN, OpportunityStage.WON, OpportunityStage.LOST}
    ),
    OpportunityStage.WON: frozenset(),
    OpportunityStage.LOST: frozenset({OpportunityStage.OPEN}),  # re-open a lost deal
}

# Company stage implied by an opportunity stage change (synchronization rule).
OPPORTUNITY_TO_PROSPECT_STAGE: dict[OpportunityStage, ProspectStage] = {
    OpportunityStage.OPEN: S.OPPORTUNITY_OPEN,
    OpportunityStage.PROPOSAL_SENT: S.PROPOSAL_SENT,
    OpportunityStage.WON: S.WON,
    OpportunityStage.LOST: S.LOST,
}


def allowed_prospect_targets(current: ProspectStage) -> list[ProspectStage]:
    return sorted(PROSPECT_TRANSITIONS[current], key=lambda s: (s.order == 0, s.order))


def validate_prospect_transition(current: ProspectStage, target: ProspectStage) -> None:
    if current == target:
        raise InvalidTransitionError(f"The company is already in stage '{current.label}'.")
    if target not in PROSPECT_TRANSITIONS[current]:
        allowed = ", ".join(s.label for s in allowed_prospect_targets(current))
        raise InvalidTransitionError(
            f"Cannot move from '{current.label}' to '{target.label}'. Allowed: {allowed}."
        )


def validate_opportunity_transition(current: OpportunityStage, target: OpportunityStage) -> None:
    if current == target:
        raise InvalidTransitionError(f"The opportunity is already '{current.value}'.")
    if target not in OPPORTUNITY_TRANSITIONS[current]:
        raise InvalidTransitionError(
            f"Cannot move an opportunity from '{current.value}' to '{target.value}'."
        )
