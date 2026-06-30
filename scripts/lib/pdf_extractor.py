"""
Extract structured text and images from a Driver's Manual PDF using pymupdf.

Output structure per manual year:
  chapters → sections → { title, page, body_text, images[] }
"""

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # pymupdf
from PIL import Image
import io


# Matches English "CHAPTER 1" and Spanish "CAPÍTULO 1" — including the OCR/typo
# variant "CAPÍTILO" found in the 2023 Spanish manual.
CHAPTER_RE = re.compile(r"^(CHAPTER|CAP[IÍ]T[UI]LO)\s+\d+", re.IGNORECASE)
# Some editions (e.g. 2002/2003) typeset the chapter label with a discretionary
# soft hyphen inside the word, e.g. "CHAP\xadTER 2", which breaks a naive match.
# Fold these invisible format characters out before testing CHAPTER_RE.
_INVISIBLE_RE = re.compile("[­​‌‍﻿]")


def _norm_heading(text: str) -> str:
    """Strip soft-hyphens / zero-width chars so chapter labels match reliably."""
    return _INVISIBLE_RE.sub("", text)


# Real chapter labels are display-sized (English >= 47.9pt, Spanish 47.9pt). The
# size floor rejects inline body references like Spanish "capítulo 525 de las
# Leyes de 2008)" (~13pt) that the broadened regex would otherwise match.
CHAPTER_LABEL_MIN_SIZE = 30.0
# Plausible chapter-number range — a second guard against stray matches.
MAX_CHAPTER_NUM = 50
# Minimum SOURCE pixel dimensions (from xref metadata) to keep real content images
MIN_SRC_PX = 100
# Maximum ON-PAGE aspect ratio to exclude tall/narrow column-border decorators
# Column borders render at ~70x560 pts (aspect ~8); real content images are <= 6
MAX_ONPAGE_ASPECT = 7.0


@dataclass
class ExtractedImage:
    src_path: str      # relative to web/
    page: int
    bbox: tuple        # (x0, y0, x1, y1)


@dataclass
class ExtractedSection:
    chapter_num: int
    chapter_title: str
    section_key: str
    title: str
    page: int
    body_text: str
    images: list[ExtractedImage] = field(default_factory=list)


def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[\s_-]+", "-", text)


def _is_chapter_heading(span: dict, block_text: str) -> bool:
    return bool(CHAPTER_RE.match(block_text.strip()))


def _is_section_heading(span: dict, line_text: str, page_width: float) -> bool:
    """Heuristic: bold, short, non-sentence text that spans only part of the width."""
    text = line_text.strip()
    if len(text) < 3 or len(text) > 80:
        return False
    font_name = span.get("font", "")
    is_bold = "Bold" in font_name or "bold" in font_name or "Heavy" in font_name
    if not is_bold:
        return False
    # Exclude obvious body-text lines (end with period mid-word, contain lowercase start)
    if text.endswith(".") and len(text.split()) > 6:
        return False
    return True


def _clean_text(text: str) -> str:
    # Normalize whitespace; collapse multiple spaces/newlines
    text = re.sub(r"\s+", " ", text)
    # Normalize common bullet variants
    text = re.sub(r"^[•◦▪▸►‣●]\s*", "• ", text, flags=re.MULTILINE)
    return text.strip()


def _save_image(doc: fitz.Document, xref: int, dest_path: Path) -> bool:
    """Extract image by xref and save as PNG. Returns True on success."""
    try:
        img_info = doc.extract_image(xref)
        img_bytes = img_info["image"]
        img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
        # Re-save as PNG with white background (handles CMYK, palette, etc.)
        background = Image.new("RGBA", img.size, (255, 255, 255, 255))
        background.paste(img, mask=img if img.mode == "RGBA" else None)
        background.convert("RGB").save(dest_path, "PNG")
        return True
    except Exception:
        # Fallback: render the image region from the page (handled by caller)
        return False


def _save_image_from_pixmap(page: fitz.Page, bbox: fitz.Rect, dest_path: Path) -> None:
    clip = fitz.Rect(bbox)
    pix = page.get_pixmap(clip=clip, dpi=150)
    pix.save(str(dest_path))


# Minimum font size for the display title on a chapter-start page when there is no
# "CHAPTER N" label to anchor on (the 2004 edition titles render at ~30pt).
DISPLAY_TITLE_MIN_SIZE = 26.0


def _detect_chapters_by_title(doc: fitz.Document) -> list[tuple[int, int, str]]:
    """
    Locate chapter starts in editions that omit the "CHAPTER N" label. A chapter
    start is a page that carries large display-size title text (e.g. 30pt bold)
    standing on its own — body pages have nothing that large. Titles are joined in
    reading order and chapters are numbered sequentially.

    Returns [(chapter_num, page_idx, title), ...].
    """
    chapter_pages: list[tuple[int, int, str]] = []
    for page_idx in range(len(doc)):
        blocks = doc[page_idx].get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        title_parts: list[str] = []
        for block in blocks:
            if block["type"] != 0:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    span_text = span["text"].strip()
                    if span_text and span["size"] >= DISPLAY_TITLE_MIN_SIZE:
                        title_parts.append(span_text)
        title = _clean_text(" ".join(title_parts))
        if len(title) >= 4:
            chapter_pages.append((len(chapter_pages) + 1, page_idx, title))
    return chapter_pages


def extract_manual(
    pdf_path: Path, images_dir: Path, year: int, url_prefix: str = "images"
) -> list[ExtractedSection]:
    """
    Parse a single Driver's Manual PDF.
    Saves images to images_dir/p{NNN}_img{N}.png.
    Returns a flat list of ExtractedSection objects.

    `url_prefix` is the web-relative folder the saved images live under
    (`{url_prefix}/{year}/...`). Defaults to "images" (the English build); the
    Spanish build passes "images_spanish" so the two don't collide on shared years.
    """
    images_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf_path))

    # ── Phase 1: Find chapter boundaries ──────────────────────────────────────
    # On a chapter-start page the layout is:
    #   "CHAPTER N"            (very large, ~48pt)
    #   "Obtaining" "Your License"  (large display title, ~36pt, in reading order)
    #   body text             (~12pt)
    # We capture the descriptive title from the large display spans that follow the
    # "CHAPTER N" label, so chapter_title reads e.g. "Obtaining Your License".
    chapter_pages: list[tuple[int, int, str]] = []  # (chapter_num, page_idx, title)
    for page_idx in range(len(doc)):
        page = doc[page_idx]
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]

        # Pass 1: locate the chapter label (and its font size) anywhere on the page.
        chapter_num: int | None = None
        chapter_label_size = 0.0
        for block in blocks:
            if block["type"] != 0:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    span_text = _norm_heading(span["text"].strip())
                    if span_text and CHAPTER_RE.match(span_text) and span["size"] >= CHAPTER_LABEL_MIN_SIZE:
                        m = re.search(r"\d+", span_text)
                        num = int(m.group()) if m else len(chapter_pages) + 1
                        if num > MAX_CHAPTER_NUM:
                            continue
                        chapter_num = num
                        chapter_label_size = span["size"]

        # Pass 2: on a chapter-start page, collect the display-size title words. This
        # is order-independent — in some editions (e.g. the Spanish manual) the title
        # appears BEFORE the "CHAPTER N" label in block order, so a single ordered
        # pass would miss it and fall back to a generic "Chapter N".
        title_parts: list[str] = []
        if chapter_num is not None:
            for block in blocks:
                if block["type"] != 0:
                    continue
                for line in block["lines"]:
                    for span in line["spans"]:
                        span_text = span["text"].strip()
                        if (
                            span_text
                            and 24 <= span["size"] < chapter_label_size
                            and not CHAPTER_RE.match(_norm_heading(span_text))
                        ):
                            title_parts.append(span_text)

        if chapter_num is not None:
            title = _clean_text(" ".join(title_parts)) if title_parts else f"Chapter {chapter_num}"
            chapter_pages.append((chapter_num, page_idx, title))

    # Fallback for editions that omit the "CHAPTER N" label entirely (e.g. 2004):
    # the only thing marking a chapter start is the large display title on its own
    # page. Detect those pages by their display-size text and number them in order.
    if not chapter_pages:
        chapter_pages = _detect_chapters_by_title(doc)
        if chapter_pages:
            print(f"  No 'CHAPTER N' labels in {pdf_path.name}; "
                  f"detected {len(chapter_pages)} chapters by display title.")

    if not chapter_pages:
        print(f"  WARNING: No chapter headings found in {pdf_path.name}. Treating whole doc as one chapter.")
        chapter_pages = [(1, 0, "Chapter 1")]

    # Build chapter page ranges
    chapters_info = []
    for i, (ch_num, start_pg, ch_title) in enumerate(chapter_pages):
        end_pg = chapter_pages[i + 1][1] - 1 if i + 1 < len(chapter_pages) else len(doc) - 1
        chapters_info.append((ch_num, start_pg, end_pg, ch_title))

    # ── Phase 2: Extract sections and images per chapter ──────────────────────
    all_sections: list[ExtractedSection] = []
    img_counter = [0]  # mutable for nested use

    for ch_num, ch_start, ch_end, ch_title in chapters_info:
        current_section_title: str | None = None
        current_section_page: int = ch_start
        current_text_parts: list[str] = []
        current_section_key: str | None = None
        section_key_seen: set[str] = set()

        def flush_section():
            if current_section_title and current_text_parts:
                body = _clean_text(" ".join(current_text_parts))
                if len(body) > 20:
                    key = current_section_key or _slugify(current_section_title)
                    # Deduplicate keys within chapter
                    base_key = key
                    suffix = 1
                    while key in section_key_seen:
                        key = f"{base_key}-{suffix}"
                        suffix += 1
                    section_key_seen.add(key)
                    all_sections.append(ExtractedSection(
                        chapter_num=ch_num,
                        chapter_title=ch_title,
                        section_key=key,
                        title=current_section_title,
                        page=current_section_page,
                        body_text=body,
                    ))

        for page_idx in range(ch_start, ch_end + 1):
            page = doc[page_idx]
            page_width = page.rect.width

            # Extract images on this page
            page_images: list[ExtractedImage] = []
            img_list = page.get_images(full=True)
            for img_info in img_list:
                xref = img_info[0]
                src_w_px = img_info[2]  # source pixel width
                src_h_px = img_info[3]  # source pixel height

                # Filter 1: exclude tiny source images (bullets, dots, small icons)
                if src_w_px < MIN_SRC_PX or src_h_px < MIN_SRC_PX:
                    continue

                # Get on-page placement rect
                try:
                    rects = page.get_image_rects(xref)
                except Exception:
                    rects = []

                if not rects:
                    # No placement info — still save, position at top of page
                    img_bbox = (0, 0, page.rect.width, page.rect.height / 4)
                else:
                    r = rects[0]
                    img_bbox = (r.x0, r.y0, r.x1, r.y1)

                # Filter 2: exclude tall narrow column-border decorators by on-page aspect ratio
                onpage_w = img_bbox[2] - img_bbox[0]
                onpage_h = img_bbox[3] - img_bbox[1]
                if onpage_w <= 0 or onpage_h <= 0:
                    continue
                onpage_aspect = max(onpage_w, onpage_h) / min(onpage_w, onpage_h)
                if onpage_aspect > MAX_ONPAGE_ASPECT:
                    continue

                filename = f"p{page_idx:03d}_img{img_counter[0]:03d}.png"
                img_counter[0] += 1
                dest = images_dir / filename
                src_path = f"{url_prefix}/{year}/{filename}"

                saved = _save_image(doc, xref, dest)
                if not saved:
                    _save_image_from_pixmap(page, img_bbox, dest)

                page_images.append(ExtractedImage(src_path=src_path, page=page_idx, bbox=img_bbox))

            # Extract text blocks
            blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
            for block in blocks:
                if block["type"] != 0:
                    continue
                for line in block["lines"]:
                    line_text = "".join(s["text"] for s in line["spans"]).strip()
                    if not line_text:
                        continue

                    # Skip chapter headings (display-sized only — an inline body
                    # reference like "capítulo 525 de las Leyes" must not be dropped)
                    if CHAPTER_RE.match(_norm_heading(line_text)) and any(
                        s["size"] >= CHAPTER_LABEL_MIN_SIZE for s in line["spans"]
                    ):
                        continue

                    # Skip large display title words on chapter-start pages
                    if line["spans"] and all(s["size"] >= 24 for s in line["spans"]):
                        continue

                    # Check if this line is a section heading
                    first_span = line["spans"][0] if line["spans"] else {}
                    if _is_section_heading(first_span, line_text, page_width):
                        flush_section()
                        current_section_title = line_text
                        current_section_page = page_idx
                        current_section_key = _slugify(line_text)
                        current_text_parts = []
                    else:
                        if current_section_title is None:
                            # Text before first section heading — attach to chapter intro
                            current_section_title = ch_title
                            current_section_page = page_idx
                            current_section_key = _slugify(ch_title + "-intro")
                        current_text_parts.append(line_text)

            # Attach page images to the most recent section
            if page_images and all_sections:
                all_sections[-1].images.extend(page_images)
            elif page_images and current_section_title:
                # Images found but section not flushed yet — store temporarily
                # They'll be attached when the section is flushed
                pass

        flush_section()

    doc.close()

    total_sections = len(all_sections)
    total_images = sum(len(s.images) for s in all_sections)
    print(f"  {pdf_path.name}: {total_sections} sections, {total_images} images extracted")
    if total_sections < 15:
        print(f"  WARNING: Low section count ({total_sections}). Heading detection may need tuning.")

    return all_sections
