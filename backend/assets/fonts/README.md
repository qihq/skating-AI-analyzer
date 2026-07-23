# Annual PDF Fonts

Annual PDF exports require a Chinese-capable TrueType or OpenType font. Fonts
are not downloaded at runtime.

Configure deployment with these paths:

```text
ANNUAL_PDF_FONT_PATH=/app/assets/fonts/NotoSansCJKsc-Regular.otf
ANNUAL_PDF_FONT_BOLD_PATH=/app/assets/fonts/NotoSansCJKsc-Bold.otf
```

For Docker Compose and Synology deployments, mount the host `fonts/` directory
read-only at `/app/assets/fonts`, then place licensed files with these names in
that directory. Do not commit font binaries unless their source, version,
license, and SHA256 are recorded here.

When bundling a font, record its upstream source, version, license, and SHA256
in this file before release. The development fallback is a local system font
only and must not be relied on for deployment.
