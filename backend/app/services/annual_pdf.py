from __future__ import annotations

import hashlib
import io
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


RENDERER_VERSION = "annual_pdf.v1"
MAX_REPRESENTATIVE_FRAME_PIXELS = (1600, 1200)
MAX_REPRESENTATIVE_FRAME_RENDER_POINTS = (145, 105)
_SAFE_FRAME_TOKEN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class AnnualPdfError(RuntimeError):
    """Base exception for annual PDF export failures."""


class AnnualPdfFontError(AnnualPdfError):
    """The configured Chinese-capable font files are unavailable."""


@dataclass(frozen=True)
class AnnualPdfResult:
    output_path: Path
    file_sha256: str
    page_count: int
    extracted_text: str
    renderer_version: str = RENDERER_VERSION


def configured_font_paths() -> dict[str, str]:
    """Return deploy-configured font paths without downloading a font at runtime."""
    return {
        "regular": os.getenv("ANNUAL_PDF_FONT_PATH", "").strip(),
        "bold": os.getenv("ANNUAL_PDF_FONT_BOLD_PATH", "").strip(),
    }


def _require_pdf_dependencies():
    try:
        import pypdf  # noqa: F401
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        from PIL import Image as PilImage
        from PIL import ImageOps
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        missing = getattr(exc, "name", None) or "reportlab/pypdf"
        raise AnnualPdfError(f"年度 PDF 运行依赖缺失：{missing}。请重新安装完整后端依赖后再试。") from exc
    return {
        "colors": colors,
        "TA_CENTER": TA_CENTER,
        "TA_LEFT": TA_LEFT,
        "A4": A4,
        "ParagraphStyle": ParagraphStyle,
        "getSampleStyleSheet": getSampleStyleSheet,
        "mm": mm,
        "pdfmetrics": pdfmetrics,
        "TTFont": TTFont,
        "KeepTogether": KeepTogether,
        "Image": Image,
        "PilImage": PilImage,
        "ImageOps": ImageOps,
        "PageBreak": PageBreak,
        "Paragraph": Paragraph,
        "SimpleDocTemplate": SimpleDocTemplate,
        "Spacer": Spacer,
        "Table": Table,
        "TableStyle": TableStyle,
    }


def validate_font_paths(font_paths: Mapping[str, Path | str] | None = None) -> tuple[Path, Path]:
    """Validate configured font files without importing the PDF renderer."""
    font_paths = font_paths or configured_font_paths()
    regular_value = str(font_paths.get("regular", "")).strip()
    bold_value = str(font_paths.get("bold", "")).strip()
    regular = Path(regular_value) if regular_value else None
    bold = Path(bold_value) if bold_value else None
    missing = [label for label, path in (("常规字体", regular), ("粗体字体", bold)) if path is None or not path.is_file()]
    if missing:
        raise AnnualPdfFontError(
            "年度 PDF 中文字体不可用：" + "、".join(missing) + "。请检查一体化镜像中的字体安装和 ANNUAL_PDF_FONT_PATH 配置。"
        )
    assert regular is not None and bold is not None
    return regular, bold


_validate_font_paths = validate_font_paths


def _safe_text(value: Any) -> str:
    return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")


def _page_footer(canvas, document) -> None:
    canvas.saveState()
    canvas.setFont("AnnualSans", 8)
    canvas.setFillColorRGB(0.4, 0.45, 0.52)
    canvas.drawCentredString(document.pagesize[0] / 2, 10 * 2.83465, f"IceBuddy Annual - 第 {document.page} 页")
    canvas.restoreState()


def _representative_frame_path(frame: dict[str, Any], frames_root: Path) -> Path | None:
    """Derive a path from identifiers; snapshots never carry filesystem paths."""
    analysis_id = str(frame.get("analysis_id") or "")
    frame_id = str(frame.get("frame_id") or "")
    if not _SAFE_FRAME_TOKEN.fullmatch(analysis_id) or not _SAFE_FRAME_TOKEN.fullmatch(frame_id):
        return None
    root = frames_root.resolve()
    for directory in ("frames", "semantic_frames"):
        candidate = (root / analysis_id / directory / f"{frame_id}.jpg").resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        if candidate.is_file():
            return candidate
    return None


def _representative_frame_flowable(frame: dict[str, Any], frames_root: Path, lib: dict[str, Any], body_style, muted_style):
    phase = _safe_text(frame.get("phase") or "key moment")
    path = _representative_frame_path(frame, frames_root)
    if path is None:
        return lib["Paragraph"](f"Representative frame unavailable: {phase}", muted_style)
    try:
        with lib["PilImage"].open(path) as image:
            normalized = lib["ImageOps"].exif_transpose(image).convert("RGB")
            normalized.thumbnail(MAX_REPRESENTATIVE_FRAME_PIXELS)
            width, height = normalized.size
            payload = io.BytesIO()
            normalized.save(payload, format="JPEG", quality=85, optimize=True)
        payload.seek(0)
        max_width, max_height = MAX_REPRESENTATIVE_FRAME_RENDER_POINTS
        scale = min(max_width / width, max_height / height, 1.0)
        return lib["KeepTogether"]([
            lib["Paragraph"](f"Representative frame: {phase}", body_style),
            lib["Image"](payload, width=width * scale, height=height * scale),
        ])
    except Exception:  # noqa: BLE001 - absent/corrupt media becomes a text panel
        return lib["Paragraph"](f"Representative frame unavailable: {phase}", muted_style)


def render_annual_pdf(
    snapshot: dict[str, Any],
    output_path: Path,
    font_paths: Mapping[str, Path] | None = None,
    *,
    frames_root: Path | None = None,
) -> AnnualPdfResult:
    """Render a stable annual snapshot atomically; only snapshot data reaches the PDF."""
    regular_path, bold_path = validate_font_paths(font_paths)
    lib = _require_pdf_dependencies()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame_root = Path(frames_root).resolve() if frames_root is not None else output_path.parent / "_missing_frames"

    pdfmetrics = lib["pdfmetrics"]
    pdfmetrics.registerFont(lib["TTFont"]("AnnualSans", str(regular_path)))
    pdfmetrics.registerFont(lib["TTFont"]("AnnualSansBold", str(bold_path)))
    styles = lib["getSampleStyleSheet"]()
    title_style = lib["ParagraphStyle"]("AnnualTitle", parent=styles["Title"], fontName="AnnualSansBold", fontSize=25, leading=34, alignment=lib["TA_CENTER"], textColor=lib["colors"].HexColor("#0f3b62"))
    heading_style = lib["ParagraphStyle"]("AnnualHeading", parent=styles["Heading1"], fontName="AnnualSansBold", fontSize=17, leading=24, textColor=lib["colors"].HexColor("#173f5f"), spaceAfter=10)
    chapter_style = lib["ParagraphStyle"]("AnnualChapter", parent=styles["Heading2"], fontName="AnnualSansBold", fontSize=15, leading=22, textColor=lib["colors"].HexColor("#173f5f"), spaceAfter=8)
    body_style = lib["ParagraphStyle"]("AnnualBody", parent=styles["BodyText"], fontName="AnnualSans", fontSize=10.5, leading=18, textColor=lib["colors"].HexColor("#27364a"), spaceAfter=8)
    muted_style = lib["ParagraphStyle"]("AnnualMuted", parent=body_style, textColor=lib["colors"].HexColor("#667085"), fontSize=9.5, leading=15)
    quote_style = lib["ParagraphStyle"]("AnnualQuote", parent=body_style, leftIndent=12, borderColor=lib["colors"].HexColor("#b9d8eb"), borderWidth=2, borderPadding=8, textColor=lib["colors"].HexColor("#285b77"))

    story = []
    year = int(snapshot.get("year") or 0)
    chapters = snapshot.get("chapters") if isinstance(snapshot.get("chapters"), list) else []
    milestones = snapshot.get("milestones") if isinstance(snapshot.get("milestones"), list) else []
    coverage = snapshot.get("coverage") if isinstance(snapshot.get("coverage"), dict) else {}

    story.extend([
        lib["Spacer"](1, 65 * lib["mm"]),
        lib["Paragraph"]("IceBuddy", muted_style),
        lib["Spacer"](1, 8 * lib["mm"]),
        lib["Paragraph"](f"{year} 年度成长合集", title_style),
        lib["Spacer"](1, 8 * lib["mm"]),
        lib["Paragraph"]("由已发布月度章节重新生成 - 每一页均保留事实来源与数据覆盖说明。", body_style),
        lib["PageBreak"](),
        lib["Paragraph"]("年度一览", heading_style),
    ])
    overview_rows = [
        ["已发布章节", str(coverage.get("published_chapter_count", len(chapters)))],
        ["文字章节", str(coverage.get("text_only_chapter_count", 0))],
        ["入选里程碑", str(coverage.get("selected_milestone_count", len(milestones)))],
    ]
    table = lib["Table"](overview_rows, colWidths=[70 * lib["mm"], 80 * lib["mm"]])
    table.setStyle(lib["TableStyle"]([
        ("FONTNAME", (0, 0), (-1, -1), "AnnualSans"),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("LEADING", (0, 0), (-1, -1), 18),
        ("BACKGROUND", (0, 0), (0, -1), lib["colors"].HexColor("#eef7fb")),
        ("GRID", (0, 0), (-1, -1), 0.4, lib["colors"].HexColor("#c8d9e5")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.extend([table, lib["Spacer"](1, 10 * lib["mm"]), lib["Paragraph"]("仅展示已发布的月度章节；PDF 是可从原始快照重新生成的派生文件。", muted_style)])

    for chapter in chapters:
        if not isinstance(chapter, dict):
            continue
        story.extend([lib["PageBreak"](), lib["Paragraph"](f"{_safe_text(chapter.get('year_month'))} 月度章节", chapter_style)])
        chapter_coverage = chapter.get("coverage") if isinstance(chapter.get("coverage"), dict) else {}
        story.append(lib["Paragraph"](
            f"覆盖：{int(chapter_coverage.get('sessions') or 0)} 次训练，{int(chapter_coverage.get('completed_analyses') or 0)} 次完成分析，{int(chapter_coverage.get('comparable_metrics') or 0)} 项可比指标。",
            muted_style,
        ))
        story.append(lib["Paragraph"](_safe_text(chapter.get("final_text")), body_style))
        quotes = chapter.get("quote_facts") if isinstance(chapter.get("quote_facts"), list) else []
        for quote in quotes:
            if isinstance(quote, dict) and quote.get("text"):
                speaker = {"skater": "孩子", "parent": "家长", "coach": "教练"}.get(str(quote.get("speaker") or ""), "记录")
                story.append(lib["Paragraph"](f"{speaker}的话：{_safe_text(quote.get('text'))}", quote_style))
        frames = chapter.get("representative_frames") if isinstance(chapter.get("representative_frames"), list) else []
        for frame in frames:
            if isinstance(frame, dict):
                story.append(_representative_frame_flowable(frame, frame_root, lib, body_style, muted_style))
        if chapter.get("media_mode") == "text_only":
            story.append(lib["Paragraph"]("本章节没有可用于导出的代表图片，以下内容为文字版记录。", muted_style))

    story.extend([lib["PageBreak"](), lib["Paragraph"]("里程碑时间线", heading_style)])
    if milestones:
        for milestone in milestones:
            if not isinstance(milestone, dict):
                continue
            date = _safe_text(milestone.get("occurred_at"))[:10] or "日期未记录"
            verification = {"parent_confirmed": "家长确认", "coach_confirmed": "教练确认", "system_detected": "系统记录"}.get(str(milestone.get("verification") or ""), "来源未标注")
            note = _safe_text(milestone.get("note"))
            story.append(lib["Paragraph"](f"{date} - <b>{_safe_text(milestone.get('title'))}</b>（{verification}）{('<br/>' + note) if note else ''}", body_style))
    else:
        story.append(lib["Paragraph"]("本年度没有入选的里程碑记录。", muted_style))

    story.extend([lib["PageBreak"](), lib["Paragraph"]("指标定义与来源", heading_style)])
    definitions = snapshot.get("metric_definitions") if isinstance(snapshot.get("metric_definitions"), dict) else {}
    for name, definition in sorted(definitions.items()):
        story.append(lib["Paragraph"](f"<b>{_safe_text(name)}</b>：{_safe_text(definition)}", body_style))
    story.append(lib["Spacer"](1, 5 * lib["mm"]))
    story.append(lib["Paragraph"]("来源：本合集只引用选定章节中已冻结的事实快照、家长确认或教练确认的里程碑来源。未经支持的成功率、等级或健康结论不会生成。", muted_style))

    fd, temporary_name = tempfile.mkstemp(prefix=f".{output_path.stem}-", suffix=".pdf", dir=output_path.parent)
    os.close(fd)
    temporary_path = Path(temporary_name)
    try:
        document = lib["SimpleDocTemplate"](
            str(temporary_path), pagesize=lib["A4"], leftMargin=18 * lib["mm"], rightMargin=18 * lib["mm"], topMargin=16 * lib["mm"], bottomMargin=16 * lib["mm"], title=f"IceBuddy {year} Annual",
        )
        document.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
        raw = temporary_path.read_bytes()
        from pypdf import PdfReader
        reader = PdfReader(str(temporary_path))
        extracted_text = "\n".join(page.extract_text() or "" for page in reader.pages)
        result = AnnualPdfResult(output_path, hashlib.sha256(raw).hexdigest(), len(reader.pages), extracted_text)
        os.replace(temporary_path, output_path)
        return result
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
