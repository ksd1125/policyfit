"""기업마당 수집 원문 → 마크다운 변환 파이프라인

대상:
  - raw/html/{runId}/*.html → 상세페이지 파싱
  - raw/files/{runId}/{noticeId}/* → 첨부/출력파일 변환
    - .pdf → PyMuPDF 텍스트 추출
    - .hwp → olefile PrvText 스트림 추출
    - .hwpx → ZIP 내부 XML 텍스트 추출
    - .docx → ZIP 내부 XML 텍스트 추출
    - 기타 → UNSUPPORTED 기록

출력: raw/markdown/{runId}/{noticeId}/
"""

import json
import os
import re
import sys
import zlib
import zipfile
from pathlib import Path
from collections import Counter

from bs4 import BeautifulSoup
import fitz  # PyMuPDF
import olefile


def find_latest_run_id(raw_dir):
    api_dir = raw_dir / "api"
    if not api_dir.exists():
        return None
    runs = sorted(
        [d.name for d in api_dir.iterdir() if d.is_dir() and re.match(r"\d{8}-\d{6}", d.name)],
        reverse=True,
    )
    return runs[0] if runs else None


# ── HTML 상세페이지 → MD ──

def convert_detail_html(html_path):
    text = html_path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(text, "html.parser")

    view_cont = soup.find("div", class_="view_cont")
    if not view_cont:
        return None, "NO_VIEW_CONT"

    lines = []

    title_meta = soup.find("meta", attrs={"name": "title"})
    if title_meta and title_meta.get("content"):
        lines.append(f"# {title_meta['content'].strip()}\n")

    for li in view_cont.find_all("li"):
        s_title = li.find("span", class_="s_title")
        txt_div = li.find("div", class_="txt")
        if s_title and txt_div:
            label = s_title.get_text(strip=True)
            body = txt_div.get_text("\n", strip=True)
            lines.append(f"## {label}\n\n{body}\n")

    notice_div = view_cont.find("div", style=re.compile("text-align.*center"))
    if notice_div:
        lines.append(f"\n---\n{notice_div.get_text(strip=True)}\n")

    if not lines:
        return None, "EMPTY_CONTENT"

    return "\n".join(lines), None


# ── PDF → 텍스트 ──

# PyMuPDF stderr 경고("MuPDF error: syntax error...")는 텍스트 추출에 영향 없으니 억제
try:
    fitz.TOOLS.mupdf_display_errors(False)
except Exception:
    pass


def convert_pdf(pdf_path):
    try:
        doc = fitz.open(str(pdf_path))
        pages = []
        for page in doc:
            pages.append(page.get_text())
        doc.close()
        text = "\n\n---\n\n".join(pages).strip()
        if not text:
            return None, "EMPTY_PDF"
        return text, None
    except Exception as e:
        return None, f"PDF_ERROR: {e}"


# ── HWP → 텍스트 (PrvText 스트림 우선, BodyText 폴백) ──

def extract_hwp_bodytext(ole):
    sections = sorted([s for s in ole.listdir() if s[0] == "BodyText"])
    text_parts = []
    for section_path in sections:
        stream_name = "/".join(section_path)
        data = ole.openstream(stream_name).read()
        try:
            data = zlib.decompress(data, -15)
        except zlib.error:
            pass
        chars = []
        i = 0
        while i < len(data) - 1:
            code = int.from_bytes(data[i : i + 2], "little")
            if 0x0020 <= code <= 0xFFFF and code not in range(0xD800, 0xE000):
                chars.append(chr(code))
            elif code == 0x000A or code == 0x000D:
                chars.append("\n")
            i += 2
        raw = "".join(chars)
        cleaned = re.sub(r"[^\w\s가-힣ㄱ-ㅎㅏ-ㅣ.,;:!?()（）\-–—·•※☞◎○●□■▶▷△▲◆◇★☆「」『』《》〈〉\[\]{}<>@#$%&*+=~^/\\|\"'` 　]", "", raw)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        if cleaned.strip():
            text_parts.append(cleaned.strip())
    return "\n\n".join(text_parts)


def convert_hwp(hwp_path):
    try:
        if not olefile.isOleFile(str(hwp_path)):
            return None, "NOT_OLE_FILE"

        ole = olefile.OleFileIO(str(hwp_path))

        if ole.exists("PrvText"):
            data = ole.openstream("PrvText").read()
            text = data.decode("utf-16-le", errors="replace").strip()
            text = text.replace("\x00", "")
            if len(text) > 50:
                ole.close()
                return text, None

        try:
            text = extract_hwp_bodytext(ole)
            if text and len(text) > 50:
                ole.close()
                return text, None
        except Exception:
            pass

        ole.close()
        return None, "EMPTY_HWP"
    except Exception as e:
        return None, f"HWP_ERROR: {e}"


# ── HWPX → 텍스트 (ZIP 내부 XML 파싱) ──

def convert_hwpx(hwpx_path):
    try:
        with zipfile.ZipFile(str(hwpx_path), "r") as zf:
            section_files = sorted([
                n for n in zf.namelist()
                if re.match(r"Contents/section\d+\.xml", n, re.IGNORECASE)
            ])
            if not section_files:
                section_files = [n for n in zf.namelist() if n.endswith(".xml") and "section" in n.lower()]

            text_parts = []
            for sf in section_files:
                xml_data = zf.read(sf)
                soup = BeautifulSoup(xml_data, "lxml-xml")
                for t_tag in soup.find_all("t"):
                    t = t_tag.get_text()
                    if t.strip():
                        text_parts.append(t)

            text = "\n".join(text_parts).strip()
            if not text:
                return None, "EMPTY_HWPX"
            return text, None
    except zipfile.BadZipFile:
        return None, "BAD_ZIP"
    except Exception as e:
        return None, f"HWPX_ERROR: {e}"


# ── DOCX → 텍스트 ──

def convert_docx(docx_path):
    try:
        with zipfile.ZipFile(str(docx_path), "r") as zf:
            if "word/document.xml" not in zf.namelist():
                return None, "NO_DOCUMENT_XML"
            xml_data = zf.read("word/document.xml")
            soup = BeautifulSoup(xml_data, "lxml-xml")
            paragraphs = []
            for p in soup.find_all("p"):
                text = p.get_text()
                if text.strip():
                    paragraphs.append(text.strip())
            text = "\n".join(paragraphs)
            if not text:
                return None, "EMPTY_DOCX"
            return text, None
    except Exception as e:
        return None, f"DOCX_ERROR: {e}"


# ── 메인 파이프라인 ──

def main():
    project_root = Path(os.getcwd())
    raw_dir = project_root / "raw"

    run_id = os.environ.get("E2E_RUN_ID") or find_latest_run_id(raw_dir)
    if not run_id:
        print("ERROR: No run found in raw/api/")
        sys.exit(1)

    html_dir = raw_dir / "html" / run_id
    files_dir = raw_dir / "files" / run_id
    md_dir = raw_dir / "markdown" / run_id

    print(f"Run ID: {run_id}")
    print(f"HTML dir: {html_dir}")
    print(f"Files dir: {files_dir}")
    print(f"Output dir: {md_dir}")

    results = {
        "runId": run_id,
        "html": {"total": 0, "success": 0, "failures": []},
        "attachments": {"total": 0, "success": 0, "failures": []},
        "by_ext": Counter(),
        "by_ext_success": Counter(),
    }

    # ── 1. HTML 상세페이지 변환 ──
    print("\n[1/2] Converting detail HTML pages...")
    html_files = sorted(html_dir.glob("*.html")) if html_dir.exists() else []
    results["html"]["total"] = len(html_files)

    for i, html_path in enumerate(html_files):
        notice_id = html_path.stem
        out_dir = md_dir / notice_id
        out_dir.mkdir(parents=True, exist_ok=True)

        text, error = convert_detail_html(html_path)
        if text:
            (out_dir / "detail.md").write_text(text, encoding="utf-8")
            results["html"]["success"] += 1
        else:
            results["html"]["failures"].append({"id": notice_id, "error": error})

        if (i + 1) % 100 == 0:
            print(f"  HTML: {i + 1}/{len(html_files)}")

    print(f"  HTML done: {results['html']['success']}/{results['html']['total']}")

    # ── 2. 첨부파일 변환 ──
    print("\n[2/2] Converting attachment files...")
    notice_dirs = sorted(files_dir.iterdir()) if files_dir.exists() else []
    converters = {
        ".pdf": convert_pdf,
        ".hwp": convert_hwp,
        ".hwpx": convert_hwpx,
        ".docx": convert_docx,
    }
    skip_exts = {".zip", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".xlsx", ".pptx", ".xls"}

    processed = 0
    for notice_dir in notice_dirs:
        if not notice_dir.is_dir():
            continue
        notice_id = notice_dir.name
        out_dir = md_dir / notice_id
        out_dir.mkdir(parents=True, exist_ok=True)

        for file_path in sorted(notice_dir.iterdir()):
            if not file_path.is_file():
                continue

            ext = file_path.suffix.lower()
            results["by_ext"][ext] += 1
            results["attachments"]["total"] += 1
            processed += 1

            if ext in skip_exts:
                code = "OCR_NEEDED" if ext in {".png", ".jpg", ".jpeg", ".gif", ".bmp"} else "UNSUPPORTED_FORMAT"
                results["attachments"]["failures"].append({
                    "id": f"{notice_id}/{file_path.name}",
                    "error": code,
                })
                continue

            converter = converters.get(ext)
            if not converter:
                results["attachments"]["failures"].append({
                    "id": f"{notice_id}/{file_path.name}",
                    "error": "UNKNOWN_FORMAT",
                })
                continue

            text, error = converter(file_path)
            out_name = file_path.stem + ".md"
            if text:
                (out_dir / out_name).write_text(text, encoding="utf-8")
                results["attachments"]["success"] += 1
                results["by_ext_success"][ext] += 1
            else:
                results["attachments"]["failures"].append({
                    "id": f"{notice_id}/{file_path.name}",
                    "error": error,
                })

            if processed % 200 == 0:
                print(f"  Attachments: {processed} processed")

    print(f"  Attachments done: {results['attachments']['success']}/{results['attachments']['total']}")

    # ── 요약 저장 ──
    summary = {
        "runId": run_id,
        "html_total": results["html"]["total"],
        "html_success": results["html"]["success"],
        "html_fail": len(results["html"]["failures"]),
        "attach_total": results["attachments"]["total"],
        "attach_success": results["attachments"]["success"],
        "attach_fail": len(results["attachments"]["failures"]),
        "by_extension": dict(results["by_ext"]),
        "by_extension_success": dict(results["by_ext_success"]),
        "failures": results["html"]["failures"] + results["attachments"]["failures"],
    }

    outputs_dir = project_root / "outputs"
    outputs_dir.mkdir(exist_ok=True)

    summary_path = outputs_dir / f"conversion-summary-{run_id}.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    md_summary = f"""# 원문 변환 요약

- runId: {run_id}
- 상세 HTML → MD: {summary['html_success']}/{summary['html_total']}건 성공
- 첨부파일 → MD: {summary['attach_success']}/{summary['attach_total']}건 성공

## 확장자별 현황
"""
    for ext, count in sorted(results["by_ext"].items(), key=lambda x: -x[1]):
        ok = results["by_ext_success"].get(ext, 0)
        md_summary += f"- {ext}: {ok}/{count}건 변환\n"

    fail_counts = Counter(f["error"].split(":")[0] for f in summary["failures"])
    md_summary += "\n## 실패 유형\n"
    for code, count in fail_counts.most_common():
        md_summary += f"- {code}: {count}건\n"

    md_path = outputs_dir / f"conversion-summary-{run_id}.md"
    md_path.write_text(md_summary, encoding="utf-8")

    print(f"\nSummary saved to: {summary_path.name}")
    print(json.dumps({
        "runId": run_id,
        "html": f"{summary['html_success']}/{summary['html_total']}",
        "attachments": f"{summary['attach_success']}/{summary['attach_total']}",
        "failureCount": len(summary["failures"]),
    }, indent=2))


if __name__ == "__main__":
    main()
