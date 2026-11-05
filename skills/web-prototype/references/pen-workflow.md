# pen.dev workflow

Before the first canvas call of a new prototype, read pen.dev's own skill with `read_skill()`,
then `pen-schema.md`, `execute.md` and `guide/landing-page.md` through it. In an Iterate round,
`pen-schema.md` and `execute.md` are enough. pen.dev's guides are authoritative for the `.pen`
format and the `execute` API; where they disagree with this file on *what to build*, this file
wins (see [Conflicts](#conflicts)).

## Access

Use the first channel that works and keep it for the whole run:

1. **Pencil MCP**: the `mcp__pencil__*` tools (`get_app_state` answers). The user sees the canvas
   change live.
2. **`pen` CLI connected to the app**: `pen status` reports logged in, and
   `pen interactive --app desktop` connects (it fails fast when the app is not running).
3. **`pen` CLI headless**: logged in, app not running. Run every batch through the bundled
   helper, which JSON-encodes snippet files so multi-line JavaScript needs no escaping:

   ```sh
   node <skill-dir>/scripts/pen-run.mjs design/<slug>.pen tokens.js hero.js
   node <skill-dir>/scripts/pen-run.mjs design/<slug>.pen --read-only check.js 'read_skill({path:"execute.md"})'
   ```

   Steps in one call share globals; separate calls do not, so read node ids back with `Get` at the
   start of each batch. Use `--read-only` for queries so they never rewrite the design file.
   `TakeScreenshot` images are not visible here: verify by `Export`ing the section to PNG in a
   temp folder and viewing the file. The `browser` tool needs the app, so skip the current-site
   import and compare against Playwright screenshots only.

None of them works (`pen` missing, or `pen status` not logged in) → stop and ask the user to run
`npm i -g @pen.dev/cli` and `pen login`, or to open the pen.dev app with the MCP enabled. Use the
agent's own design calls (`execute`); `pen --prompt`, which hands the design to pen.dev's own AI
agent, is outside this workflow because it ignores the token and block rules below.

`Generate` (stock and AI images) needs a signed-in account. When it is unavailable, use styled
placeholder fills and note it in the hub.

## Conflicts

pen.dev's guides are written for generic designs; for client prototypes these rules win:

- **The brief's palette and fonts win** over any `get_style` rule. Its archetypes ban cream or
  beige backgrounds and some hero layouts; when the client's brand uses them, use them.
- **`get_style` takes named palette presets, not hex values.** Pick the nearest preset to get the
  archetype's type, spacing and imagery rules, then recolour with the brief's tokens.
- **Tokens go in Tailwind `@theme`**, not `:root` as pen's `tailwind.md` suggests, and font tokens
  carry a fallback stack.
- **Components are Astro**, not the React `.tsx` that pen's `code.md` assumes; its per-component
  validation loop is replaced by the page comparison in Verify.

## Current site

When the client already has a website and the channel has the browser, load each key page and
`import-to-canvas` it into a frame group named **Current site**, to the left of everything else.
It is reference only: never edit it, never ship from it.

## Directions

For each of 2–3 directions:

1. Pick a `get_style` archetype that fits the brief and recolour it per [Conflicts](#conflicts).
   The directions must differ in kind (e.g. editorial vs bold vs warm), not in shade.
2. Build one frame `Direction <A|B|C> · <name>` at 1440 wide: the home hero with the brief's real
   copy and primary CTA, then a strip showing palette swatches, the type scale, a button pair and one
   card.
3. `Export` the frames as PNG to `docs/directions/`.

After the gate, move the rejected frames into a group named **Directions (archived)**, record the
choice and the reason in `docs/DECISIONS.md` and the brief, and carry the winner forward.

## Design

Work in this order, verifying each section before the next.

1. **Tokens.** `SetVariables` with exactly this vocabulary, so the names map one to one onto
   Tailwind `@theme` (`--color-<name>`, `--font-<name>`, `--radius-<name>`, `--spacing-<name>`):

   | Kind | Names |
   | --- | --- |
   | color | `bg`, `surface`, `text`, `muted`, `primary`, `primary-fg`, `accent`, `accent-fg`, `border` |
   | string | `font-display`, `font-body` |
   | number | `radius-sm`, `radius-md`, `radius-lg`, `space-section`, `space-gutter` |

   `accent-fg` is the text colour on accent fills. Add a name only when the design truly needs one
   more (for example `accent-text` when the accent fails contrast as text), and log it in
   `DECISIONS.md`. Dark mode (only when the brief asks) is a `mode` theme on the same names.

2. **Components.** One reusable component per block the sitemap uses, named exactly as in
   [blocks.md](blocks.md) (`Hero`, `FeatureGrid`, …), plus `Header`, `Footer`, `Button`. A block
   with layout variants gets one component per variant used, named `<Block> · <variant>`
   (`Hero · split`); in code that is one component with a `variant` prop. pen.dev has no
   responsive components, so build a `<Block> · mobile` component for each block the mobile frames
   use. Place components at the top of the canvas. Build them yourself; use a `.lib.pen` library
   such as `pencil:shadcn.lib.pen` only when the brief describes an app-like UI.

3. **Pages.** One top-level frame per page, named `Page · <path>` (`Page · /`, `Page · /about`),
   1440 wide, composed of block instances. Mobile frames at 375 wide, named `Page · <path> · mobile`,
   for the home page and one representative inner page only, composed of the mobile components;
   code derives the other breakpoints from these patterns.

4. **Images.** Fill image slots with `Generate("stock", …)`, or `"ai"` when stock cannot express
   it. Look at every result and re-query any that shows a third-party brand, contradicts the copy
   (the wrong person for a named team member, the wrong product) or clashes with the direction.
   Copy the chosen fill to the mobile frame instead of generating again, so both use the same
   photo. Generate a wordmark with `Generate("svg", …)` when the client has no logo. Every
   generated image is a placeholder in the code too.

Done check, per page: `Get(page, (n,c) => c.problems && Print(n.name, c.problems))` prints nothing,
and a visual check shows no collapsed layout, no clipped text, and readable contrast.

## Design to code

Follow pen.dev's `guide/code.md` and `guide/tailwind.md` (via `read_skill`), with the
[Conflicts](#conflicts) rules and these for this stack:

- Components are `src/components/blocks/<BlockName>.astro`. The component name equals the pen.dev
  component name (minus ` · <variant>` and ` · mobile`) equals the `blockType`.
- Variables become `@theme` tokens in `src/styles/global.css` with the same names. Classes use the
  tokens (`bg-primary`, `text-muted`), never raw hex.
- Text comes from the content entry passed as props, never from the design file. The design's copy
  is representative, except facts (contact details, prices, names), which are kept in sync with the
  content so exports never show wrong data.
- Generated images: take the image fill's source URL (`Get` the node, read its `fill`) and download
  the file into `src/assets/generated/`. Exporting the node instead bakes any text on top into the
  picture.
- `Export([...], "html-tailwind", …)` is a reference for tricky layouts only; rewrite its output as
  Astro, never paste it in.
- Save PNG exports of every page frame to `design/exports/<version>/` at each tagged version.
