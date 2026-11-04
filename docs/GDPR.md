# Privacy and GDPR considerations

> CyberLead 360 provides **technical controls that support** GDPR-aligned processes. It does
> **not** make any deployment automatically compliant. The controller (the organization
> using it) remains responsible for its own legal assessment, records and policies.

## Personal data categories
| Category | Fields | Where |
|---|---|---|
| Identification | first name, last name | `contacts` |
| Professional contact details | professional e-mail, business phone, public professional profile URL | `contacts` |
| Professional role | job title, department | `contacts` |
| Interaction data | activity subjects and notes, meeting notes, draft bodies | `activities`, `meetings`, `outreach_drafts` |
| Provenance | source id, collection date, lawful-basis notes | `contacts` |
| Suppression | SHA-256 hash of e-mail (not the e-mail itself) | `suppression_records` |

Company data (name, domain, sector, size, public facts) is **business information** and is
shown in separate screens. Facts are about organizations, not individuals.
**Not collected:** private e-mails, private phone numbers, special-category data, or any
attribute of individuals used for scoring.

## Purposes
B2B prospecting and account management for cybersecurity services: qualifying
organizations, contacting relevant professional roles, and tracking the resulting
commercial relationship.

## Lawful-basis considerations
B2B prospecting of professionals is commonly based on **legitimate interest** (Art. 6(1)(f)),
subject to a documented balancing test, transparency (Art. 14 information when data is not
collected from the person), and national e-privacy rules for electronic marketing, which
vary by country (some require prior consent even in B2B). The `lawful_basis_notes` field
records the basis and context for each contact. The organization must complete the legal
analysis itself.

## Data sources
Manual entry, user-uploaded CSV files and permitted public sources (official corporate
websites, public announcements). Each contact can reference a recorded source with a
collection timestamp. The app never infers e-mail addresses and never scrapes protected
profiles or authenticated pages.

## Retention
`CONTACT_RETENTION_DAYS` (default 730) defines the period after the last contact (or
creation). *Settings → Privacy & retention* lists the contacts beyond the period and
anonymizes them after explicit confirmation. Scheduling this automatically is on the roadmap.

## Access control
Not implemented in the demonstrator (single operator, no authentication). A production
deployment requires authentication and role-based access (see SECURITY.md). Exports of
contact data are audited, and restricted contacts are excluded by default.

## Rights handling
| Right | How |
|---|---|
| Access (Art. 15) | *Contacts → Manage → Prepare data access export*: a JSON file with the contact record, activities, meetings and drafts (audited) |
| Rectification (Art. 16) | Edit form on the contact (audited by field name) |
| Erasure (Art. 17) | *Anonymize* (removes personal data, clears linked free-text notes, keeps anonymous history) or *Delete* (removes the row; activities keep a NULL contact and have their notes cleared). Both are confirmed by typing `ERASE` |
| Objection (Art. 21) | *Record objection*: sets objection + do-not-contact and adds the e-mail hash to the suppression list |
| Restriction | Contact status `do_not_contact` |

## Objection handling and suppression
The suppression list stores **only a SHA-256 hash** of the normalized e-mail, plus optional
whole domains. It is checked when contacts are created (blocks re-adding or re-import),
when drafts are generated, approved and marked sent, when outbound activities are logged,
and when meetings are scheduled. Keeping the hash after erasure prevents accidental
re-contact. Operators can untick this option if they must remove every trace.

## Deletion processes
Contacts: anonymize or delete as above. Companies: archived by default. Hard deletion
cascades to all company-linked data and is intended for erasure requests handled by an
administrator.

## AI processing
Only company information and the recipient's job title are sent to an LLM provider. Names,
e-mails and phones never are. Using an external provider can still be a processor
relationship that needs a DPA, and possibly transfer safeguards. Check the provider's data
retention terms.

## Limitations of the demonstrator
No authentication, no encryption at rest beyond what the database or disk provides, no
automated retention schedule, no DPIA, no consent management, and pattern-based (not
exhaustive) detection of personal data in free text. All demo data is fictional.
