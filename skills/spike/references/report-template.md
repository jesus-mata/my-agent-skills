# Spike report template

Copy everything below the line into `report.md`. Replace every `<...>`. Delete a section's body
and write "n/a, <reason>" when it does not apply. Keep the headings so every report has the
same shape.

---

# Spike: <the question>

> Throwaway spike. This report and any code on `spike/<slug>` exist to inform a decision. Nothing
> here is merged; decisions land through `/grilling`.

**Exit:** <answered | inconclusive | reframed> · **Budget:** <S|M|L>, used <n> research threads,
<n> prototypes/PoCs · **Branch:** `spike/<slug>` · **Issue:** <link or none> · **Date:** <YYYY-MM-DD>

## Question

<the one-sentence question>

**Decision it unblocks:** <what someone decides once this is answered>

**Exit criteria:** <the observable evidence that counts as an answer>

**Out of scope:** <other unknowns spotted and deliberately left for later, or none>

## Context & constraints

<the current state of the code and the stack, plus hard constraints (versions, infrastructure,
compliance, deadlines) that limit the options, each with a file path or link>

## Findings

<numbered findings, one fact each, each ending in its evidence: [source](url), `path/to/file.ts@<sha>`,
or the PoC command and the relevant lines of its output>

1. <finding>. Evidence: <...>

Research notes: <links to research-*.md in this folder>

## Options compared

| Option | How it works | Pros | Cons | Effort | Risk |
| --- | --- | --- | --- | --- | --- |
| <A> | | | | | |
| <B> | | | | | |

## Design artifacts

<whichever the question calls for: an architecture sketch (a mermaid diagram or bullet list of
components and data flow), an API contract (endpoints or function signatures with request and
response shapes), a data model or schema. Mark each as a proposal.>

## Prototype / PoC

<for each one: what it tried, where it lives (folder or files on the branch), the exact command
to run it, and what the run proved or disproved>

## Recommendation

<the recommended option, in one paragraph>

**Confidence:** <high | medium | low>. <what the confidence rests on, and what evidence would
raise it>

## Decisions for grilling

<one entry per decision the evidence leaves open, in the order the grilling should take them.
Each is worded so that "yes" accepts the recommendation.>

❓ **D1** - **<decision title>**: <the question, including the options>

➡️ <recommended answer>. Evidence: <findings by number>

## Still unknown / risks

<claims that could not be backed by evidence, unknowns the budget did not cover, and the risks
of the recommendation, each with what would settle it>

## Reframing

<only when exit is reframed: the question the evidence points to instead, and why. Otherwise
"n/a">
