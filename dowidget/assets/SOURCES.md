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

## Display and attribution

Preserve each image's aspect ratio, colors, original padding, and any background. Place it within an uncluttered provider tile with additional clear space; the OpenAI image belongs on a neutral light tile, not a tinted or recolored treatment. Runtime downscaling for display is not a replacement or modification of these source PNG files.

DoWidget is an independent application and is not affiliated with, sponsored by, or endorsed by DeepSeek or OpenAI. Their marks are included solely to identify the connected providers. This provenance notice does not override either provider's trademark rights, brand guidelines, service terms, or permission requirements.

## Original DoWidget application and control marks

- Created for DoWidget on **2026-10-12**. These are original geometric artwork, not downloaded marks or adaptations of either provider's logo.
- Application source: `dowidget.svg`. A pale **D** and cyan remaining-usage arc sit on a dark blue rounded tile; the surrounding corners are transparent.
- Application runtime asset: `dowidget.png`, **256 × 256 pixels**, rendered from the SVG with PySide6's Qt SVG renderer.
- Windows executable icon: `dowidget.ico`, containing independently rendered **16 × 16**, **32 × 32**, **48 × 48**, and **256 × 256** 32-bit RGBA PNG frames in a Windows ICO container. This is the application icon supplied to PyInstaller, not a provider mark.
- Control sources: `refresh.svg` (circular reload arrow), `settings.svg` (eight-tooth cog), `expand.svg` (outward diagonal arrows for Detailed mode), `minimize.svg` (minus), and `close.svg` (cross).
- Matching control PNGs are **96 × 96 pixels**, rendered from those SVGs for **24 × 24** logical-pixel display. Their outlined foreground is **`#e8eef8`**, with a transparent background.
- The editable SVG sources and generated PNG/ICO files are distributed with DoWidget. No third-party artwork, fonts, or additional runtime rendering dependency is used for these marks.
