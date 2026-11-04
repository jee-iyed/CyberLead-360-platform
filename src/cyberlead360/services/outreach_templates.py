"""Deterministic outreach templates (EN/FR) — the no-API-key generation mode.

A draft is assembled from: greeting → evidence-based hook → service value
statement → call to action → sign-off. Wording varies by tone and message type.
Every statement about the company comes from an approved fact (cited by id).
"""

from __future__ import annotations

from dataclasses import dataclass

from cyberlead360.domain.enums import FactType, Language, MessageType, ServiceLine, Tone
from cyberlead360.services.ai_service import FIRST_NAME_PLACEHOLDER, CompanyContext, GroundingFact

VALUE_EN: dict[ServiceLine, str] = {
    ServiceLine.PENETRATION_TESTING: "We run scoped, authorized penetration tests with clear, prioritized remediation reports.",
    ServiceLine.WEB_SECURITY_AUDIT: "We help teams review the security of customer-facing web applications before and after releases.",
    ServiceLine.NETWORK_ASSESSMENT: "We assess network architecture and segmentation, especially when new sites or offices come online.",
    ServiceLine.CLOUD_SECURITY: "We support cloud programmes with configuration reviews and secure landing-zone design.",
    ServiceLine.SECURITY_AWARENESS: "We run practical security awareness programmes adapted to growing teams.",
    ServiceLine.SOC_MDR: "We provide managed detection and response for teams that need 24/7 monitoring without building a full SOC.",
    ServiceLine.INCIDENT_RESPONSE_READINESS: "We help organizations prepare response plans and run tabletop exercises.",
    ServiceLine.COMPLIANCE_SUPPORT: "We support certification and regulatory programmes (e.g. ISO 27001, NIS2, DORA) with pragmatic gap analyses.",
    ServiceLine.OT_SECURITY: "We specialize in industrial / OT environments, where availability and safety constraints shape security work.",
}
VALUE_FR: dict[ServiceLine, str] = {
    ServiceLine.PENETRATION_TESTING: "Nous réalisons des tests d'intrusion autorisés et cadrés, avec des recommandations priorisées.",
    ServiceLine.WEB_SECURITY_AUDIT: "Nous accompagnons les équipes dans l'audit de sécurité de leurs applications web exposées.",
    ServiceLine.NETWORK_ASSESSMENT: "Nous évaluons l'architecture et la segmentation réseau, notamment lors de l'ouverture de nouveaux sites.",
    ServiceLine.CLOUD_SECURITY: "Nous accompagnons les projets cloud : revues de configuration et conception d'environnements sécurisés.",
    ServiceLine.SECURITY_AWARENESS: "Nous animons des programmes de sensibilisation à la sécurité adaptés aux équipes en croissance.",
    ServiceLine.SOC_MDR: "Nous proposons un service de détection et réponse managé (MDR) avec une surveillance 24/7.",
    ServiceLine.INCIDENT_RESPONSE_READINESS: "Nous aidons les organisations à préparer leurs plans de réponse et à s'entraîner via des exercices de crise.",
    ServiceLine.COMPLIANCE_SUPPORT: "Nous accompagnons les démarches de certification et de conformité (ISO 27001, NIS2, DORA) de manière pragmatique.",
    ServiceLine.OT_SECURITY: "Nous sommes spécialisés dans les environnements industriels / OT, où disponibilité et sûreté priment.",
}


@dataclass(frozen=True)
class TemplateDraft:
    subject: str | None
    body: str
    evidence_fact_ids: list[int]
    notes: list[str]


def pick_hook_fact(ctx: CompanyContext) -> GroundingFact | None:
    order = [
        FactType.SECURITY_NEED_EXPLICIT,
        FactType.SECURITY_SIGNAL,
        FactType.REGULATORY_CONTEXT,
        FactType.GROWTH_EVENT,
        FactType.TECHNOLOGY_CONTEXT,
        FactType.BUSINESS_CONTEXT,
    ]
    for fact_type in order:
        candidates = [f for f in ctx.facts if f.fact_type == fact_type]
        if candidates:
            return max(
                candidates, key=lambda f: (f.observed_at is not None, f.observed_at, f.fact_id)
            )
    return None


def _sentence(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    text = text[0].lower() + text[1:] if not text[:2].isupper() else text
    return text.rstrip(".")


def _hook(ctx: CompanyContext, fact: GroundingFact | None, lang: Language) -> str:
    name = ctx.company_name
    if fact is None:
        if lang == Language.FR:
            return (
                f"Je m'intéresse aux organisations du secteur {ctx.industry_label.lower()} "
                f"comme {name}."
            )
        return (
            f"I work with organizations in the {ctx.industry_label.lower()} sector such as {name}."
        )
    if lang == Language.FR:
        return f"J'ai pris connaissance d'une information publique concernant {name} : « {fact.statement.strip()} »"
    return f"I came across a public update from {name}: {_sentence(fact.statement)}."


def _cta(message_type: MessageType, lang: Language, tone: Tone) -> str:
    fr = lang == Language.FR
    if message_type == MessageType.MEETING_INVITATION:
        return (
            "Seriez-vous disponible pour un échange de 30 minutes dans les deux prochaines semaines ?"
            if fr
            else "Would you be open to a 30-minute call in the next two weeks?"
        )
    if message_type == MessageType.POST_MEETING_FOLLOW_UP:
        return (
            "Comme convenu, je vous propose de planifier la prochaine étape. Quelles dates vous conviendraient ?"
            if fr
            else "As discussed, I suggest we schedule the next step. Which dates would suit you?"
        )
    if message_type == MessageType.FOLLOW_UP:
        return (
            "Je me permets de revenir vers vous : le sujet est-il d'actualité de votre côté ?"
            if fr
            else "I wanted to follow up briefly: is this topic relevant for you at the moment?"
        )
    if tone == Tone.EXECUTIVE:
        return (
            "Un court échange aurait-il du sens pour vous ?"
            if fr
            else "Would a short conversation make sense?"
        )
    return (
        "Seriez-vous ouvert(e) à un bref échange pour voir si cela peut vous être utile ?"
        if fr
        else "Would you be open to a brief conversation to see whether this could be useful?"
    )


def _greeting(lang: Language, tone: Tone) -> str:
    if lang == Language.FR:
        return f"Bonjour {FIRST_NAME_PLACEHOLDER},"
    return (
        f"Hello {FIRST_NAME_PLACEHOLDER},"
        if tone != Tone.CONCISE
        else f"Hi {FIRST_NAME_PLACEHOLDER},"
    )


def _signoff(lang: Language, tone: Tone, sender: str, sender_company: str) -> str:
    if lang == Language.FR:
        closing = "Bien cordialement," if tone != Tone.CONCISE else "Cordialement,"
    else:
        closing = "Best regards," if tone != Tone.CONCISE else "Thanks,"
    return f"{closing}\n{sender}\n{sender_company}"


def _technical_line(service: ServiceLine, lang: Language) -> str:
    if lang == Language.FR:
        return (
            "Notre approche s'appuie sur des référentiels reconnus (OWASP, MITRE ATT&CK, "
            "IEC 62443 selon le contexte) et un périmètre défini avec vos équipes."
        )
    return (
        "Our approach relies on recognized frameworks (OWASP, MITRE ATT&CK, IEC 62443 where "
        "relevant) and a scope agreed with your team."
    )


def _consultative_line(lang: Language) -> str:
    if lang == Language.FR:
        return "J'aimerais surtout comprendre vos priorités actuelles avant de proposer quoi que ce soit."
    return "Above all, I'd like to understand your current priorities before suggesting anything."


def render_template(
    ctx: CompanyContext,
    message_type: MessageType,
    tone: Tone,
    lang: Language,
    service: ServiceLine,
    sender_name: str,
    sender_company: str,
) -> TemplateDraft:
    fact = pick_hook_fact(ctx)
    value = (VALUE_FR if lang == Language.FR else VALUE_EN)[service]
    notes = []
    if fact is None:
        notes.append(
            "No approved fact available: the hook is sector-level only. "
            "Add and review sources to personalize."
        )
    else:
        notes.append(f"Hook based on fact {fact.fact_id} ({fact.fact_type.label.lower()}).")

    if message_type == MessageType.LINKEDIN_CONNECTION:
        if lang == Language.FR:
            body = (
                f"Bonjour {FIRST_NAME_PLACEHOLDER}, "
                + (
                    f"j'ai lu une actualité de {ctx.company_name} qui a retenu mon attention. "
                    if fact
                    else ""
                )
                + f"J'accompagne des acteurs du secteur {ctx.industry_label.lower()} sur "
                f"des sujets de {service.label.lower()}. Au plaisir d'échanger. — {sender_name}"
            )
        else:
            body = (
                f"Hi {FIRST_NAME_PLACEHOLDER}, "
                + (
                    f"I read a recent update from {ctx.company_name} with interest. "
                    if fact
                    else ""
                )
                + f"I work with {ctx.industry_label.lower()} organizations on "
                f"{service.label.lower()} topics. Happy to connect. — {sender_name}"
            )
        return TemplateDraft(
            None,
            body[:300],
            [fact.fact_id] if fact else [],
            [*notes, "LinkedIn connection notes are limited to 300 characters."],
        )

    parts = [_greeting(lang, tone)]
    if message_type in (MessageType.COLD_EMAIL, MessageType.MEETING_INVITATION):
        parts.append(_hook(ctx, fact, lang))
    elif message_type == MessageType.FOLLOW_UP:
        parts.append(
            "Je reviens vers vous suite à mon précédent message."
            if lang == Language.FR
            else "I'm following up on my previous message."
        )
    else:
        parts.append(
            "Merci pour notre échange."
            if lang == Language.FR
            else "Thank you for our conversation."
        )
    parts.append(value)
    if tone == Tone.TECHNICAL:
        parts.append(_technical_line(service, lang))
    elif tone == Tone.CONSULTATIVE:
        parts.append(_consultative_line(lang))
    parts.append(_cta(message_type, lang, tone))
    parts.append(_signoff(lang, tone, sender_name, sender_company))
    body = "\n\n".join(p for p in parts if p)

    subjects_en = {
        MessageType.COLD_EMAIL: f"{service.label} — {ctx.company_name}",
        MessageType.FOLLOW_UP: f"Following up — {service.label}",
        MessageType.MEETING_INVITATION: f"30 minutes on {service.label.lower()}?",
        MessageType.POST_MEETING_FOLLOW_UP: f"Next steps — {ctx.company_name}",
    }
    subjects_fr = {
        MessageType.COLD_EMAIL: f"{service.label} — {ctx.company_name}",
        MessageType.FOLLOW_UP: f"Suite à mon message — {service.label}",
        MessageType.MEETING_INVITATION: f"30 minutes sur le sujet {service.label.lower()} ?",
        MessageType.POST_MEETING_FOLLOW_UP: f"Prochaines étapes — {ctx.company_name}",
    }
    subject = (subjects_fr if lang == Language.FR else subjects_en)[message_type]
    return TemplateDraft(subject, body, [fact.fact_id] if fact else [], notes)
