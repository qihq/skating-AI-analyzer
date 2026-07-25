# Annual PDF Fonts

Annual PDF exports require a Chinese-capable TrueType or OpenType font. The
all-in-one image installs Debian's `fonts-wqy-zenhei` package and uses:

```text
/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc
/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc
```

WenQuanYi Zen Hei uses TrueType outlines that ReportLab can embed. The current
all-in-one image contains Debian package `fonts-wqy-zenhei` version `0.9.45-8`,
distributed under GPL-2.0-or-later with the font embedding exception.

```text
File: /usr/share/fonts/truetype/wqy/wqy-zenhei.ttc
SHA256: 79c18ebe7b811951e8311bad7103ebeae8c337ed9988ea69e8a78a66cfe029b9
Source: https://packages.debian.org/bookworm/fonts-wqy-zenhei
```

The same TTC supplies both the regular and bold aliases. Fonts are installed
at image build time and are never downloaded by the running application.

Configure deployment with these paths:

```text
ANNUAL_PDF_FONT_PATH=/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc
ANNUAL_PDF_FONT_BOLD_PATH=/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc
```

For Docker Compose and Synology deployments, mount the host `fonts/` directory
read-only at `/app/assets/fonts`, then place licensed files with these names in
that directory. Do not commit font binaries unless their source, version,
license, and SHA256 are recorded here.

When bundling a font, record its upstream source, version, license, and SHA256
in this file before release. The development fallback is a local system font
only and must not be relied on for deployment.
