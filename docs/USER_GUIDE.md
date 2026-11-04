# User guide

Start the app with `uv run streamlit run app.py` and open http://localhost:8501. The sidebar
groups the pages into **Overview**, **Prospects**, **Engagement** and **Administration**.

## Home
Shows system status (database, AI mode, retrieval). On an empty database, **Load fictional
demo data** creates the demonstration dataset.

## Dashboard
Headline KPIs, the funnel, companies by stage, follow-ups due within 7 days (overdue ones
flagged), top-priority open prospects and recent activity. Hover the ⓘ icons to see each
rate's formula.

## Companies
* **Browse:** search by name, domain or city, and filter by industry, country, stage,
  employees or score. Results are sorted by score. Select a row to open it.
* **Profile & edit:** score, priority, stage, counts and metadata. Edit any field. The
  *qualification decision* (qualified / nurture / disqualified) is separate from the
  pipeline stage. Use **Archive** (with a reason and confirmation) or **Restore**.
* **Add company:** an exact domain duplicate is refused. A possible duplicate (similar name)
  requires ticking the confirmation box.
* **Import CSV:** download the template, upload a file, and review the preview counts
  (new / possible duplicates / skipped / invalid). Invalid rows are listed with line numbers
  and can be downloaded. Choose the policy for possible duplicates, then import.
* **Duplicates:** review suspected pairs, choose the primary record and the fields to take
  from the duplicate, confirm, and merge. The duplicate is archived, not deleted.
* **Export:** CSV protected against formula injection.

## Contacts
Contact details are personal data, so only professional details belong here. Add a contact
with its source and lawful-basis notes. Under *Manage selected* you can correct data, change
status, **record an objection** (suppresses the e-mail), **anonymize or delete** (type
`ERASE`), and prepare a **JSON access export**. Exports exclude restricted contacts by default.

## Lead Qualification
The ranking table (score, priority, completeness, confidence) can be filtered. Selecting a
company shows the criterion chart, the reasons, the supporting fact ids, missing information
and the score history. A warning appears if some scores use older rule versions, with a
button to recalculate them.

## Company Intelligence
1. **Add source / fact:** record the source first (type, title, URL, date), then the fact
   (type, factual statement, excerpt, confidence). Tick *approve now* only if you checked it
   against the source.
2. **Review queue:** approve or reject pending facts and reclassify their type or confidence.
   Only approved facts count.
3. **Sources:** mark sources verified or rejected, or open the original.
4. **Retrieve website** (only if `ENABLE_WEB_RETRIEVAL=true`): fetches the company's own
   site and creates *pending* candidate facts.
5. **AI summary & analysis:** a grounded profile with unknowns, and possible service
   alignment with evidence and caveats.

## AI Outreach
Choose the company, the recipient (suppressed contacts are excluded and listed), message
type, tone, language, service focus and sender, then **Generate draft**. In *Drafts &
approval*, read the warnings and evidence, edit, **Approve**, send from your own e-mail or
LinkedIn, then **Mark as sent manually**. That logs the activity and advances the stage.

## Sales Pipeline
* **Board:** companies per stage.
* **Change company stage:** only valid transitions are offered. Each change is logged with a note.
* **Opportunities:** create one (service, value, *seller-estimated* probability, close date,
  next action), move it (a loss requires a reason), and edit its details. The company stage
  follows the deal.

## Activities
Log e-mails, calls, LinkedIn messages, replies, notes and follow-ups (optionally advancing
the stage). Complete follow-ups, record meetings (no invitation is sent) and update their
status, and browse the activity feed.

## Analytics
KPIs with formulas, eight charts, metric definitions, and CSV exports of opportunities,
activities and KPIs.

## Settings
* **Scoring rules:** edit the points, size bands, need points, markets and thresholds, check
  the impact preview, add notes, confirm, and publish. Every version is kept.
* **AI provider:** status, budgets and how to configure it (environment variables only).
* **Privacy & retention:** retention run, e-mail and domain suppression.
* **Audit log:** every significant action, with the actor and time.
* **Application:** non-secret configuration summary.
