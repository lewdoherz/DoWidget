# Provider logo sources

Retrieved on **2026-10-12**. These provider marks identify the corresponding services inside DoWidget; they are not DoWidget's application branding.

## DeepSeek — `deepseek.png`

- Official source page: <https://www.deepseek.com/>.
- Direct source: <https://www.deepseek.com/favicon.ico>, linked by the homepage as its `rel="icon"` with `sizes="225x225"`.
- Asset: the original identifiable blue whale, **225 × 225 pixels**, with transparency.
- Conversion: downloaded the original ICO bytes, decoded with PySide6 `QImage.fromData`, and saved as PNG at the original dimensions. No cropping, resizing, recoloring, redrawing, rotation, or change to the logo geometry.
- DeepSeek's name and whale logo remain the property of their respective rights holders. Retrieval from the official website is provenance, not a grant of a trademark license or a statement that the asset is public domain. Use is limited to identifying the DeepSeek integration; follow any applicable provider terms and obtain permission where required.

## OpenAI — `openai.png`

- Official source and usage-guidelines page: <https://openai.com/brand/>.
- Direct source: <https://openai.com/apple-icon.png?apple-icon.3o0tf8iy4mx7y.png>, linked in that page's HTML as its `rel="apple-touch-icon"` with `sizes="180x180"`.
- Asset: the official standalone black Blossom on its original white background, **180 × 180 pixels**. The source's surrounding space and original background are retained.
- Conversion: downloaded the official PNG bytes, decoded with PySide6 `QImage.fromData`, and saved as PNG at the original dimensions. No cropping, resizing, recoloring, redrawing, rotation, or change to the logo geometry.
- The official website icon is used instead of the brand page's `Blossom_Light.svg` spacing illustration, which includes multiple logos and guides and is not a standalone logo asset.
- OpenAI owns its name and marks. See the [design guidelines](https://openai.com/brand/) and [Marks usage terms](https://openai.com/brand/#usage-terms). Those terms limit permission to compliant, non-exclusive, non-transferable use; permit review, changes, and termination; and require that OpenAI's marks not be more prominent than the application's own branding. Use this logo only in relation to OpenAI services, without alteration or any implication of endorsement. The Blossom must not be DoWidget's primary branding.

## Claude — `claude.png`

- Official source page: <https://platform.claude.com/>, the Claude Developer Platform (Claude Console), where Claude API keys are created and managed.
- Direct source: <https://platform.claude.com/apple-touch-icon.png>, declared by that page's own HTML as `<link rel="apple-touch-icon" href="/apple-touch-icon.png"/>` (alongside `<link href="/apple-touch-icon.png" rel="apple-touch-startup-image"/>`).
- The same page also declares `<link rel="icon" href="/favicon.svg" type="image/svg+xml" sizes="any"/>` and `<link rel="icon" href="/favicon.ico" sizes="32x32"/>`. That declared SVG draws the identical mark in the identical palette — a rounded 32 × 32 tile, `fill="#30302E"`, plus the sparkle, `fill="#D97757"` — so the downloaded PNG is Claude's own icon and not a third-party imitation.
- Asset: the official Claude sparkle in Claude coral **`#D97757`** on the official dark rounded tile **`#30302E`**, corners transparent, **180 × 180 pixels**, 32-bit RGBA, served from Anthropic's own domain.
- Conversion: the original PNG bytes are bundled unmodified. No decode/re-encode, cropping, resizing, recoloring, redrawing, or rotation; the source's own padding and background tile are retained.
- Anthropic owns the Claude name and marks. Retrieval from Anthropic's official site is provenance, not a grant of a trademark license or a statement that the asset is public domain. Use is limited to identifying the Claude integration; follow Anthropic's applicable terms and brand guidance and obtain permission where required.

## Gemini — `gemini.png`

- Official source page: <https://gemini.google.com/>, the Gemini web app.
- Direct source: <https://www.gstatic.com/lamda/images/gemini_sparkle_4g_512_lt_f94943af3be039176192d.png>, declared by that page's HTML as `<link rel="icon" href="https://www.gstatic.com/lamda/images/gemini_sparkle_4g_512_lt_f94943af3be039176192d.png" sizes="512x512">` and again as `<link rel="apple-touch-icon-precomposed" … sizes="512x512">`. The file is served from Google's `gstatic.com` asset host.
- Asset: the official Gemini four-point sparkle in Google's gradient, **512 × 512 pixels**, 32-bit RGBA on a transparent background, exactly as Google serves it, including Google's own margin above the mark and the points that reach the canvas edges.
- Conversion: the original PNG bytes are bundled unmodified. No decode/re-encode, cropping, resizing, recoloring, redrawing, or rotation; the source's own padding is retained.
- Google owns the Gemini and Google names and marks. See the [Brand Resource Center](https://about.google/brand-resource-center/). Retrieval from Google's official pages is provenance, not a trademark license; use is limited to identifying the Gemini integration, without alteration or any implication of endorsement, and follow Google's brand guidance and terms.
- Gemini's published limits are enforced per Google Cloud project rather than per API key, and Google prints the active limits in AI Studio rather than as a subscription percentage, so the mark identifies the integration only and implies no subscription quota.

## Grok — `grok.png`

- Official source page: <https://grok.com/>, the Grok web app.
- Direct source: <https://grok.com/images/apple-touch-icon.png>, declared by that page's HTML as `<link rel="apple-touch-icon" sizes="180x180" href="/images/apple-touch-icon.png"/>`. The same page also declares `/images/favicon.svg`, `/images/favicon.ico`, `/images/android-chrome-192x192.png`, and `/images/android-chrome-512x512.png`; the declared 180 × 180 touch icon is used because it carries the mark at its own inset, while the 512 × 512 variant is a full-bleed black square.
- Asset: the official Grok mark in white on the official black rounded tile **`#050505`**, corners transparent, **180 × 180 pixels**, 32-bit RGBA.
- Conversion: the original PNG bytes are bundled unmodified. No decode/re-encode, cropping, resizing, recoloring, redrawing, or rotation; the source's own padding and background tile are retained.
- xAI owns the Grok name and marks. Retrieval from the official Grok site is provenance, not a grant of a trademark license or a statement that the asset is public domain. Use is limited to identifying the Grok integration; follow any applicable provider terms and obtain permission where required.

## GLM — `glm.png`

- Official source page: <https://docs.z.ai/>, Z.AI's official GLM API documentation site, the platform whose GLM models DoWidget's `glm` provider refers to.
- Direct source: <https://docs.z.ai/mintlify-assets/_mintlify/favicons/zhipu-32152247/ksfquWFAc8TQf_Hb/_generated/favicon/android-chrome-192x192.png>, declared by that page's HTML as `<link rel="icon" href="…/android-chrome-192x192.png" type="image/png" sizes="192x192" media="(prefers-color-scheme: light)"/>`; the site also declares a dark-background variant from the sibling `favicon-dark/` directory, plus 16 × 16, 32 × 32, and `apple-touch-icon` variants. The `zhipu-32152247` path is Z.AI/Zhipu's own favicon set for its documentation site.
- The `rel="shortcut icon"` declared by <https://z.ai/> and <https://chat.z.ai/> is <https://z-cdn.chatglm.cn/z-ai/static/logo.svg>, which draws the same “Z” mark that this PNG contains; only the raster favicon is bundled so no vector rendering is required at build time.
- Asset: the official Z.AI “Z” mark in white on the official dark rounded tile, corners transparent, **192 × 192 pixels** (indexed-colour PNG with an alpha channel), displayed as 32-bit RGBA.
- Conversion: the original PNG bytes are bundled unmodified. No decode/re-encode, cropping, resizing, recoloring, redrawing, or rotation; the source's own padding and background tile are retained.
- Z.AI/Zhipu owns the Z.AI and GLM names and marks. Retrieval from Z.AI's official site is provenance, not a grant of a trademark license or a statement that the asset is public domain. Use is limited to identifying the GLM integration; follow any applicable provider terms and obtain permission where required.

## Display and attribution

Preserve each image's aspect ratio, colors, original padding, and any background. Place every provider image within an uncluttered, neutral light provider tile with additional clear space, and never re-tint, recolor, or re-theme it: the OpenAI image and the transparent Gemini and DeepSeek marks belong on that neutral tile, while the Claude, Grok, and GLM images keep their own official dark tiles and are not inverted or restyled to match DoWidget's theme. Runtime downscaling for display is not a replacement or modification of these source PNG files.

DoWidget is an independent application and is not affiliated with, sponsored by, or endorsed by DeepSeek, OpenAI, Anthropic (Claude), Google (Gemini), xAI (Grok), or Z.AI (GLM). Their marks are included solely to identify the connected providers. This provenance notice does not override any provider's trademark rights, brand guidelines, service terms, or permission requirements.

## Original DoWidget application and control marks

- Created for DoWidget on **2026-10-12**. These are original geometric artwork, not downloaded marks or adaptations of any provider's logo.
- Application source: `dowidget.svg`. A pale **D** and cyan remaining-usage arc sit on a dark blue rounded tile; the surrounding corners are transparent.
- Application runtime asset: `dowidget.png`, **256 × 256 pixels**, rendered from the SVG with PySide6's Qt SVG renderer.
- Windows executable icon: `dowidget.ico`, containing independently rendered **16 × 16**, **32 × 32**, **48 × 48**, and **256 × 256** 32-bit RGBA PNG frames in a Windows ICO container. This is the application icon supplied to PyInstaller, not a provider mark.
- Control sources: `refresh.svg` (circular reload arrow), `settings.svg` (eight-tooth cog), `expand.svg` (outward diagonal arrows for Detailed mode), `minimize.svg` (minus), and `close.svg` (cross).
- Matching control PNGs are **96 × 96 pixels**, rendered from those SVGs for **24 × 24** logical-pixel display. Their outlined foreground is **`#e8eef8`**, with a transparent background.
- The editable SVG sources and generated PNG/ICO files are distributed with DoWidget. No third-party artwork, fonts, or additional runtime rendering dependency is used for these marks.
