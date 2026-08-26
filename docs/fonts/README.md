# Vendored fonts

The four Porchlight families, self-hosted rather than fetched from a CDN. Two
reasons, and the second is the real one:

1. A page that loads a font from a third party tells that third party who read
   it, which is a strange thing for a page about not trusting free things.
2. The `latin` subsets are 30–50 KB each. There is no meaningful bandwidth case
   for a CDN at that size, only a dependency.

All four are licensed under the SIL Open Font License 1.1; the licence text for
each ships beside it. Source of truth for the brand: `Clanker-Labs/branding`.

| File | Family | Used for |
| :--- | :--- | :--- |
| `archivo-latin.woff2` | Archivo | headings and body |
| `archivo-narrow-latin.woff2` | Archivo Narrow | labels, eyebrows, nav |
| `source-serif-4-latin-wght.woff2` | Source Serif 4 | the lede |
| `jetbrains-mono-latin.woff2` | JetBrains Mono | code, numbers, terminals |
