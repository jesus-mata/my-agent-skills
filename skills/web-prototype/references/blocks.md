# Blocks

A **block** is one page section. It is the shared unit across the three layers: a pen.dev
component, an Astro component and a Payload block all carry the same name, so a later move to
Payload changes where the data comes from and nothing else.

Build only the blocks the brief's sitemap uses. The catalogue below gives each block's name and
fields; add a new block in the same shape when the brief needs one that is not listed.

## Content shape

Model content the way Payload stores a `blocks` field:

```ts
// src/content.config.ts (sketch)
const hero = z.object({
  blockType: z.literal('Hero'),
  id: z.string(),
  eyebrow: z.string().optional(),
  heading: z.string(),
  body: z.string().optional(),
  primaryCta: cta,
  secondaryCta: cta.optional(),
  image: media.optional(),
  placeholder: z.boolean().default(false),
});
const block = z.discriminatedUnion('blockType', [hero, featureGrid /* … */]);

const pages = defineCollection({
  loader: glob({ pattern: '**/*.json', base: './src/content/pages' }),
  schema: z.object({ title: z.string(), seo: seo, layout: z.array(block) }),
});
```

- `media` is `{ src, alt, placeholder }`, never a bare string, because Payload stores media as an upload reference.
- `cta` is `{ label, href }`.
- Data repeated across pages (services, team, testimonials, FAQs, posts) is its own collection, and
  blocks reference entries by id, the way Payload uses relationship fields.
- Long text (about copy, posts, legal pages) is Markdown rendered only through `<RichText>`. Payload
  stores rich text as Lexical JSON, so on migration only `RichText.astro` changes, and the Markdown
  needs converting on import. Note this in `CMS-MAPPING.md`.
- `placeholder: true` marks invented copy and generated images, at the field or block level.
- `BlockRenderer.astro` maps `blockType` to the component and renders `layout` in order.

## Catalogue

| blockType | Fields |
| --- | --- |
| `Hero` | eyebrow?, heading, body?, primaryCta, secondaryCta?, image?, variant (`split`, `centered`, `image-bg`) |
| `FeatureGrid` | heading, intro?, items[] { icon, title, body } |
| `FeatureSplit` | heading, body, image, bullets[]?, cta?, imageSide (`left`, `right`) |
| `LogoCloud` | heading?, logos[] media |
| `Stats` | heading?, items[] { value, label } |
| `Testimonials` | heading?, testimonials → collection refs |
| `Pricing` | heading, intro?, plans[] { name, price, period, features[], cta, featured } |
| `FAQ` | heading, faqs → collection refs |
| `Team` | heading, intro?, members → collection refs |
| `Gallery` | heading?, images[] media |
| `CTA` | heading, body?, primaryCta, secondaryCta? |
| `ContactForm` | heading, intro?, fields[] { name, label, type, required }, submitLabel — stubbed |
| `Map` | heading?, address, embedNote — stubbed, static |
| `RichTextBlock` | content (Markdown via RichText) |
| `CardList` | heading, source collection, limit — for services, posts and similar |

`Header` and `Footer` are site-wide components, not blocks; their data lives in
`src/content/site.json` (nav, contact details, socials, legal links).
