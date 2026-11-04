# pen.dev workflow

Before the first canvas call in a session, read pen.dev's own skill with `read_skill()`, then
`pen-schema.md`, `execute.md` and `guide/landing-page.md` through it. That guide is authoritative
for the `.pen` format and the `execute` API; this file adds only what is specific to prototypes.

## Access

Use the first channel that works and keep it for the whole run:

1. **Pencil MCP**: the `mcp__pencil__*` tools (`get_app_state` answers). The user sees the canvas
   change live.
2. **`pen` CLI connected to the app**: `pen status` reports logged in, and the pen.dev app is
   running. Drive it with `pen interactive --app desktop --in design/<slug>.pen`.
3. **`pen` CLI headless**: logged in, app not running. Run each batch by piping tool calls in
   and saving:

   ```sh
   printf '%s\n' 'execute({ input: "…" })' 'save()' 'exit()' \
     | pen interactive --in design/<slug>.pen --out design/<slug>.pen
   ```

   Globals do not survive between invocations, so read node ids back with `Get` at the start of
   each batch. The `browser` tool needs the app; in this channel skip the current-site import and
   compare against Playwright screenshots only.

None of them works (`pen` missing, or `pen status` not logged in) → stop and ask the user to run
`npm i -g @pen.dev/cli` and `pen login`, or to open the pen.dev app with the MCP enabled. Use the
agent's own design calls (`execute`); `pen --prompt`, which hands the design to pen.dev's own AI
agent, is outside this workflow because it ignores the token and block rules below.

`Generate` (stock and AI images) needs a signed-in account. When it is unavailable, use styled
placeholder fills and note it in the hub.

## Current site

When the client already has a website and the channel has the browser, load each key page and
`import-to-canvas` it into a frame group named **Current site**, to the left of everything else.
It is reference only: never edit it, never ship from it.

## Directions

For each of 2–3 directions:

1. Pick a `get_style` archetype that fits the brief, then load it with params bent to the brief's
   palette, fonts and imagery. The directions must differ in kind (e.g. editorial vs bold vs warm),
   not in shade.
2. Build one frame `Direction <A|B|C> · <name>` at 1440 wide: the home hero with the brief's real
   copy and primary CTA, then a strip showing palette swatches, the type scale, a button pair and one
   card.
3. `Export` the frames as PNG to `docs/directions/`.

After the gate, move the rejected frames into a group named **Directions (archived)**, record the
choice and the reason in `docs/DECISIONS.md` and the brief, and carry the winner forward.

## Design

Work in this order, verifying each section with a screenshot before the next.

1. **Tokens.** `SetVariables` with exactly this vocabulary, so the names map one to one onto
   Tailwind `@theme` (`--color-<name>`, `--font-<name>`, `--radius-<name>`, `--spacing-<name>`):

   | Kind | Names |
   | --- | --- |
   | color | `bg`, `surface`, `text`, `muted`, `primary`, `primary-fg`, `accent`, `border` |
   | string | `font-display`, `font-body` |
   | number | `radius-sm`, `radius-md`, `radius-lg`, `space-section`, `space-gutter` |

   Add a name only when the design truly needs one more, and log it in `DECISIONS.md`. Dark mode
   (only when the brief asks) is a `mode` theme on the same names.

2. **Components.** One reusable component per block the sitemap uses, named exactly as in
   [blocks.md](blocks.md) (`Hero`, `FeatureGrid`, …), plus `Header`, `Footer`, `Button`. Place
   them at the top of the canvas. Build them yourself; use a `.lib.pen` library such as
   `pencil:shadcn.lib.pen` only when the brief describes an app-like UI.

3. **Pages.** One top-level frame per page, named `Page · <path>` (`Page · /`, `Page · /about`),
   1440 wide, composed of block instances. Mobile frames at 375 wide, named `Page · <path> · mobile`,
   for the home page and one representative inner page only; code derives the other breakpoints
   from these patterns.

4. **Images.** Fill image slots with `Generate("stock", …)`, or `"ai"` when stock cannot express
   it. Generate a wordmark with `Generate("svg", …)` when the client has no logo. Every generated
   image is a placeholder in the code too.

Done check, per page: `Get(page, (n,c) => c.problems && Print(n.name, c.problems))` prints nothing,
and a screenshot shows no collapsed layout, no clipped text, and readable contrast.

## Design to code

Follow pen.dev's `guide/code.md` and `guide/tailwind.md` (via `read_skill`), with these overrides
for this stack:

- Components are **Astro** components in `src/components/blocks/<BlockName>.astro`, not React.
  The component name equals the pen.dev component name equals the `blockType`.
- Variables become Tailwind v4 `@theme` tokens in `src/styles/global.css` with the same names.
  Classes use the tokens (`bg-primary`, `text-muted`), never raw hex.
- Text comes from the content entry passed as props, never from the design file. The design's copy
  is representative.
- Export generated images with `Export([...], "png", "src/assets/generated/")` and reference them
  through `astro:assets`.
- `Export([...], "html-tailwind", …)` is a reference for tricky layouts only; rewrite its output as
  Astro, never paste it in.
- Save PNG exports of every page frame to `design/exports/<version>/` at each tagged version.
