"""Deterministic, ENTIRELY FICTIONAL demo data generator.

* Company names are generated; domains use the reserved ``.example`` TLD (RFC 2606).
* People are invented; e-mails are non-deliverable; phones use the 555-01xx range.
* Sources are explicitly labelled "fictional demo source" — no real citation is made.
* ``random.Random(42)``: the same data structure is produced on every run; dates
  are relative to the anchor day (default: today, UTC).
"""

from __future__ import annotations

import itertools
import random
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import delete, select

from cyberlead360.config.settings import get_settings
from cyberlead360.database.base import Base
from cyberlead360.database.models import Activity, Company, Meeting, Opportunity
from cyberlead360.database.session import Database
from cyberlead360.domain.enums import (
    ActivityDirection,
    ActivityType,
    Confidence,
    ContactStatus,
    FactType,
    Industry,
    Language,
    MeetingStatus,
    MessageType,
    OpportunityStage,
    ProspectStage,
    QualificationStatus,
    ReviewStatus,
    ServiceLine,
    SourceType,
    Tone,
    VerificationStatus,
)
from cyberlead360.domain.schemas import (
    CompanyCreate,
    ContactCreate,
    FactCreate,
    OutreachRequest,
    SourceCreate,
)
from cyberlead360.services.company_service import CompanyService
from cyberlead360.services.compliance_service import ComplianceService
from cyberlead360.services.contact_service import ContactService
from cyberlead360.services.enrichment_service import EnrichmentService
from cyberlead360.services.outreach_service import OutreachService
from cyberlead360.services.scoring_service import ScoringService
from cyberlead360.utils.normalization import slugify

ACTOR = "seed.script"
N_COMPANIES = 84

PREFIXES = [
    "Nordel",
    "Alpicor",
    "Atlantis",
    "Helion",
    "Vectra",
    "Lumio",
    "Orivia",
    "Cobaltix",
    "Azurel",
    "Kernova",
    "Silvane",
    "Brionet",
    "Terrava",
    "Novacia",
    "Quantel",
    "Rivaro",
    "Borealis",
    "Celsio",
    "Deltane",
    "Equinor",
    "Fennix",
    "Galvane",
    "Hydrel",
    "Ilyon",
    "Jurassia",
    "Kalixo",
    "Loriane",
    "Meridio",
    "Nexalis",
    "Opalia",
    "Pyrenea",
    "Quartzo",
    "Rhodan",
    "Sequana",
    "Tavira",
    "Ulmara",
    "Valtek",
    "Wavera",
    "Xenora",
    "Yseris",
    "Zephyra",
    "Arvella",
]
SUFFIX = {
    Industry.MANUFACTURING: ["Industries", "Precision", "Composites", "Mécanique"],
    Industry.HEALTHCARE: ["Santé", "Medical", "Clinics", "Biotech"],
    Industry.FINANCIAL_SERVICES: ["Finance", "Assurances", "Capital", "Banque"],
    Industry.TECHNOLOGY: ["Software", "Systems", "Cloud", "Labs"],
    Industry.ENERGY_UTILITIES: ["Energy", "Hydro", "Réseaux", "Power"],
    Industry.TELECOM: ["Telecom", "Networks", "Connect"],
    Industry.LOGISTICS: ["Logistics", "Transport", "Freight"],
    Industry.RETAIL: ["Retail", "Commerce", "Distribution"],
    Industry.PUBLIC_SECTOR: ["Agglomération", "Public Services"],
    Industry.EDUCATION: ["Academy", "Institute"],
    Industry.PROFESSIONAL_SERVICES: ["Conseil", "Partners", "Advisory"],
}
INDUSTRY_WEIGHTS = {
    Industry.MANUFACTURING: 14,
    Industry.HEALTHCARE: 10,
    Industry.FINANCIAL_SERVICES: 10,
    Industry.TECHNOLOGY: 12,
    Industry.ENERGY_UTILITIES: 5,
    Industry.TELECOM: 3,
    Industry.LOGISTICS: 5,
    Industry.RETAIL: 5,
    Industry.PUBLIC_SECTOR: 3,
    Industry.EDUCATION: 2,
    Industry.PROFESSIONAL_SERVICES: 3,
}
COUNTRIES = {
    "FR": (40, ["Paris", "Lyon", "Toulouse", "Nantes", "Lille", "Bordeaux", "Grenoble"]),
    "BE": (8, ["Brussels", "Liège", "Ghent"]),
    "CH": (6, ["Geneva", "Lausanne", "Zurich"]),
    "LU": (3, ["Luxembourg"]),
    "DE": (8, ["Munich", "Stuttgart", "Hamburg"]),
    "ES": (5, ["Madrid", "Barcelona"]),
    "GB": (5, ["London", "Manchester"]),
    "MA": (5, ["Casablanca", "Rabat"]),
    "TN": (4, ["Tunis", "Sfax"]),
    "CA": (3, ["Montréal"]),
    "US": (3, ["Boston"]),
}
FIRST_NAMES = [
    "Camille",
    "Julien",
    "Sarah",
    "Thomas",
    "Léa",
    "Nicolas",
    "Inès",
    "Hugo",
    "Amira",
    "Lucas",
    "Chloé",
    "Mehdi",
    "Emma",
    "Karim",
    "Laura",
    "Antoine",
    "Yasmine",
    "Paul",
    "Nora",
    "David",
    "Elena",
    "Marc",
    "Sofia",
    "Omar",
    "Anna",
    "Pierre",
    "Lina",
    "Victor",
]
LAST_NAMES = [
    "Martin",
    "Bernard",
    "Dubois",
    "Lefèvre",
    "Moreau",
    "Laurent",
    "Garcia",
    "Roux",
    "Fontaine",
    "Chevalier",
    "Benali",
    "Haddad",
    "Schneider",
    "Weber",
    "Rossi",
    "Janssens",
    "Peeters",
    "Müller",
    "Navarro",
    "Durand",
    "Mercier",
    "Girard",
]
TITLES = [
    ("Chief Information Security Officer", "Security"),
    ("CIO", "IT"),
    ("IT Director", "IT"),
    ("Head of Infrastructure", "IT"),
    ("Chief Operating Officer", "Operations"),
    ("Data Protection Officer", "Legal"),
    ("Head of OT & Automation", "Operations"),
    ("CTO", "Engineering"),
]

FACT_LIBRARY: dict[FactType, list[str]] = {
    FactType.SECURITY_NEED_EXPLICIT: [
        "Published a call for tenders for an external penetration test of its customer portal.",
        "Announced it is seeking a partner to run 24/7 security monitoring (MDR) from next year.",
        "Stated in its annual report that it will launch an ISO 27001 certification project.",
        "Issued a request for proposals for a security awareness programme for all staff.",
    ],
    FactType.SECURITY_SIGNAL: [
        "Created a new Chief Information Security Officer position.",
        "Announced a migration of its core ERP to a public cloud provider.",
        "Launched a new online platform for customer self-service.",
        "Is recruiting several security engineers according to its careers page.",
    ],
    FactType.REGULATORY_CONTEXT: [
        "Describes itself as an operator falling within the scope of the NIS2 directive.",
        "Mentions DORA readiness work in its latest investor communication.",
        "Reports pursuing a health-data hosting (HDS) certification.",
    ],
    FactType.GROWTH_EVENT: [
        "Announced the opening of two new production sites.",
        "Completed the acquisition of a regional competitor.",
        "Reported 30% headcount growth over the last year.",
        "Opened a new office and warehouse to support expansion.",
    ],
    FactType.TECHNOLOGY_CONTEXT: [
        "Uses a hybrid infrastructure combining on-premise data centers and cloud services.",
        "Operates connected industrial equipment across several factories.",
        "Develops its own web applications for B2B customers.",
    ],
    FactType.BUSINESS_CONTEXT: [
        "Serves mainly B2B customers in Europe.",
        "Is a family-owned company with a long regional presence.",
        "Positions itself as a specialist supplier for regulated industries.",
    ],
}

STAGE_WEIGHTS = {
    ProspectStage.NEW: 8,
    ProspectStage.RESEARCHING: 8,
    ProspectStage.QUALIFIED: 8,
    ProspectStage.READY_TO_CONTACT: 7,
    ProspectStage.CONTACTED: 26,
    ProspectStage.REPLIED: 5,
    ProspectStage.MEETING_SCHEDULED: 4,
    ProspectStage.OPPORTUNITY_OPEN: 4,
    ProspectStage.PROPOSAL_SENT: 3,
    ProspectStage.WON: 3,
    ProspectStage.LOST: 9,
    ProspectStage.ARCHIVED: 3,
}
SERVICE_VALUE = {
    ServiceLine.PENETRATION_TESTING: (12_000, 45_000),
    ServiceLine.WEB_SECURITY_AUDIT: (8_000, 25_000),
    ServiceLine.NETWORK_ASSESSMENT: (10_000, 35_000),
    ServiceLine.CLOUD_SECURITY: (15_000, 60_000),
    ServiceLine.SECURITY_AWARENESS: (6_000, 20_000),
    ServiceLine.SOC_MDR: (40_000, 150_000),
    ServiceLine.INCIDENT_RESPONSE_READINESS: (10_000, 30_000),
    ServiceLine.COMPLIANCE_SUPPORT: (15_000, 70_000),
    ServiceLine.OT_SECURITY: (20_000, 90_000),
}


def weighted(rng: random.Random, mapping: dict) -> object:  # type: ignore[type-arg]
    keys = list(mapping)
    weights = [mapping[k][0] if isinstance(mapping[k], tuple) else mapping[k] for k in keys]
    return rng.choices(keys, weights=weights, k=1)[0]


def at(anchor: datetime, days_ago: float, hour: int = 10) -> datetime:
    base = anchor - timedelta(days=days_ago)
    return base.replace(hour=hour, minute=0, second=0, microsecond=0)


def wipe(db: Database) -> None:
    with db.session() as s:
        for table in reversed(Base.metadata.sorted_tables):
            s.execute(delete(table))


def seed(db: Database, anchor_day: date) -> dict[str, int]:
    rng = random.Random(42)
    anchor = datetime.combine(anchor_day, time(12, 0), tzinfo=UTC)
    stats = {
        "companies": 0,
        "contacts": 0,
        "facts": 0,
        "activities": 0,
        "opportunities": 0,
        "meetings": 0,
        "drafts": 0,
    }
    used_slugs: set[str] = set()
    prefixes = PREFIXES.copy()
    rng.shuffle(prefixes)

    with db.session() as s:
        ScoringService(s, ACTOR).ensure_default_rules()
        companies_svc = CompanyService(s, ACTOR)
        contacts_svc = ContactService(s, ACTOR)
        intel = EnrichmentService(s, ACTOR)

        for i in range(N_COMPANIES):
            industry: Industry = weighted(rng, INDUSTRY_WEIGHTS)  # type: ignore[assignment]
            prefix = prefixes[i % len(prefixes)]
            name = f"{prefix} {rng.choice(SUFFIX[industry])}"
            slug = slugify(name)
            while slug in used_slugs:
                extra = rng.choice(["Group", "Europe", "Holding"])
                name = f"{prefix} {rng.choice(SUFFIX[industry])} {extra}"
                slug = slugify(name)
            used_slugs.add(slug)
            country: str = weighted(rng, COUNTRIES)  # type: ignore[assignment]
            size_band = rng.choices(
                [(12, 49), (50, 249), (250, 999), (1000, 4999), (5000, 20000)],
                weights=[10, 30, 32, 20, 8],
            )[0]
            employees = rng.randint(*size_band) if rng.random() > 0.06 else None
            company = companies_svc.create(
                CompanyCreate(
                    company_name=name,
                    website=None if rng.random() < 0.04 else f"https://www.{slug}.example",
                    industry=industry if rng.random() > 0.04 else None,
                    country=country,
                    city=rng.choice(COUNTRIES[country][1]),
                    employee_count=employees,
                    description=f"Fictional {industry.label.lower()} company created for "
                    "CyberLead 360 demonstrations.",
                ),
                confirm_possible_duplicate=True,
                source_label="demo_seed",
            )
            created_at = at(anchor, rng.randint(120, 300))
            company.created_at = created_at
            stats["companies"] += 1

            # ---- sources and facts (fictional, labelled as such)
            n_facts = rng.choices([0, 1, 2, 3, 4], weights=[12, 22, 30, 24, 12])[0]
            if n_facts:
                fact_types = rng.sample(
                    [
                        FactType.SECURITY_NEED_EXPLICIT,
                        FactType.SECURITY_SIGNAL,
                        FactType.REGULATORY_CONTEXT,
                        FactType.GROWTH_EVENT,
                        FactType.TECHNOLOGY_CONTEXT,
                        FactType.BUSINESS_CONTEXT,
                    ],
                    k=n_facts,
                )
                for j, fact_type in enumerate(fact_types):
                    published = at(anchor, rng.randint(5, 500))
                    source = intel.add_source(
                        SourceCreate(
                            company_id=company.id,
                            source_type=SourceType.DEMO_FICTIONAL,
                            title=f"Fictional demo source #{j + 1}: {name} (not real)",
                            url=f"https://www.{slug}.example/news/demo-{j + 1}",
                            publisher=f"{slug}.example (fictional)",
                            published_at=published,
                        )
                    )
                    if rng.random() < 0.6:
                        source.verification_status = VerificationStatus.VERIFIED.value
                    review = rng.choices(
                        [ReviewStatus.APPROVED, ReviewStatus.PENDING, ReviewStatus.REJECTED],
                        weights=[75, 18, 7],
                    )[0]
                    fact = intel.add_fact(
                        FactCreate(
                            company_id=company.id,
                            source_id=source.id,
                            fact_type=fact_type,
                            statement=rng.choice(FACT_LIBRARY[fact_type]),
                            confidence=rng.choice(
                                [Confidence.MEDIUM, Confidence.HIGH, Confidence.LOW]
                            ),
                            observed_at=published,
                        )
                    )
                    if review != ReviewStatus.PENDING:
                        fact.review_status = review.value
                        fact.reviewed_by = ACTOR
                        fact.reviewed_at = published + timedelta(days=2)
                    stats["facts"] += 1

            # ---- contacts
            contacts = []
            for _ in range(rng.choices([0, 1, 2, 3], weights=[5, 35, 40, 20])[0]):
                first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
                title, dept = rng.choice(TITLES)
                email = f"{slugify(first)}.{slugify(last)}@{slug}.example"
                if any(c.professional_email == email for c in contacts):
                    continue
                contact = contacts_svc.create(
                    ContactCreate(
                        company_id=company.id,
                        first_name=first,
                        last_name=last,
                        job_title=title,
                        department=dept,
                        professional_email=email,
                        business_phone=f"+1-555-01{rng.randint(0, 99):02d}",
                        lawful_basis_notes="Demo: legitimate interest (B2B prospecting).",
                    )
                )
                contact.created_at = created_at
                contacts.append(contact)
                stats["contacts"] += 1

            # ---- pipeline history consistent with the target stage
            target: ProspectStage = weighted(rng, STAGE_WEIGHTS)  # type: ignore[assignment]
            needs_contact = (
                target.order >= ProspectStage.CONTACTED.order or target == ProspectStage.LOST
            )
            if needs_contact and not contacts:
                target = ProspectStage.QUALIFIED
            history = _build_history(s, rng, anchor, company, contacts, target, stats)
            company.prospect_stage = history["stage"].value
            company.highest_stage_order = history["highest"]
            company.stage_changed_at = history["changed_at"]
            company.last_activity_at = history["last_activity"]
            if history["stage"] == ProspectStage.ARCHIVED:
                company.archived_at = history["changed_at"]
            if company.highest_stage_order >= ProspectStage.QUALIFIED.order:
                company.qualification_status = QualificationStatus.QUALIFIED.value
            elif history["stage"] == ProspectStage.RESEARCHING:
                company.qualification_status = QualificationStatus.NURTURE.value

        s.flush()
        # ---- privacy scenarios: one objection, one bounced address
        compliance = ComplianceService(s, ACTOR)
        all_contacts = sorted(
            (c for comp in s.scalars(select(Company)) for c in comp.contacts), key=lambda c: c.id
        )
        if len(all_contacts) > 10:
            compliance.record_objection(
                all_contacts[7].id, "Demo: contact asked not to be contacted"
            )
            all_contacts[11].contact_status = ContactStatus.BOUNCED.value

        ScoringService(s, ACTOR).recalculate_all()

    # ---- a few template drafts for the best-scored companies (no API key needed)
    settings = get_settings()
    with db.session() as s:
        ranking = ScoringService(s, ACTOR).ranking()
        outreach = OutreachService(s, ACTOR, settings, provider=None)
        for cid in ranking["id"].head(12).tolist():
            company = s.get(Company, int(cid))
            contact = next((c for c in company.contacts if c.can_be_contacted), None)
            if contact is None or company.stage.order >= ProspectStage.CONTACTED.order:
                continue
            outreach.generate(
                OutreachRequest(
                    company_id=company.id,
                    contact_id=contact.id,
                    message_type=MessageType.COLD_EMAIL,
                    tone=rng.choice([Tone.PROFESSIONAL, Tone.CONSULTATIVE]),
                    language=Language.FR
                    if company.country in {"FR", "BE", "CH", "LU", "MA", "TN"}
                    else Language.EN,
                    use_llm=False,
                )
            )
            stats["drafts"] += 1
            if stats["drafts"] >= 5:
                break
    return stats


def _add_activity(
    s,
    stats,
    company,
    contact,
    kind,
    when,
    subject,
    direction=ActivityDirection.OUTBOUND,
    follow_up=None,
    opp=None,
):  # type: ignore[no-untyped-def]
    s.add(
        Activity(
            company_id=company.id,
            contact_id=contact.id if contact else None,
            opportunity_id=opp.id if opp else None,
            activity_type=kind.value,
            direction=direction.value,
            subject=subject,
            occurred_at=when,
            follow_up_at=follow_up,
            follow_up_done=False,
            created_by=ACTOR,
            created_at=when,
        )
    )
    stats["activities"] += 1
    if contact and kind.is_outbound_touch:
        contact.last_contacted_at = max(filter(None, [contact.last_contacted_at, when]))


def _stage_log(s, stats, company, frm, to, when):  # type: ignore[no-untyped-def]
    s.add(
        Activity(
            company_id=company.id,
            activity_type=ActivityType.STAGE_CHANGE.value,
            direction=ActivityDirection.INTERNAL.value,
            subject=f"{frm.label} → {to.label}",
            occurred_at=when,
            created_by=ACTOR,
            created_at=when,
        )
    )
    stats["activities"] += 1


def _build_history(s, rng, anchor, company, contacts, target, stats):  # type: ignore[no-untyped-def]
    """Create a plausible, chronologically ordered history ending in ``target``."""
    path = [ProspectStage.NEW]
    linear = [
        ProspectStage.RESEARCHING,
        ProspectStage.QUALIFIED,
        ProspectStage.READY_TO_CONTACT,
        ProspectStage.CONTACTED,
        ProspectStage.REPLIED,
        ProspectStage.MEETING_SCHEDULED,
        ProspectStage.OPPORTUNITY_OPEN,
        ProspectStage.PROPOSAL_SENT,
        ProspectStage.WON,
    ]
    lost_after_opp = target == ProspectStage.LOST and rng.random() < 0.5
    final_linear = {
        ProspectStage.LOST: ProspectStage.PROPOSAL_SENT
        if lost_after_opp
        else ProspectStage.CONTACTED,
        ProspectStage.ARCHIVED: ProspectStage.RESEARCHING,
    }.get(target, target)
    for stage in linear:
        if stage.order > final_linear.order:
            break
        path.append(stage)
    if target in (ProspectStage.LOST, ProspectStage.ARCHIVED):
        path.append(target)

    day = rng.randint(70, 110)  # days ago when the work started
    contact = contacts[0] if contacts else None
    last_activity = None
    opp = None
    for prev, stage in itertools.pairwise(path):
        day = max(day - rng.randint(3, 12), 1)
        when = at(anchor, day, hour=rng.randint(8, 17))
        if stage == ProspectStage.CONTACTED:
            fu = when + timedelta(days=7)
            _add_activity(
                s,
                stats,
                company,
                contact,
                ActivityType.EMAIL_SENT,
                when,
                "Introduction — cybersecurity services",
                follow_up=fu if fu > anchor - timedelta(days=10) else None,
            )
            if rng.random() < 0.5 and len(contacts) > 1:
                _add_activity(
                    s,
                    stats,
                    company,
                    contacts[1],
                    ActivityType.LINKEDIN_MESSAGE,
                    when + timedelta(days=2),
                    "LinkedIn connection",
                )
            if target == ProspectStage.CONTACTED and rng.random() < 0.6:
                _add_activity(
                    s,
                    stats,
                    company,
                    contact,
                    ActivityType.EMAIL_SENT,
                    when + timedelta(days=8),
                    "Follow-up",
                    follow_up=anchor + timedelta(days=rng.randint(-5, 10)),
                )
            last_activity = when
        elif stage == ProspectStage.REPLIED:
            _add_activity(
                s,
                stats,
                company,
                contact,
                ActivityType.REPLY_RECEIVED,
                when,
                "Reply: interested, asks for details",
                direction=ActivityDirection.INBOUND,
            )
            last_activity = when
        elif stage == ProspectStage.MEETING_SCHEDULED:
            future = target == ProspectStage.MEETING_SCHEDULED
            scheduled = (
                (anchor + timedelta(days=rng.randint(2, 15)))
                if future
                else when + timedelta(days=5)
            )
            s.add(
                Meeting(
                    company_id=company.id,
                    contact_id=contact.id if contact else None,
                    scheduled_at=scheduled.replace(hour=rng.choice([9, 10, 14, 16])),
                    duration_minutes=rng.choice([30, 45, 60]),
                    meeting_type="discovery",
                    location="Video call",
                    status=(MeetingStatus.SCHEDULED if future else MeetingStatus.HELD).value,
                    created_at=when,
                    updated_at=when,
                )
            )
            stats["meetings"] += 1
            _add_activity(
                s, stats, company, contact, ActivityType.MEETING, when, "Discovery meeting booked"
            )
            last_activity = when
        elif stage == ProspectStage.OPPORTUNITY_OPEN:
            service = rng.choice(list(ServiceLine))
            low, high = SERVICE_VALUE[service]
            value = Decimal(rng.randrange(low, high, 500))
            opp = Opportunity(
                company_id=company.id,
                primary_contact_id=contact.id if contact else None,
                name=f"{service.label} — {company.company_name}",
                service_line=service.value,
                stage=OpportunityStage.OPEN.value,
                estimated_value=value,
                currency="EUR",
                probability=rng.choice([20, 30, 40]),
                expected_close_date=(anchor + timedelta(days=rng.randint(20, 90))).date(),
                next_action="Prepare scoping questionnaire",
                next_action_date=(anchor + timedelta(days=rng.randint(-3, 14))).date(),
                created_at=when,
                updated_at=when,
            )
            s.add(opp)
            s.flush()
            stats["opportunities"] += 1
            last_activity = when
        elif stage == ProspectStage.PROPOSAL_SENT and opp is not None:
            opp.stage = OpportunityStage.PROPOSAL_SENT.value
            opp.probability = rng.choice([40, 50, 60])
            _add_activity(
                s, stats, company, contact, ActivityType.EMAIL_SENT, when, "Proposal sent", opp=opp
            )
            last_activity = when
        elif stage == ProspectStage.WON and opp is not None:
            opp.stage, opp.probability, opp.closed_at = OpportunityStage.WON.value, 100, when
            opp.won_lost_reason = "Clear scope and fast mobilisation (demo)"
            opp.next_action = None
            last_activity = when
        elif stage == ProspectStage.LOST:
            if opp is not None:
                opp.stage, opp.probability, opp.closed_at = OpportunityStage.LOST.value, 0, when
                opp.won_lost_reason = rng.choice(
                    [
                        "Budget postponed (demo)",
                        "Chose incumbent provider (demo)",
                        "Project cancelled (demo)",
                    ]
                )
            last_activity = when
        _stage_log(s, stats, company, prev, stage, when)
    highest = max(st.order for st in path)
    return {
        "stage": path[-1],
        "highest": highest,
        "changed_at": at(anchor, day) if len(path) > 1 else company.created_at,
        "last_activity": last_activity,
    }
