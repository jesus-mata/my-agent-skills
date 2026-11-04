# Scaffold

Scaffold fresh every time so the project starts on current versions. Before running anything,
look up the current commands in the docs (Astro, `@astrojs/cloudflare`, Tailwind, Vite+) with the
docs tool you have. The shape below is stable; exact flags and versions are not.

## Stack

| Concern | Choice |
| --- | --- |
| Framework | Astro, latest major, TypeScript strict |
| Hosting | `@astrojs/cloudflare` adapter on Workers; every page prerendered by default, so a server route or Action can be added later without restructuring |
| Styling | Tailwind v4 through `astro add tailwind` (`@tailwindcss/vite`), tokens in `@theme` |
| Package manager | pnpm |
| Tooling | Vite+ (`vite-plus`, CLI `vp`) for lint, format, test, git hooks and running scripts |
| Fonts | Fontsource packages, self-hosted |
| Icons | `astro-icon` with an Iconify set matching the design |
| Images | `astro:assets` |
| SEO | `@astrojs/sitemap` + a `<SEO>` component |
| Browser checks | Playwright as a dev dependency |
| UI framework | none; add a React or Preact island only for interactivity Astro cannot do with a small script |

Add any other library only when a brief requirement calls for it (carousel, animation, blog
search…), and log the library and the reason in `docs/DECISIONS.md`.

**Vite+ with Astro.** Vite+ does not drive Astro: `vp dev` and `vp build` start plain Vite. Keep
`astro dev`, `astro build` and `astro check` as package scripts and run them through `vp run <script>`.
Put lint, format and test settings in a small root `vite.config.ts` from `vite-plus`. On the first
run, check whether Oxfmt formats `.astro` files; when it does not, format them with Prettier and
`prettier-plugin-astro`, and record which one you used in `DECISIONS.md`. Keep `astro check`, since
`vp check` does not type-check `.astro` files.

## Scripts

| Script | Runs |
| --- | --- |
| `dev` | `astro dev` |
| `build` | `astro build` |
| `check` | `astro check` then `vp check` |
| `shots` | `scripts/screenshots.ts` (Playwright) |
| `links` | `scripts/links.ts` (Playwright crawl from `/`) |
| `deploy` | build then `wrangler deploy` |
| `deploy:preview` | build then `wrangler versions upload` |

## Layout

```
design/
  <slug>.pen
  exports/<version>/          page PNGs per tagged version
docs/
  BRIEF.md  DECISIONS.md  FEEDBACK.md  CHANGELOG.md  TODO-BACKEND.md  CMS-MAPPING.md
  directions/                 direction PNGs
  screenshots/<version>/      Playwright shots
scripts/screenshots.ts  scripts/links.ts
src/
  components/
    blocks/<BlockName>.astro  one per blockType
    BlockRenderer.astro       blockType → component map
    SEO.astro  RichText.astro  Header.astro  Footer.astro  PrototypeBadge.astro
  content.config.ts           Zod schemas (see blocks.md)
  content/pages/*.json        one entry per page: seo + layout[]
  content/<collection>/       repeated data: services, team, testimonials, faqs, posts…
  layouts/Base.astro
  pages/[...slug].astro       renders a pages entry
  pages/404.astro
  pages/styleguide.astro      tokens + every built block
  pages/prototype/index.astro the hub, at /prototype
  styles/global.css           @import "tailwindcss"; @theme { … }
wrangler.jsonc
README.md
```

The hub (`/prototype`) and `PrototypeBadge` sit behind one `PROTOTYPE` flag (an env var read in
the Astro config), so turning them off for production is one change. The hub lives in one folder
that is deleted whole. (Astro skips `_`-prefixed folders when routing, so the hub cannot be `/_prototype`.)

## Prototype-only behaviour

- **`noindex`**: `robots.txt` disallows everything, and the Worker sends `X-Robots-Tag: noindex`.
  Both are switched by the same `PROTOTYPE` flag.
- **Badge**: a small fixed "Prototype vN" pill linking to the hub.
- **Hub**: page list with links; versions with preview URLs and changelog entries (from
  `docs/CHANGELOG.md`); every `placeholder: true` item grouped by page; missing assets; stubbed
  features from `TODO-BACKEND.md`.
- **Stubs**: forms validate client-side and show "Prototype — not sent" on submit; maps are a static
  image or a styled block with the address.

## Docs files

| File | Holds |
| --- | --- |
| `BRIEF.md` | the brief (see brief-template.md) |
| `DECISIONS.md` | one dated line per decision and its reason: direction, libraries, token additions, unresolved design gaps |
| `FEEDBACK.md` | one section per feedback round (see iterate.md) |
| `CHANGELOG.md` | one entry per tagged version: date, preview URL, what changed |
| `TODO-BACKEND.md` | per stubbed feature: what it needs (Worker route or Action, Turnstile, email service, API keys, analytics) |
| `CMS-MAPPING.md` | per schema: future Payload collection or block, field mapping, pen.dev component name, rich-text note |

`README.md` is for the developer who continues the site: stack, scripts, folder map, how to add a
page and a block, how to deploy, links to `docs/`, and a **prototype → production checklist**
(turn off `PROTOTYPE`, replace every `placeholder: true`, implement `TODO-BACKEND.md`, connect the
domain, optionally migrate content to Payload per `CMS-MAPPING.md`).
