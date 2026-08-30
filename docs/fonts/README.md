# Vendored fonts

The brand's three families, self-hosted rather than fetched from a CDN. Two
reasons, and the second is the real one:

1. A page that loads a font from a third party tells that third party who read
   it, which is a strange thing for a page about not trusting free things.
2. The `latin` subsets are 30–50 KB each. There is no meaningful bandwidth case
   for a CDN at that size, only a dependency.

All three are licensed under the SIL Open Font License 1.1; the licence text for
each ships beside it. Source of truth for the brand: `Clanker-Labs/branding`.

| File | Family | Used for |
| :--- | :--- | :--- |
| `space-grotesk-latin.woff2` | Space Grotesk | headings, body, labels, eyebrows, nav |
| `source-serif-4-latin-wght.woff2` | Source Serif 4 | the lede |
| `jetbrains-mono-latin.woff2` | JetBrains Mono | code, numbers, terminals |

Space Grotesk is a **variable** file with a `wght` axis of 300–700, which is why
one entry covers what used to take two: Archivo for headings and Archivo Narrow
for labels are now the same face at different weights, and the page makes one
font request instead of two.
