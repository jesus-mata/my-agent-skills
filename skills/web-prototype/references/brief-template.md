# Brief template

Write this as `docs/BRIEF.md`. Fields marked **(required)** must be filled before the brief gate.
Every other field has a default you state, so the user can just accept it. Keep the brief current:
any later change the client asks for that touches what the site is gets written here.

```md
# <Project name> — Brief

## Product
- **Client / brand** (required):
- **What it is** (required): one paragraph — the product or service, what makes it different.
- **Audience** (required): who visits, what they already know, what they want.
- **Goal of the site** (required): the one outcome a visit should produce.

## Calls to action
- **Primary CTA** (required): label + where it leads (e.g. "Book a demo" → contact form, or the
  client's existing booking or shop tool).
- **Secondary CTA**: default: none.

## Sitemap (required)
| Page | Path | Purpose | Blocks (from references/blocks.md) |
| --- | --- | --- | --- |
| Home | / | | |

Always added: 404. Added when the site has a form: privacy and terms pages, with paths in the site's
language (`/privacidad`, `/terminos`).

## Look and feel
- **Palette** (required, or "recommend"): hex values with roles (primary, accent, background, text).
- **Contrast check**: AA pass/fail and a proposed fix for each of text/bg, muted/bg, muted/surface,
  primary-fg/primary, primary as link/bg, accent-fg/accent, accent as text/bg.
- **Style / tone** (required, or "recommend"): a few adjectives + reference sites the client likes.
- **Chosen direction**: filled at the directions gate — name + `get_style` archetype it started from.
- **Fonts**: default: picked with the direction.
- **Logo and assets**: files provided, or "none" (a wordmark is generated).
- **Dark mode**: default: no.

## Content
- **Language(s)** (required): default: one language. More than one → Astro i18n routing.
- **Copy source**: default: Sources first, realistic invented copy flagged `placeholder: true` for gaps.
- **Future CMS**: may this move to Payload later? (yes / no / unsure) — content is block-shaped either way.

## Features
| Feature | Prototype behaviour | Production needs (→ TODO-BACKEND.md) |
| --- | --- | --- |
| Contact form | UI + validation, "Prototype — not sent" | Workers Action, Turnstile, email |

## Delivery
- **Slug** (required): kebab-case project name, derived from the brand; names the folder, the Worker
  and the repo.
- **Cloudflare account**: name + id (filled at the deploy gate).
- **Worker**: `<slug>-prototype`.
- **URL**: workers.dev (default) or a custom domain on a zone in the account.
- **Access**: public + noindex (default), or Cloudflare Access for these emails: …
- **Repo**: local only (default), or private GitHub repo.

## Sources
### <source title or URL>
- Facts: …
- Usable copy: "…"
- Claims to verify with the client: …
```
