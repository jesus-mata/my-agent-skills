# Iterate

An Iterate round turns one batch of client feedback into a new preview version. The input is
whatever the user pastes: call notes, an email, a list, or crit comments on the live page.

```
Iterate progress:
- [ ] 1. Reconnect: pen.dev channel, docs read
- [ ] 2. Log the feedback
- [ ] 3. Apply design changes in pen.dev
- [ ] 4. Apply code and content changes
- [ ] 5. Verify
- [ ] 6. Ship v<N> as a preview
- [ ] 7. Report
```

## 1. Reconnect

Run the pen.dev access check ([pen-workflow.md#access](pen-workflow.md#access)). Read `BRIEF.md`,
`DECISIONS.md`, the last `FEEDBACK.md` round and the last `CHANGELOG.md` entry. `N` is the last
tag plus one.

## 2. Log the feedback

Add a section to `docs/FEEDBACK.md`:

```md
## v<N> — <date>
Source: <call notes / email / crit>

| # | Client said | Kind | Change | Status |
| --- | --- | --- | --- | --- |
| 1 | "Hero feels too dark" | visual | lighten `bg`, swap hero image | done |
| 2 | "Add a pricing page" | scope | new page /pricing with Pricing block | done |
| 3 | "Can the form send to our CRM?" | backend | → TODO-BACKEND.md | deferred |
```

Each item has one **kind**: `visual` (layout, style, components), `copy` (text and data),
`scope` (pages, blocks or features added or removed), or `backend` (deferred to
`TODO-BACKEND.md`). Ask the user in one round about any item that is ambiguous or contradicts the
brief, before changing anything.

## 3. Design changes

`visual` and `scope` items change the `.pen` file first: tokens, components, page frames. A token
or component change propagates to every instance, so screenshot every affected page. `copy`
items do not touch the design.

## 4. Code and content changes

Carry each design change into the matching Astro component or `@theme` token. Apply `copy` items
in `src/content/` only. When a client supplies real copy or assets, clear the matching
`placeholder: true` flags. Update `BRIEF.md` for anything that changes what the site is, and
`CMS-MAPPING.md` for new or changed blocks.

## 5. Verify

Run all of [verify-deploy.md#verify](verify-deploy.md#verify). The design comparison only needs to
cover the pages that changed.

## 6. Ship

Deploy `v<N>` as a preview ([verify-deploy.md#deploy](verify-deploy.md#deploy)), export the changed
frames to `design/exports/v<N>/`, update the changelog, the hub and the README, then commit and tag.

## 7. Report

Give the user the preview URL and the previous version's URL for comparison, the table from step 2,
and anything deferred. Promoting the version to the main URL waits for the user to say so.
