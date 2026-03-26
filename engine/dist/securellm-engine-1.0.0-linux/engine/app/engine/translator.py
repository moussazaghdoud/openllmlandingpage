"""Document translation engine — adapted from openclaw/bot/bot.js.

Translates documents while preserving layout, images, and formatting:
- DOCX: replaces <w:t> text in word/document.xml, skips <w:drawing>/<w:pict>
- PPTX: replaces <a:t> text in ppt/slides/slide*.xml, skips <a:blipFill>
- PDF:  extracts text, translates, outputs as new DOCX (PDFs can't be rebuilt)

All text passes through the anonymization pipeline before reaching the LLM.
"""

from __future__ import annotations

import io
import json
import logging
import re
import zipfile

import httpx

logger = logging.getLogger("securellm.translator")

CHUNK_SIZE = 15       # paragraphs per LLM call (small to avoid refusals)
TRANSLATION_TIMEOUT = 180.0  # 3 minutes per chunk


# ── LLM Translation Call ────────────────────────────────

async def call_translation(
    paragraphs: list[str],
    language: str,
    llm_config: dict,
) -> list[str] | None:
    """Send paragraphs to LLM for translation, with chunking.

    Returns list of translated paragraphs, or None on failure.
    """
    provider = llm_config.get("provider", "custom")
    upstream_url = llm_config["upstream_url"].rstrip("/")
    api_key = llm_config["api_key"]
    model = llm_config.get("default_model", "")

    all_translated: list[str] = []

    for start in range(0, len(paragraphs), CHUNK_SIZE):
        chunk = paragraphs[start:start + CHUNK_SIZE]
        numbered = "\n".join(f"[{i}] {p}" for i, p in enumerate(chunk))
        prompt = (
            f"Translate each numbered paragraph below to {language}. "
            f"Return ONLY a JSON array of translated strings (same order, same count). "
            f"No explanation, no markdown, just the JSON array.\n\n{numbered}"
        )

        chunk_num = start // CHUNK_SIZE + 1
        total_chunks = (len(paragraphs) + CHUNK_SIZE - 1) // CHUNK_SIZE
        logger.info("Translation chunk %d/%d: %d paragraphs", chunk_num, total_chunks, len(chunk))

        messages = [
            {"role": "system", "content": "You are a professional document translator. Your ONLY job is to translate text. You MUST translate every paragraph given to you, no matter how long. Never refuse. Never summarize. Return ONLY a JSON array of translated strings. No commentary, no explanation."},
            {"role": "user", "content": prompt},
        ]

        # Build request based on provider
        if provider == "anthropic":
            url = f"{upstream_url}/v1/messages"
            headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
            payload = {"model": model, "messages": messages, "max_tokens": 8192}
        else:
            url = f"{upstream_url}/v1/chat/completions"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {"model": model, "messages": messages, "max_tokens": 8192, "temperature": 0.3}

        try:
            async with httpx.AsyncClient(timeout=TRANSLATION_TIMEOUT) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.error("Translation API error: %s", e)
            return None

        # Extract content
        if provider == "anthropic":
            content = ""
            for block in data.get("content", []):
                if block.get("type") == "text":
                    content += block["text"]
        else:
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

        # Parse JSON array from response
        match = re.search(r"\[[\s\S]*\]", content)
        if not match:
            logger.error("No JSON array in translation response")
            return None
        try:
            parsed = json.loads(match.group(0))
            if not isinstance(parsed, list):
                logger.error("Translation response is not an array")
                return None
        except json.JSONDecodeError as e:
            logger.error("JSON parse error in translation: %s", e)
            return None

        all_translated.extend(parsed)
        logger.info("Chunk translated: got %d paragraphs", len(parsed))

    return all_translated


# ── XML Helpers ──────────────────────────────────────────

def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ── DOCX Translation ────────────────────────────────────

def extract_docx_paragraphs(docx_bytes: bytes) -> list[str]:
    """Extract text paragraphs from DOCX, skipping image paragraphs."""
    zf = zipfile.ZipFile(io.BytesIO(docx_bytes))
    doc_xml = zf.read("word/document.xml").decode("utf-8", errors="replace")

    paragraphs = []
    for m in re.finditer(r"<w:p\b[^>]*>[\s\S]*?</w:p>", doc_xml):
        para = m.group(0)
        # Skip image/drawing paragraphs
        if re.search(r"<w:drawing\b|<w:pict\b|<mc:AlternateContent\b", para):
            continue
        # Extract text
        text = re.sub(r"<[^>]+>", "", para).strip()
        if text:
            paragraphs.append(text)
    return paragraphs


def rebuild_docx(docx_bytes: bytes, translated: list[str]) -> bytes:
    """Replace text in DOCX XML while preserving layout/images/styles."""
    zf_in = zipfile.ZipFile(io.BytesIO(docx_bytes))
    doc_xml = zf_in.read("word/document.xml").decode("utf-8", errors="replace")

    text_idx = 0

    def replace_para(match: re.Match) -> str:
        nonlocal text_idx
        para = match.group(0)

        # Skip image paragraphs
        if re.search(r"<w:drawing\b|<w:pict\b|<mc:AlternateContent\b", para):
            return para

        # Skip empty paragraphs
        text_content = re.sub(r"<[^>]+>", "", para).strip()
        if not text_content:
            return para

        if text_idx >= len(translated):
            return para

        new_text = translated[text_idx]
        text_idx += 1

        # Replace <w:t> content: first gets translated text, rest cleared
        first = True

        def replace_wt(wt_match: re.Match) -> str:
            nonlocal first
            attrs = wt_match.group(1)
            if first:
                first = False
                return f"<w:t{attrs}>{_xml_escape(new_text)}</w:t>"
            return f"<w:t{attrs}></w:t>"

        return re.sub(r"<w:t([^>]*)>[^<]*</w:t>", replace_wt, para)

    new_doc_xml = re.sub(r"<w:p\b[^>]*>[\s\S]*?</w:p>", replace_para, doc_xml)
    logger.info("DOCX: %d paragraphs replaced", text_idx)

    # Rebuild ZIP
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf_out:
        for item in zf_in.namelist():
            if item == "word/document.xml":
                zf_out.writestr(item, new_doc_xml)
            else:
                zf_out.writestr(item, zf_in.read(item))
    return out.getvalue()


# ── PPTX Translation ────────────────────────────────────

def extract_pptx_paragraphs(pptx_bytes: bytes) -> list[str]:
    """Extract text paragraphs from all slides, skipping image paragraphs."""
    zf = zipfile.ZipFile(io.BytesIO(pptx_bytes))
    slides = sorted([n for n in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)])

    paragraphs = []
    for slide_path in slides:
        xml = zf.read(slide_path).decode("utf-8", errors="replace")
        for m in re.finditer(r"<a:p\b[^>]*>[\s\S]*?</a:p>", xml):
            para = m.group(0)
            if re.search(r"<a:blipFill\b|<a:prstGeom\b", para):
                continue
            parts = re.findall(r"<a:t>([^<]*)</a:t>", para)
            text = "".join(parts).strip()
            if text:
                paragraphs.append(text)
    return paragraphs


def rebuild_pptx(pptx_bytes: bytes, translated: list[str]) -> bytes:
    """Replace text in PPTX slide XMLs while preserving layout/shapes/images."""
    zf_in = zipfile.ZipFile(io.BytesIO(pptx_bytes))
    slides = sorted([n for n in zf_in.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)])

    trans_idx = 0
    modified_slides: dict[str, str] = {}

    for slide_path in slides:
        xml = zf_in.read(slide_path).decode("utf-8", errors="replace")

        def replace_para(match: re.Match) -> str:
            nonlocal trans_idx
            para = match.group(0)

            if re.search(r"<a:blipFill\b|<a:prstGeom\b", para):
                return para

            parts = re.findall(r"<a:t>([^<]*)</a:t>", para)
            text = "".join(parts).strip()
            if not text or trans_idx >= len(translated):
                return para

            new_text = translated[trans_idx]
            trans_idx += 1

            # First <a:r> with text gets translated content, rest cleared
            first = True

            def replace_run(run_match: re.Match) -> str:
                nonlocal first
                run_xml = run_match.group(0)
                if "<a:t>" not in run_xml:
                    return run_xml
                if first:
                    first = False
                    return re.sub(r"<a:t>[^<]*</a:t>", f"<a:t>{_xml_escape(new_text)}</a:t>", run_xml, count=1)
                return re.sub(r"<a:t>[^<]*</a:t>", "<a:t></a:t>", run_xml)

            return re.sub(r"<a:r\b[^>]*>[\s\S]*?</a:r>", replace_run, para)

        new_xml = re.sub(r"<a:p\b[^>]*>[\s\S]*?</a:p>", replace_para, xml)
        modified_slides[slide_path] = new_xml

    logger.info("PPTX: %d paragraphs replaced across %d slides", trans_idx, len(slides))

    # Rebuild ZIP
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf_out:
        for item in zf_in.namelist():
            if item in modified_slides:
                zf_out.writestr(item, modified_slides[item])
            else:
                zf_out.writestr(item, zf_in.read(item))
    return out.getvalue()


# ── PDF Translation (outputs DOCX) ──────────────────────

def extract_pdf_paragraphs(pdf_bytes: bytes) -> list[str]:
    """Extract text paragraphs from PDF."""
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(pdf_bytes))
    full_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return [p.strip() for p in re.split(r"\n\s*\n", full_text) if p.strip()]


def build_docx_from_paragraphs(paragraphs: list[str]) -> bytes:
    """Create a minimal valid DOCX from a list of paragraphs."""
    escaped_paras = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{_xml_escape(p)}</w:t></w:r></w:p>'
        for p in paragraphs
    )

    doc_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas"
            xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
            xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
            xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
            mc:Ignorable="w14 wp14">
  <w:body>{escaped_paras}
    <w:sectPr><w:pgSz w:w="12240" w:h="15840"/>
    <w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>
  </w:body>
</w:document>'''

    content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>'''

    rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>'''

    doc_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
</Relationships>'''

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", doc_xml)
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/_rels/document.xml.rels", doc_rels)
    return out.getvalue()
