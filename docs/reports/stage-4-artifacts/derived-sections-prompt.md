# Prompt for the derived-sections addendum to Stage 4 (owner's instruction, 2026-10-08)

This is the instruction the commit under review implements (schema pack v3, type `re_rtc`,
the two derived sections and the producer tag `DERIVED`). It stands in for a stage prompt
in the independent review; the "draft stage report" to judge under (e) is the section
"Derived tables: a third pass, over decisions, without a model (2026-10-08)" of
`docs/ARCHITECTURE.md`, the dated lines of `docs/DECISIONS.md` and the entries of
`docs/KNOWN-GAPS.md` in the diff.

---

New tender and two schema additions. The WBSEDCL RE-RTC tender (RFQ WBSEDCL/PT&P/RE-RTC/2026/01, 23.09.2026, 1500 MW + 500 MW greenshoe) is attached/at <path>. It is our first state discom and a new type, and it breaks an assumption: it is called an RE tender but permits up to 49% from any source including thermal and market purchases, with RECs supplied to cover the non-RE share.

1. Ingest it as the 14th tender, type re-rtc, agency WBSEDCL, from wbsedcl.in. Both sections (RfQ Section A and RfP Section B) are one document. Add a re-rtc schema to the power pack. Fields the existing schemas lack, which this tender needs:
- traceable_green_min_pct, with its definition and the RECs obligation for the balance
- cuf_annual_min_pct, cuf_monthly_min_pct, cuf_peak_min_pct and the peak window (4 hours daily, single or multiple stretches at the procurer's discretion)
- greenshoe_capacity_mw, greenshoe_exercise_deadline, greenshoe_ssd, greenshoe_tariff_basis (same tariff as base)
- linked_capacity_obligation: the mandatory solar installation at a multiple of contracted supply (2x here), its acres per MW, and the staged land and connectivity document deadlines (50% at 3 months from LOA, 50% at 6 months)
- non_re_tariff_split: fixed and variable percentages and the merit-order treatment
- bid_security_instruments and pbg_instruments as enums, since this one allows BG, eBG, insurance surety bond, POI from IREDA/PFC/REC, and demand draft
- financial capacity needs an EBITDA field alongside net worth and turnover
- technical_experience here is a single station of at least 1200 MW operated continuously for five years, which the existing experience field cannot express; add min_single_station_mw and min_continuous_operation_years

2. Source eligibility, as a derived table. After extraction, produce for each tender a table with one row per source: solar, wind, hydro, biomass, BESS, pumped storage, thermal, market or exchange purchase, other. Each row has: status (allowed, allowed_with_limit, required, prohibited, not_addressed), limit value and unit where one applies, and the evidence that supports it.

This is a derivation, not an extraction, so it follows these rules:
- Every row cites the clause it derives from, by page and quote. A row with no clause behind it is `not_addressed`, never an assumption from the tender type.
- The derivation is deterministic code over approved fields and clause text, not a model judgement. Add a fifth producer tag DERIVED to FIELD-TRACE, ARCHITECTURE.md and the master prompt's column definition.
- Reviewers approve the table like any other field, with the clause on screen.
- Test it against three cases: this tender (thermal allowed to 49%, RECs required, BESS allowed but must be RE-charged and co-located per CERC sharing regulations), seci-fdre-ix (storage mandatory, thermal prohibited), and an EPC tender (not_addressed throughout, since the question does not arise).

3. Optimizer constraints. Add a section to each tender's record holding the constraints an optimisation engine must satisfy, derived from approved fields, each carrying the field and evidence it came from. For this tender they include: minimum 51% traceable green annually; 80% annual, 70% monthly and 90% peak-hour CUF; a 4-hour daily peak window set by the procurer; RECs for all non-RE supply; BESS charged only from RE and co-located; solar capacity installed at 2x contracted supply; supply start 01.07.2028 for the base and 01.04.2029 for the greenshoe; 25-year term; and the 70/30 fixed-variable treatment of non-RE under merit order. Constraints are typed (quantity with unit and comparator, temporal, boolean obligation) so the engine reads them rather than parsing prose. Same provenance and review rules as the source table.

Design the schema and the two derived sections first and show me the field list and the constraint types before extracting. Do not run the full corpus until I have seen them.

---

Follow-up after the design was shown: "Yes to both" (thermal and market purchase inherit the general non-RE clause's 49% limit, with basis `inherited`; the peak window is both a quantity and an obligation). "Also fetch the draft PPA from wbsedcl.in or the TCIL ETS portal and attach it as a document with role ppa on this tender's version, so the commercial and penalty fields have a source. If it is behind the portal login, say so and I will download it. For the UI: a derived source row whose status is inherited from a general clause rather than a clause naming that source must be visually distinct from a directly stated one, so a reviewer sees the derivation rather than reading it as a printed fact."

---

## Later instructions in the same range (2026-10-12 and 2026-10-13)

The commits after the derived sections (`c3c3769`, `59d2916`, `0dfb85d`, `5fff42b`) implement
these owner instructions, given in the operating phase. The "draft stage report" to judge
under (e) for them is the "what changed" entries dated 2026-10-12 and 2026-10-13 in
`docs/ARCHITECTURE.md`, the lines of those dates in `docs/DECISIONS.md`, and the entries of
`docs/KNOWN-GAPS.md` in the diff.

1. "Do any other build task like making the UI for the final application. Making amendment
   review screen." Scope as recorded: a second screen of the review link, per later version
   the fields it states against what stood before, typed added/changed/restated, with that
   version's evidence and the reviewer's decision, using the same decisions and the same
   `POST /approvals` as the review screen; the summary and the derived tables are not
   amendment changes. Also: re-source the `ntpc-hybrid-03` RfS from an NTPC domain and
   compare hashes (record the outcome if it cannot be done).
2. "Can you continue building." From the owner's review of NHPC FDRE-II: a note may accompany
   Approve or Not in document, not only an edit, stored on the approval and shown on the
   decision line; the reviewer's keys work on the amendment screen; the reliability report
   and dashboard show accuracy by key for structured fields.
3. "Check the status and continue the build." From the owner's edit of the NTPC PHES
   optimiser table (its rows held the power capacity and the term; the edit listed the
   energy procured, the project size limits, the location, the commissioning deadline and
   the term): optimiser constraints rule v2, every row still from one decided field and
   its clause, nothing computed; an approved table stays as approved.
4. "All six, make gold." Gold records for the six reviews completed on 2026-10-13, then
   `make eval` and `make report`; the scorer must take each gold field's candidate from the
   version the record shows it from.

Standing rules that apply throughout: a reviewer's decision is the only source of a
canonical value; the owner's approval rows are never changed by code; gold records are made
only on the owner's word; no secret or review token appears in the repo.
