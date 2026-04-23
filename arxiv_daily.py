import os
import smtplib
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Iterable
from xml.etree import ElementTree as ET

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None


@dataclass(frozen=True)
class EmailConfig:
    from_email: str
    to_emails: list[str]
    password: str
    smtp_server: str = "smtp.qq.com"
    smtp_port: int = 465


@dataclass(frozen=True)
class ArxivApiConfig:
    base_url: str = "https://export.arxiv.org/api/query"
    page_size: int = 200


def _split_emails(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def load_email_config() -> EmailConfig:
    if load_dotenv is not None:
        load_dotenv()

    from_email = (os.getenv("FROM_EMAIL") or "").strip()
    to_email_raw = (os.getenv("TO_EMAIL") or "").strip()
    password = (os.getenv("EMAIL_PASSWORD") or "").strip()

    missing: list[str] = []
    if not from_email:
        missing.append("FROM_EMAIL")
    if not to_email_raw:
        missing.append("TO_EMAIL")
    if not password:
        missing.append("EMAIL_PASSWORD")
    if missing:
        joined = ", ".join(missing)
        raise SystemExit(
            f"Missing required environment variables: {joined}. "
            "Set them in GitHub Secrets or a local .env file."
        )

    to_emails = _split_emails(to_email_raw)
    if not to_emails:
        raise SystemExit("TO_EMAIL is empty after parsing.")

    return EmailConfig(from_email=from_email, to_emails=to_emails, password=password)


def is_dry_run() -> bool:
    return (os.getenv("DRY_RUN") or "").strip().lower() in {"1", "true", "yes"}


def max_email_chars() -> int:
    raw = (os.getenv("MAX_EMAIL_CHARS") or "").strip()
    if not raw:
        return 80_000
    try:
        value = int(raw)
    except ValueError:
        raise SystemExit("MAX_EMAIL_CHARS must be an integer.")
    if value < 5_000:
        raise SystemExit("MAX_EMAIL_CHARS is too small; use >= 5000.")
    return value


def load_arxiv_api_config() -> ArxivApiConfig:
    raw_page_size = (os.getenv("ARXIV_PAGE_SIZE") or "").strip()
    page_size = 200
    if raw_page_size:
        try:
            page_size = int(raw_page_size)
        except ValueError:
            raise SystemExit("ARXIV_PAGE_SIZE must be an integer.")
        if page_size < 1:
            raise SystemExit("ARXIV_PAGE_SIZE must be >= 1.")
        # arXiv API max_results supports up to 2000; keep a safe cap.
        page_size = min(page_size, 2000)
    return ArxivApiConfig(page_size=page_size)


def yesterday_utc() -> date:
    return datetime.utcnow().date() - timedelta(days=1)


def build_query(target_date: date) -> str:
    """
    arXiv API query string.
    Fetch all cs.* papers submitted on target_date (UTC).
    """
    ymd = target_date.strftime("%Y%m%d")
    return f"submittedDate:[{ymd}0000 TO {ymd}2359] AND cat:cs.*"


ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


def _parse_arxiv_atom(xml_bytes: bytes) -> list[dict[str, str]]:
    root = ET.fromstring(xml_bytes)
    entries = root.findall("atom:entry", ATOM_NS)
    papers: list[dict[str, str]] = []
    for entry in entries:
        title_el = entry.find("atom:title", ATOM_NS)
        id_el = entry.find("atom:id", ATOM_NS)
        author_els = entry.findall("atom:author/atom:name", ATOM_NS)
        category_els = entry.findall("atom:category", ATOM_NS)

        title = (title_el.text if title_el is not None else "") or ""
        title = title.replace("\n", " ").strip()
        entry_id = (id_el.text if id_el is not None else "") or ""
        authors = ", ".join((a.text or "").strip() for a in author_els if (a.text or "").strip())
        categories = ", ".join(
            (c.attrib.get("term") or "").strip() for c in category_els if (c.attrib.get("term") or "").strip()
        )

        papers.append({"title": title, "authors": authors, "url": entry_id, "categories": categories})
    return papers


def fetch_arxiv_papers_all(query: str, api: ArxivApiConfig) -> list[dict[str, str]]:
    """
    Fetch all matching papers by paginating the official arXiv API.
    This avoids client-side default limits (e.g. only returning ~100 results).
    """
    start = 0
    all_papers: list[dict[str, str]] = []

    while True:
        params = {
            "search_query": query,
            "start": str(start),
            "max_results": str(api.page_size),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        url = f"{api.base_url}?{urllib.parse.urlencode(params)}"

        req = urllib.request.Request(url, headers={"User-Agent": "arxiv-daily-email/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            xml_bytes = resp.read()

        page = _parse_arxiv_atom(xml_bytes)
        if not page:
            break

        all_papers.extend(page)
        start += len(page)

        # If the server returns fewer than requested, we've reached the end.
        if len(page) < api.page_size:
            break

    return all_papers

def _format_paper_block(paper: dict[str, str], global_index: int) -> str:
    lines: list[str] = []
    lines.append(f"{global_index}. {paper.get('title', '').strip()}")
    authors = paper.get("authors", "").strip()
    if authors:
        lines.append(f"   Authors: {authors}")
    categories = paper.get("categories", "").strip()
    if categories:
        lines.append(f"   Categories: {categories}")
    url = paper.get("url", "").strip()
    if url:
        lines.append(f"   Link: {url}")
    lines.append("")
    return "\n".join(lines)


def split_papers_into_email_batches(
    papers: list[dict[str, str]],
    target_date: date,
    max_chars: int,
) -> list[list[tuple[int, dict[str, str]]]]:
    """
    Split papers into batches so each email body stays under max_chars.
    We keep global numbering across batches for easier reading.
    """
    header = f"[arXiv] Daily digest for {target_date} (UTC)\n\n"
    batches: list[list[tuple[int, dict[str, str]]]] = []
    current: list[tuple[int, dict[str, str]]] = []
    current_len = len(header)

    for idx, paper in enumerate(papers, 1):
        block = _format_paper_block(paper, idx)
        block_len = len(block)

        if current and (current_len + block_len) > max_chars:
            batches.append(current)
            current = []
            current_len = len(header)

        current.append((idx, paper))
        current_len += block_len

    if current:
        batches.append(current)

    return batches


def build_email_content(papers: Iterable[dict[str, str]], target_date: date) -> str:
    papers_list = list(papers)
    if not papers_list:
        return f"[arXiv] No matching papers for {target_date} (UTC)."

    lines: list[str] = []
    lines.append(f"[arXiv] Daily digest for {target_date} (UTC)")
    lines.append("")

    for idx, paper in enumerate(papers_list, 1):
        lines.append(_format_paper_block(paper, idx).rstrip())

    return "\n".join(lines).rstrip() + "\n"


def build_email_content_indexed(papers: Iterable[tuple[int, dict[str, str]]], target_date: date) -> str:
    indexed = list(papers)
    if not indexed:
        return f"[arXiv] No matching papers for {target_date} (UTC)."

    lines: list[str] = []
    lines.append(f"[arXiv] Daily digest for {target_date} (UTC)")
    lines.append("")

    for global_index, paper in indexed:
        lines.append(_format_paper_block(paper, global_index).rstrip())

    return "\n".join(lines).rstrip() + "\n"


def send_email(config: EmailConfig, subject: str, content: str) -> None:
    msg = MIMEText(content, "plain", "utf-8")
    msg["Subject"] = str(Header(subject, "utf-8"))
    from_name = (os.getenv("FROM_NAME") or "arXiv Daily Bot").strip()
    msg["From"] = formataddr((str(Header(from_name, "utf-8")), config.from_email))
    msg["To"] = ", ".join(config.to_emails)

    with smtplib.SMTP_SSL(config.smtp_server, config.smtp_port) as server:
        server.login(config.from_email, config.password)
        server.sendmail(config.from_email, config.to_emails, msg.as_string())


def main() -> int:
    target = yesterday_utc()
    query = build_query(target)

    api = load_arxiv_api_config()
    papers = fetch_arxiv_papers_all(query, api)

    if is_dry_run():
        content = build_email_content(papers, target)
        print(content)
        return 0

    config = load_email_config()
    batches = split_papers_into_email_batches(papers, target, max_email_chars())
    total = len(batches)
    for part_index, batch in enumerate(batches, 1):
        body = build_email_content_indexed(batch, target)
        if total > 1:
            subject = f"arXiv Daily - {target} (Part {part_index}/{total})"
        else:
            subject = f"arXiv Daily - {target}"
        send_email(config, subject, body)

    print(f"Sent {len(papers)} papers for {target} in {total} email(s) to {', '.join(config.to_emails)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
