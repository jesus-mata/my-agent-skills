# Verify and deploy

## Verify

Run every check before every deploy, and fix what fails before going on.

1. **Build**: `vp run check` (that is `astro check` and `vp check`), then `vp run build`. Both must pass.
2. **Links**: `vp run links` crawls from `/` against `astro preview`. Every internal link must
   return 200, apart from 404-page tests.
3. **Screenshots**: `vp run shots` captures every page at 375, 768 and 1280 wide into
   `docs/screenshots/<version>/`. Look at each one yourself and check for horizontal scroll,
   overlaps, clipped text, broken images, and a mobile menu that opens.
4. **Design comparison**: for each page, put the pen.dev frame export (`design/exports/<version>/`)
   next to the 1280 screenshot, and the mobile frame next to the 375 shot where one exists. Compare
   spacing, type sizes and weights, colour, alignment and section order. Fix the differences in code.
   This gets **two fix passes per page**. Whatever still differs after that goes into
   `docs/DECISIONS.md` as a known gap, with the reason.
5. **Quality**: before each version goes to the client, run Lighthouse (the `lighthouse` npm CLI,
   mobile) on the home page and one inner page. Accessibility should be at least 95, with WCAG AA
   contrast, keyboard reachable nav and forms, visible focus, `alt` on every image, and
   `prefers-reduced-motion` respected. Fix accessibility failures. Log performance scores below 90
   with their cause.

## Deploy

Look up current `wrangler` usage in the docs before the first deploy.

**First deploy**, after the deploy gate in SKILL.md:

1. `wrangler whoami`. If it lists more than one account, ask which one, then put `account_id` in
   `wrangler.jsonc`. Record the account in the brief.
2. In `wrangler.jsonc`, set `name: "<slug>-prototype"`, keep `workers_dev` on, and enable
   `preview_urls`. For a custom domain, add a route on the client's chosen zone.
3. Ship `noindex`: `public/robots.txt` with `Disallow: /`, plus `public/_headers` with
   `/*` → `X-Robots-Tag: noindex`.
4. Access: if the brief says protected, add a Cloudflare Access application with an email one-time
   PIN policy for the listed emails, covering the `workers.dev` hostname and its preview URLs. Use
   the Cloudflare API or MCP if available; otherwise give the user the dashboard steps. Open the URL
   in a private window and confirm it challenges.
5. `vp run deploy`. Load the URL and the hub and confirm both render.
6. Run `git tag v1`, save the page exports to `design/exports/v1/`, write the `v1` entry in
   `docs/CHANGELOG.md` with the URL, and commit.

**Each later version** (Iterate rounds) goes out as a preview, not over the main URL:

```sh
vp run build && wrangler versions upload --preview-alias v<N>
```

This prints `v<N>-<slug>-prototype.<subdomain>.workers.dev`. Tag `v<N>` and add the preview URL
to the changelog. The client can then compare versions side by side.

**Promote**: when the client approves a version, confirm with the user first, then send all
traffic to it with `wrangler versions deploy <version-id>@100% -y`. Record the promotion in the
changelog.

**GitHub**: only if the user said yes at the gate: `gh repo create <slug> --private --source . --push`.
