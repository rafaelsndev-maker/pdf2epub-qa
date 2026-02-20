from __future__ import annotations

import json
import os
import posixpath
import re
import shutil
import subprocess
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub

APPROVAL_SUFFIX = ".approval.json"
CHAPTER_REVIEW_SUFFIX = ".review.json"


def _normalize_epub_path(path: str) -> str:
    return posixpath.normpath((path or "").replace("\\", "/"))


def approval_path_for_epub(epub_path: Path) -> Path:
    return epub_path.with_suffix(f"{epub_path.suffix}{APPROVAL_SUFFIX}")


def chapter_review_path_for_epub(epub_path: Path) -> Path:
    return epub_path.with_suffix(f"{epub_path.suffix}{CHAPTER_REVIEW_SUFFIX}")


def write_editorial_approval(
    epub_path: Path,
    approver: str,
    notes: str | None = None,
    output_path: Path | None = None,
) -> dict:
    approver_name = (approver or "").strip()
    if not approver_name:
        raise RuntimeError("Informe o nome de quem aprovou.")

    target = output_path or approval_path_for_epub(epub_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "approved": True,
        "epub": str(epub_path),
        "approver": approver_name,
        "approved_at": datetime.now(UTC).isoformat(),
        "notes": (notes or "").strip(),
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "approved", "approval_file": str(target), "approval": payload}


def load_editorial_approval(epub_path: Path) -> dict:
    approval_path = approval_path_for_epub(epub_path)
    if not approval_path.exists():
        return {
            "approved": False,
            "status": "missing",
            "approval_file": str(approval_path),
            "notes": "Aprovacao humana nao encontrada.",
        }

    try:
        data = json.loads(approval_path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "approved": False,
            "status": "invalid",
            "approval_file": str(approval_path),
            "notes": "Arquivo de aprovacao existe, mas esta invalido.",
        }

    approved = bool(data.get("approved"))
    return {
        "approved": approved,
        "status": "approved" if approved else "rejected",
        "approval_file": str(approval_path),
        "approver": data.get("approver"),
        "approved_at": data.get("approved_at"),
        "notes": data.get("notes"),
    }


def _read_opf_spine(epub_path: Path) -> list[dict[str, str]]:
    with zipfile.ZipFile(epub_path, "r") as zf:
        container_xml = zf.read("META-INF/container.xml")
        container_root = ET.fromstring(container_xml)
        rootfile = container_root.find(".//{*}rootfile")
        if rootfile is None:
            raise RuntimeError("container.xml sem rootfile.")
        opf_raw = (rootfile.attrib.get("full-path") or "").strip()
        if not opf_raw:
            raise RuntimeError("container.xml sem caminho do OPF.")
        opf_path = _normalize_epub_path(opf_raw)
        opf_xml = zf.read(opf_path)
        opf_root = ET.fromstring(opf_xml)

    opf_dir = posixpath.dirname(opf_path)
    manifest: dict[str, tuple[str, str]] = {}
    for item in opf_root.findall(".//{*}manifest/{*}item"):
        item_id = (item.attrib.get("id") or "").strip()
        href = (item.attrib.get("href") or "").strip()
        media_type = (item.attrib.get("media-type") or "").strip().lower()
        if not item_id or not href:
            continue
        full = _normalize_epub_path(posixpath.join(opf_dir, href))
        manifest[item_id] = (full, media_type)

    spine_items: list[dict[str, str]] = []
    idx = 1
    frontmatter_paths = {
        "cover.xhtml",
        "cover_page.xhtml",
        "title_page.xhtml",
        "credits.xhtml",
    }
    for itemref in opf_root.findall(".//{*}spine/{*}itemref"):
        idref = (itemref.attrib.get("idref") or "").strip()
        resolved = manifest.get(idref)
        if not resolved:
            continue
        full_path, media_type = resolved
        if media_type not in {"application/xhtml+xml", "text/html"}:
            continue
        if full_path.endswith("nav.xhtml") or full_path.endswith("editorial_nav.xhtml"):
            continue
        if PurePosixPath(full_path).name in frontmatter_paths:
            continue
        label = PurePosixPath(full_path).name
        spine_items.append({"index": idx, "path": full_path, "label": label})
        idx += 1
    return spine_items


def create_chapter_review_template(
    epub_path: Path,
    reviewer: str | None = None,
    output_path: Path | None = None,
) -> dict:
    chapters = _read_opf_spine(epub_path)
    target = output_path or chapter_review_path_for_epub(epub_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "epub": str(epub_path),
        "reviewer": (reviewer or "").strip() or None,
        "created_at": datetime.now(UTC).isoformat(),
        "chapters": [
            {
                "index": item["index"],
                "path": item["path"],
                "label": item["label"],
                "status": "pending",
                "notes": "",
            }
            for item in chapters
        ],
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "status": "created",
        "review_file": str(target),
        "chapter_count": len(chapters),
        "review": payload,
    }


def load_chapter_review(epub_path: Path) -> dict:
    review_path = chapter_review_path_for_epub(epub_path)
    if not review_path.exists():
        return {
            "status": "missing",
            "review_file": str(review_path),
            "approved": False,
            "pending_count": 0,
            "rejected_count": 0,
            "approved_count": 0,
            "total_count": 0,
            "notes": "Revisao humana por capitulo nao encontrada.",
        }

    try:
        data = json.loads(review_path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "status": "invalid",
            "review_file": str(review_path),
            "approved": False,
            "pending_count": 0,
            "rejected_count": 0,
            "approved_count": 0,
            "total_count": 0,
            "notes": "Arquivo de revisao por capitulo existe, mas esta invalido.",
        }

    chapters = data.get("chapters", [])
    total = len(chapters)
    approved_count = sum(1 for row in chapters if str(row.get("status")) == "approved")
    rejected_count = sum(1 for row in chapters if str(row.get("status")) == "rejected")
    pending_count = sum(1 for row in chapters if str(row.get("status")) == "pending")
    fully_approved = total > 0 and approved_count == total

    return {
        "status": "ok",
        "review_file": str(review_path),
        "approved": fully_approved,
        "reviewer": data.get("reviewer"),
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
        "pending_count": pending_count,
        "rejected_count": rejected_count,
        "approved_count": approved_count,
        "total_count": total,
        "chapters": chapters,
    }


def mark_chapter_review(
    epub_path: Path,
    chapter_index: int,
    status: str,
    reviewer: str | None = None,
    notes: str | None = None,
) -> dict:
    if status not in {"approved", "rejected", "pending"}:
        raise RuntimeError("status invalido. Use approved, rejected ou pending.")

    review_path = chapter_review_path_for_epub(epub_path)
    if not review_path.exists():
        create_chapter_review_template(
            epub_path=epub_path,
            reviewer=reviewer,
            output_path=review_path,
        )

    try:
        data = json.loads(review_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError("Arquivo de revisao por capitulo invalido.") from exc

    chapters = data.get("chapters", [])
    target = None
    for row in chapters:
        if int(row.get("index", -1)) == chapter_index:
            target = row
            break
    if target is None:
        raise RuntimeError(f"Capitulo {chapter_index} nao encontrado no review.")

    target["status"] = status
    if notes is not None:
        target["notes"] = notes.strip()
    if reviewer:
        data["reviewer"] = reviewer.strip()
    data["updated_at"] = datetime.now(UTC).isoformat()
    review_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return load_chapter_review(epub_path)


def run_epubcheck(epub_path: Path) -> dict:
    jar_env = (os.getenv("PDF2EPUB_QA_EPUBCHECK_JAR", "") or "").strip()
    if not jar_env:
        return {
            "status": "not_configured",
            "notes": "Defina PDF2EPUB_QA_EPUBCHECK_JAR para validar com epubcheck.",
            "error_count": 0,
            "warning_count": 0,
        }

    jar_path = Path(jar_env)
    if not jar_path.exists():
        return {
            "status": "jar_not_found",
            "notes": f"epubcheck jar nao encontrado em: {jar_path}",
            "error_count": 0,
            "warning_count": 0,
        }

    java_cmd = (os.getenv("PDF2EPUB_QA_JAVA_CMD", "java") or "java").strip()
    if shutil.which(java_cmd) is None:
        return {
            "status": "java_missing",
            "notes": f"Comando Java nao encontrado: {java_cmd}",
            "error_count": 0,
            "warning_count": 0,
        }

    cmd = [java_cmd, "-jar", str(jar_path), str(epub_path)]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except Exception as exc:
        return {
            "status": "execution_error",
            "notes": f"Falha ao executar epubcheck: {exc}",
            "error_count": 0,
            "warning_count": 0,
        }

    output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    error_count = len(re.findall(r"\bERROR\b", output))
    warning_count = len(re.findall(r"\bWARNING\b", output))
    status = "passed" if proc.returncode == 0 and error_count == 0 else "failed"
    excerpt = "\n".join(line for line in output.splitlines()[:30]).strip()
    return {
        "status": status,
        "command": cmd,
        "exit_code": proc.returncode,
        "error_count": error_count,
        "warning_count": warning_count,
        "output_excerpt": excerpt,
    }


def _read_opf_meta(epub_path: Path) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    with zipfile.ZipFile(epub_path, "r") as zf:
        container_xml = zf.read("META-INF/container.xml")
        container_root = ET.fromstring(container_xml)
        rootfile = container_root.find(".//{*}rootfile")
        if rootfile is None:
            raise RuntimeError("container.xml sem rootfile.")
        opf_raw = (rootfile.attrib.get("full-path") or "").strip()
        if not opf_raw:
            raise RuntimeError("container.xml sem caminho do OPF.")
        opf_path = _normalize_epub_path(opf_raw)
        opf_xml = zf.read(opf_path)
        opf_root = ET.fromstring(opf_xml)

    metadata_values: dict[str, list[str]] = {}
    for el in opf_root.findall(".//{*}metadata/{*}*"):
        tag = (el.tag.split("}")[-1] if "}" in el.tag else el.tag).strip().lower()
        text = (el.text or "").strip()
        if not text:
            continue
        metadata_values.setdefault(tag, []).append(text)

    properties: dict[str, list[str]] = {}
    for meta in opf_root.findall(".//{*}metadata/{*}meta"):
        prop = (meta.attrib.get("property") or "").strip()
        if not prop:
            continue
        properties.setdefault(prop, []).append((meta.text or "").strip())
    return properties, metadata_values


def _is_isbn(value: str) -> bool:
    cleaned = re.sub(r"[^0-9Xx]", "", value or "")
    return len(cleaned) in {10, 13}


def _env_flag(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return raw in {"1", "true", "yes", "y", "on"}


def collect_editorial_structure(epub_path: Path) -> dict:
    book = epub.read_epub(str(epub_path))
    documents = [item for item in book.get_items() if item.get_type() == ebooklib.ITEM_DOCUMENT]
    if not documents:
        return {
            "document_count": 0,
            "heading_count": 0,
            "heading_jump_count": 0,
            "page_anchor_count": 0,
            "broken_internal_links": 0,
            "image_without_alt_count": 0,
            "table_count": 0,
            "footnote_link_count": 0,
            "landmarks_present": False,
            "page_list_present": False,
        }

    ids_by_doc: dict[str, set[str]] = {}
    soups: list[tuple[str, BeautifulSoup]] = []
    heading_count = 0
    heading_jump_count = 0
    page_anchor_count = 0
    image_without_alt_count = 0
    table_count = 0
    footnote_link_count = 0
    landmarks_present = False
    page_list_present = False

    for item in documents:
        doc_name = _normalize_epub_path(item.get_name())
        soup = BeautifulSoup(item.get_content(), "html.parser")
        soups.append((doc_name, soup))

        ids_by_doc[doc_name] = {
            str(el.get("id")).strip() for el in soup.select("[id]") if el.get("id")
        }
        headings = [
            int(el.name[1])
            for el in soup.find_all(re.compile(r"^h[1-6]$"))
            if el.name and len(el.name) == 2
        ]
        heading_count += len(headings)
        for prev, curr in zip(headings, headings[1:]):
            if curr - prev > 1:
                heading_jump_count += 1

        page_anchor_count += len(soup.find_all(id=re.compile(r"^page-\d+$")))
        table_count += len(soup.find_all("table"))

        for img in soup.find_all("img"):
            if not (img.get("alt") or "").strip():
                image_without_alt_count += 1

        for nav in soup.find_all("nav"):
            nav_type = (
                nav.get("epub:type")
                or nav.get("type")
                or nav.get("role")
                or ""
            ).lower()
            if "landmarks" in nav_type:
                landmarks_present = True
            if "page-list" in nav_type or "doc-pagelist" in nav_type:
                page_list_present = True

        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip().lower()
            if "noteref" in (a.get("epub:type") or "").lower() or href.startswith("#fn"):
                footnote_link_count += 1

    broken_internal_links = 0
    for doc_name, soup in soups:
        doc_dir = posixpath.dirname(doc_name)
        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            if not href:
                continue
            href_l = href.lower()
            if href_l.startswith(("http://", "https://", "mailto:", "tel:")):
                continue

            target_doc = doc_name
            fragment = ""
            if href.startswith("#"):
                fragment = href[1:]
            elif "#" in href:
                rel_path, fragment = href.split("#", 1)
                target_doc = _normalize_epub_path(posixpath.join(doc_dir, rel_path))
            else:
                # Internal file reference without fragment; skip.
                continue

            if not fragment:
                continue
            if target_doc not in ids_by_doc or fragment not in ids_by_doc[target_doc]:
                broken_internal_links += 1

    return {
        "document_count": len(documents),
        "heading_count": heading_count,
        "heading_jump_count": heading_jump_count,
        "page_anchor_count": page_anchor_count,
        "broken_internal_links": broken_internal_links,
        "image_without_alt_count": image_without_alt_count,
        "table_count": table_count,
        "footnote_link_count": footnote_link_count,
        "landmarks_present": landmarks_present,
        "page_list_present": page_list_present,
    }


def collect_editorial_metadata(epub_path: Path) -> dict:
    try:
        properties, metadata_values = _read_opf_meta(epub_path)
    except Exception as exc:
        return {"status": "error", "notes": f"Falha ao ler metadados OPF: {exc}"}

    required_accessibility_props = [
        "schema:accessMode",
        "schema:accessModeSufficient",
        "schema:accessibilityFeature",
        "schema:accessibilityHazard",
        "schema:accessibilitySummary",
    ]
    missing_props = [prop for prop in required_accessibility_props if not properties.get(prop)]

    identifiers = metadata_values.get("identifier", [])
    has_isbn = any(_is_isbn(value) for value in identifiers)
    publisher = metadata_values.get("publisher", [])
    rights = metadata_values.get("rights", [])
    description = metadata_values.get("description", [])

    return {
        "status": "ok",
        "has_isbn": has_isbn,
        "identifier_count": len(identifiers),
        "has_publisher": bool(publisher),
        "has_rights": bool(rights),
        "has_description": bool(description),
        "accessibility_props_present": len(required_accessibility_props) - len(missing_props),
        "missing_accessibility_props": missing_props,
    }


def build_editorial_gate(
    qa_report: dict,
    structure: dict,
    metadata: dict,
    epubcheck: dict,
    approval: dict,
    chapter_review: dict | None = None,
    strict_epubcheck: bool = False,
) -> dict:
    blockers: list[str] = []
    checks: list[dict[str, object]] = []
    coverage = float(qa_report.get("coverage_text_percent", 0.0))
    issues = qa_report.get("issues", [])
    missing_page_count = sum(1 for item in issues if item.get("status") == "missing_page")
    require_chapter_review = _env_flag("PDF2EPUB_QA_REQUIRE_CHAPTER_REVIEW", True)

    def add_check(check_id: str, label: str, passed: bool, weight: int, fail_message: str) -> None:
        checks.append(
            {
                "id": check_id,
                "label": label,
                "status": "pass" if passed else "fail",
                "weight": weight,
            }
        )
        if not passed:
            blockers.append(fail_message)

    add_check(
        "text_coverage",
        "Cobertura textual >= 95%",
        coverage >= 95.0,
        20,
        f"Cobertura textual abaixo do minimo editorial (95%): {coverage:.2f}%.",
    )
    add_check(
        "page_anchors",
        "Sem paginas sem ancora",
        missing_page_count == 0,
        10,
        f"Paginas sem ancora no EPUB: {missing_page_count}.",
    )
    broken_links = int(structure.get("broken_internal_links", 0))
    add_check(
        "internal_links",
        "Links internos validos",
        broken_links == 0,
        10,
        f"Links internos quebrados encontrados: {broken_links}.",
    )
    image_without_alt = int(structure.get("image_without_alt_count", 0))
    add_check(
        "image_alt_text",
        "Imagens com alt text",
        image_without_alt == 0,
        10,
        f"Imagens sem alt text: {image_without_alt}.",
    )
    add_check(
        "landmarks",
        "Landmarks presentes",
        bool(structure.get("landmarks_present")),
        10,
        "Navegacao landmarks ausente.",
    )
    add_check(
        "page_list",
        "Page-list presente",
        bool(structure.get("page_list_present")),
        10,
        "Navegacao page-list ausente.",
    )
    if metadata.get("status") != "ok":
        add_check(
            "metadata_status",
            "Metadados editoriais validos",
            False,
            15,
            "Falha ao validar metadados editoriais.",
        )
    else:
        metadata_ok = (
            not metadata.get("missing_accessibility_props")
            and bool(metadata.get("has_publisher"))
            and bool(metadata.get("has_rights"))
            and bool(metadata.get("has_description"))
        )
        add_check(
            "metadata_complete",
            "Metadados editoriais completos",
            metadata_ok,
            15,
            (
                "Metadados editoriais incompletos "
                "(publisher/rights/description/acessibilidade)."
            ),
        )

    epubcheck_status = str(epubcheck.get("status", "not_configured"))
    if epubcheck_status == "failed":
        add_check("epubcheck", "epubcheck aprovado", False, 10, "epubcheck encontrou erros.")
    elif strict_epubcheck and epubcheck_status != "passed":
        add_check(
            "epubcheck",
            "epubcheck aprovado",
            False,
            10,
            "epubcheck obrigatorio no modo estrito e nao passou.",
        )
    else:
        add_check("epubcheck", "epubcheck aprovado", True, 10, "")

    add_check(
        "approval",
        "Aprovacao humana final",
        bool(approval.get("approved")),
        10,
        "Aprovacao humana editorial ausente.",
    )
    chapter_review_data = chapter_review or {}
    if require_chapter_review:
        chapter_review_ok = bool(chapter_review_data.get("approved"))
        pending = int(chapter_review_data.get("pending_count", 0))
        rejected = int(chapter_review_data.get("rejected_count", 0))
        add_check(
            "chapter_review",
            "Revisao humana por capitulo",
            chapter_review_ok,
            15,
            (
                "Revisao humana por capitulo pendente "
                f"(pending={pending}, rejected={rejected})."
            ),
        )

    total_weight = sum(int(item["weight"]) for item in checks)
    passed_weight = sum(int(item["weight"]) for item in checks if item["status"] == "pass")
    score = round((passed_weight / max(total_weight, 1)) * 100, 2)

    return {
        "release_ready": len(blockers) == 0,
        "blockers": blockers,
        "score": score,
        "checks": checks,
        "require_chapter_review": require_chapter_review,
        "strict_epubcheck": strict_epubcheck,
    }


def build_editorial_report(
    pdf_path: Path,
    epub_path: Path,
    qa_report: dict,
    strict_epubcheck: bool = False,
) -> dict:
    _ = pdf_path
    try:
        structure = collect_editorial_structure(epub_path)
    except Exception as exc:
        structure = {"status": "error", "notes": f"Falha ao inspecionar estrutura: {exc}"}

    metadata = collect_editorial_metadata(epub_path)
    epubcheck = run_epubcheck(epub_path)
    approval = load_editorial_approval(epub_path)
    chapter_review = load_chapter_review(epub_path)
    gate = build_editorial_gate(
        qa_report=qa_report,
        structure=structure if isinstance(structure, dict) else {},
        metadata=metadata if isinstance(metadata, dict) else {},
        epubcheck=epubcheck,
        approval=approval,
        chapter_review=chapter_review,
        strict_epubcheck=strict_epubcheck,
    )
    return {
        "structure": structure,
        "metadata": metadata,
        "epubcheck": epubcheck,
        "approval": approval,
        "chapter_review": chapter_review,
        "gate": gate,
    }
