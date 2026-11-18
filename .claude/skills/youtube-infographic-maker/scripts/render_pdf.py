#!/usr/bin/env python3
"""Render the infographic HTML to a print-ready PDF (+ optional PNG preview).

Usage:
    python render_pdf.py infographic.html [out.pdf] [--a4] [--preview out.png]

Tries Chromium via Playwright (Node, then Python) first (best fidelity, adds "page X / Y" footer),
then WeasyPrint. Prints the page count so you can check the length. If neither
renderer is available it says so; the HTML itself still prints cleanly from
any browser (Ctrl/Cmd+P -> Save as PDF, background graphics on).
"""
import argparse
import os
import pathlib
import subprocess
import sys

FOOTER = ('<div style="width:100%;font-size:7pt;color:#8a8f98;font-family:Arial,sans-serif;'
          'padding:0 0.5in;display:flex;justify-content:space-between;">'
          '<span class="title"></span>'
          '<span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>')


def count_pages(pdf):
    try:
        from pypdf import PdfReader
        return len(PdfReader(pdf).pages)
    except Exception:
        pass
    try:
        out = subprocess.run(["pdfinfo", pdf], capture_output=True, text=True).stdout
        for line in out.splitlines():
            if line.startswith("Pages:"):
                return int(line.split()[1])
    except Exception:
        pass
    return "?"


def with_node(html, pdf, a4, preview):
    js = os.path.join(os.path.dirname(os.path.abspath(__file__)), "render_pdf.js")
    cmd = ["node", js, html, pdf, "A4" if a4 else "Letter"] + ([preview] if preview else [])
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[:300] or "node renderer failed")


def with_playwright(html, pdf, a4, preview):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception:
            browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        page = browser.new_page()
        page.goto(pathlib.Path(html).resolve().as_uri(), wait_until="networkidle")
        page.emulate_media(media="print")
        page.pdf(path=pdf, format="A4" if a4 else "Letter", print_background=True,
                 prefer_css_page_size=not a4, display_header_footer=True,
                 header_template="<div></div>", footer_template=FOOTER,
                 margin={"top": "0.45in", "bottom": "0.6in", "left": "0.5in", "right": "0.5in"})
        if preview:
            page.emulate_media(media="screen")
            page.set_viewport_size({"width": 850, "height": 1100})
            page.screenshot(path=preview, full_page=True)
        browser.close()


def with_weasyprint(html, pdf):
    from weasyprint import HTML
    HTML(filename=html).write_pdf(pdf)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("html")
    ap.add_argument("pdf", nargs="?")
    ap.add_argument("--a4", action="store_true", help="A4 instead of US Letter")
    ap.add_argument("--preview", help="also save a full-page PNG preview")
    a = ap.parse_args()
    pdf = a.pdf or os.path.splitext(a.html)[0] + ".pdf"
    if a.a4:  # swap the @page size so CSS and PDF agree
        src = pathlib.Path(a.html).read_text(encoding="utf-8")
        pathlib.Path(a.html).write_text(src.replace("size: Letter", "size: A4"), encoding="utf-8")

    errors = []
    for name, fn in (("node-playwright", lambda: with_node(a.html, pdf, a.a4, a.preview)),
                     ("playwright", lambda: with_playwright(a.html, pdf, a.a4, a.preview)),
                     ("weasyprint", lambda: with_weasyprint(a.html, pdf))):
        try:
            fn()
            print(f"PDF_OK {pdf} via {name} — pages: {count_pages(pdf)}")
            if a.preview and "playwright" in name:
                print(f"PREVIEW_OK {a.preview}")
            return
        except Exception as e:
            errors.append(f"{name}: {type(e).__name__}: {str(e)[:200]}")
    # last resort: try installing weasyprint once
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "weasyprint"],
                       capture_output=True, text=True)
    if r.returncode == 0:
        try:
            with_weasyprint(a.html, pdf)
            print(f"PDF_OK {pdf} via weasyprint — pages: {count_pages(pdf)}")
            return
        except Exception as e:
            errors.append(f"weasyprint(after install): {e}")
    print("PDF_FAILED " + " | ".join(errors))
    print("Deliver the HTML: it prints cleanly from any browser (Print -> Save as PDF, "
          "enable 'Background graphics').")
    sys.exit(2)


if __name__ == "__main__":
    main()
