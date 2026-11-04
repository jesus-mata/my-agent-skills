---
name: web-prototype
description: Designs a client website in pen.dev and builds it as a navigable Astro + Tailwind prototype deployed to a Cloudflare Worker, which then becomes the foundation for real development. Use when the user wants a web design prototype, mockup or landing page to show a client, or wants to apply client feedback to an existing prototype.
---

# Web prototype

A **prototype** here is two things at once: the design the client reviews, and the codebase the
real site grows from. So it is built like production (current stack, typed content, real
components) and marked like a prototype (`noindex`, version badge, placeholders flagged for
replacement). The client reviews the **deployed, navigable site**, never static frames alone.

Three files decide who is right about what:

- **`docs/BRIEF.md`**: the source of truth for *what* the site is.
- **`design/<slug>.pen`**: the source of truth for *how it looks* (layout, tokens, components).
- **`src/content/`**: the source of truth for *copy and data*.

A visual change always lands in the `.pen` file first and is then carried into code. Code that
drifts from the design makes the design file worthless.

## Mode

- `docs/BRIEF.md` and `design/*.pen` exist in the current directory → **Iterate**: follow
  [references/iterate.md](references/iterate.md) and skip the checklist below.
- Otherwise → **New prototype**: copy the checklist and tick it off.

```
Web prototype progress:
- [ ] 0. Preflight: pen.dev reachable and logged in
- [ ] 1. Brief                       — GATE: user confirms BRIEF.md
- [ ] 2. Style directions            — GATE: a direction is chosen
- [ ] 3. Design in pen.dev
- [ ] 4. Scaffold the project
- [ ] 5. Build from the design
- [ ] 6. Verify
- [ ] 7. Deploy v1                   — GATE: account, Worker name, access
- [ ] 8. Hand off
```

Run straight through between gates. At a **gate**, stop, show what you have, and wait for the
user's answer. Commit at the end of every step from 4 on.

## 0. Preflight

Find a pen.dev channel in the order given in
[references/pen-workflow.md#access](references/pen-workflow.md#access). If none works, stop and
tell the user exactly what to install or log in to. There is no code-first fallback. Done when you
know which channel the whole run will use.

## 1. Brief

Fill [references/brief-template.md](references/brief-template.md) from what the user gave you. Read
every source they pass (URLs, PDFs, docs, an existing site) and extract facts, copy and claims
into `## Sources`, each attributed. Ask for every **required** field still empty in one
numbered round, each with your recommended answer. Recommend the style and tone from the product
description when the user has none. Check the palette for WCAG AA contrast and propose the
nearest passing shades for any failing pair, rather than altering it silently.

The brief is written to `docs/BRIEF.md` once the project folder exists (step 4); until then keep
it in the conversation. **Gate:** done when every required field is filled and the user confirms
the brief.

## 2. Style directions

Design 2–3 distinct directions in pen.dev as described in
[references/pen-workflow.md#directions](references/pen-workflow.md#directions): each one a hero with
the brief's real copy plus a mini style guide, starting from the closest `get_style` archetype and
bent to the brief's palette and tone. Export them as PNGs and present them with one paragraph each
(the mood, who it suits, the risk). **Gate:** done when the user names a direction.

## 3. Design in pen.dev

Follow [references/pen-workflow.md#design](references/pen-workflow.md#design): tokens, one component
per block, then every page at desktop plus the mobile frames it lists. Use the shared vocabulary in
[references/blocks.md](references/blocks.md) so a block has one name in pen.dev, Astro and the
future CMS. Done when every page in the brief's sitemap has a finished desktop frame and no frame
reports layout problems.

## 4. Scaffold the project

Follow [references/scaffold.md](references/scaffold.md). Look up current setup commands in the
docs before running them; versions move fast. Move the `.pen` file into `design/`, write
`docs/BRIEF.md` and the other docs files, `git init`, and commit. Done when `astro dev` serves
an empty layout styled with the design's tokens.

## 5. Build from the design

Translate the design into code with pen.dev's own `code` and `tailwind` guides (`read_skill`),
using the rules in [references/pen-workflow.md#design-to-code](references/pen-workflow.md#design-to-code).
Build components block by block, then compose pages from content entries. Copy comes from
`## Sources` first; write realistic copy in the brief's language where none exists and mark it
`placeholder: true`. Forms, maps and other backend features get a working UI and a stub, each
logged in `docs/TODO-BACKEND.md`. Done when every page renders from content, every nav link
resolves, and the hub page lists everything.

## 6. Verify

Run the checks in [references/verify-deploy.md#verify](references/verify-deploy.md#verify). Done when
the build is green, there are no broken links, and each page passed the design comparison or has
its leftover gaps logged in `docs/DECISIONS.md`.

## 7. Deploy v1

Follow [references/verify-deploy.md#deploy](references/verify-deploy.md#deploy). **Gate:** before the
first deploy, confirm the Cloudflare account, the Worker name `<slug>-prototype`, the URL
(`workers.dev` or a custom domain) and who can open it (public with `noindex`, or Cloudflare
Access). Offer to create a private GitHub repo and run `gh repo create` only on a yes. Done
when the URL loads, the hub is reachable, and `v1` is tagged with its preview URL in
`docs/CHANGELOG.md`.

## 8. Hand off

Give the user:

- the prototype URL and the hub URL
- what is placeholder or stubbed (pointing at the hub, not repeating it)
- how to run a feedback round: paste the client's feedback in a new session in this folder
