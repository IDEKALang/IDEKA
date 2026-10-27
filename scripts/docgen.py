#!/usr/bin/env python3
"""
IDEKA Documentation Site Generator
Converts .md doc files into a static HTML site matching the IDEKAspl.org design system.

Usage:
    python3 IDEKA_docgen.py <input_dir> <output_dir>

    input_dir  : folder containing .md files
    output_dir : where to write the HTML site

Each .md file becomes a page. An index.html is generated listing all docs.
The nav, footer, and visual style match IDEKAspl.org exactly.
"""

import sys
import os
import re
import html
import shutil
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Minimal Markdown -> HTML converter
# Handles: headings, code blocks (fenced), inline code, bold, italic,
#          horizontal rules, paragraphs, unordered/ordered lists, links,
#          anchor tags (<a id="...">), blockquotes, tables.
# ---------------------------------------------------------------------------

def md_to_html(md: str) -> tuple[str, list[tuple[str, str]]]:
    """
    Convert markdown to HTML.
    Returns (html_body, toc) where toc is list of (anchor_id, heading_text).
    """
    lines = md.split('\n')
    out = []
    toc: list[tuple[str, str]] = []
    i = 0
    in_list = None       # 'ul' or 'ol'
    list_depth = 0

    def close_list():
        nonlocal in_list
        if in_list:
            out.append(f'</{in_list}>')
            in_list = None

    def inline(text: str) -> str:
        """Process inline markdown within a line."""
        # preserve existing HTML tags (anchor tags etc)
        # bold + italic
        text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<strong><em>\1</em></strong>', text)
        text = re.sub(r'\*\*(.+?)\*\*',     r'<strong>\1</strong>', text)
        text = re.sub(r'\*(.+?)\*',          r'<em>\1</em>', text)
        # inline code
        text = re.sub(r'`([^`]+)`', lambda m: f'<code>{html.escape(m.group(1))}</code>', text)
        # links
        text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)',
                      lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', text)
        return text

    def slugify(text: str) -> str:
        text = re.sub(r'[^\w\s-]', '', text.lower())
        return re.sub(r'[\s_]+', '-', text).strip('-')

    while i < len(lines):
        line = lines[i]

        # --- fenced code block ---
        if line.strip().startswith('```'):
            close_list()
            lang = line.strip()[3:].strip()
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i])
                i += 1
            code_content = html.escape('\n'.join(code_lines))
            lang_label = lang if lang else 'IDEKA'
            out.append(f'''<div class="doc-code-wrap">
  <div class="doc-code-bar">
    <div class="code-dot code-dot-r"></div>
    <div class="code-dot code-dot-y"></div>
    <div class="code-dot code-dot-g"></div>
    <span class="code-lang">{html.escape(lang_label)}</span>
  </div>
  <pre class="doc-pre"><code>{code_content}</code></pre>
</div>''')
            i += 1
            continue

        # --- horizontal rule ---
        if re.match(r'^[-*_]{3,}\s*$', line.strip()):
            close_list()
            out.append('<hr class="doc-hr">')
            i += 1
            continue

        # --- raw anchor tags (passthrough) ---
        if re.match(r'^\s*<a\s+id=', line.strip()):
            out.append(line.strip())
            i += 1
            continue

        # --- headings ---
        m = re.match(r'^(#{1,6})\s+(.*)', line)
        if m:
            close_list()
            level = len(m.group(1))
            text = m.group(2).strip()
            slug = slugify(re.sub(r'[*`_]', '', text))
            toc.append((slug, text, level))
            tag = f'h{level}'
            cls = f'doc-h{level}'
            out.append(f'<{tag} id="{slug}" class="{cls}">{inline(text)}</{tag}>')
            i += 1
            continue

        # --- blockquote ---
        if line.startswith('>'):
            close_list()
            content = line[1:].strip()
            out.append(f'<blockquote class="doc-blockquote">{inline(content)}</blockquote>')
            i += 1
            continue

        # --- table ---
        if '|' in line and i + 1 < len(lines) and re.match(r'^[\s|:-]+$', lines[i+1]):
            close_list()
            header_cells = [c.strip() for c in line.strip('|').split('|')]
            i += 2  # skip separator
            rows = []
            while i < len(lines) and '|' in lines[i]:
                rows.append([c.strip() for c in lines[i].strip('|').split('|')])
                i += 1
            th = ''.join(f'<th>{inline(c)}</th>' for c in header_cells)
            table = f'<table class="doc-table"><thead><tr>{th}</tr></thead><tbody>'
            for row in rows:
                td = ''.join(f'<td>{inline(c)}</td>' for c in row)
                table += f'<tr>{td}</tr>'
            table += '</tbody></table>'
            out.append(table)
            continue

        # --- unordered list ---
        m = re.match(r'^(\s*)([-*+])\s+(.*)', line)
        if m:
            if in_list != 'ul':
                close_list()
                out.append('<ul class="doc-ul">')
                in_list = 'ul'
            out.append(f'<li>{inline(m.group(3))}</li>')
            i += 1
            continue

        # --- ordered list ---
        m = re.match(r'^(\s*)\d+\.\s+(.*)', line)
        if m:
            if in_list != 'ol':
                close_list()
                out.append('<ol class="doc-ol">')
                in_list = 'ol'
            out.append(f'<li>{inline(m.group(2))}</li>')
            i += 1
            continue

        # --- blank line ---
        if not line.strip():
            close_list()
            i += 1
            continue

        # --- paragraph ---
        close_list()
        # collect continuation lines
        para_lines = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not lines[i].startswith('#') \
              and not lines[i].strip().startswith('```') \
              and not lines[i].startswith('>') \
              and not re.match(r'^(\s*)([-*+])\s', lines[i]) \
              and not re.match(r'^(\s*)\d+\.\s', lines[i]) \
              and not re.match(r'^[-*_]{3,}\s*$', lines[i]):
            para_lines.append(lines[i])
            i += 1
        para = ' '.join(para_lines)
        out.append(f'<p class="doc-p">{inline(para)}</p>')

    close_list()
    return '\n'.join(out), toc

# ---------------------------------------------------------------------------
# Syntax highlighting for IDEKA code blocks
# ---------------------------------------------------------------------------

IDEKA_KEYWORDS = {
    'def','return','if','elif','else','while','for','in','break','continue',
    'struct','object','namespace','using','extern','export','import','from',
    'comptime','emitideka','macro','template','contract','trait','interface',
    'typeof','sizeof','alignof','endianof','data','singinit','defer','try',
    'throw','catch','assert','escape','enum','union','switch','case','default',
    'not','and','or','true','false','void','nullptr','new','delete',
    'cdecl','stdcall','fastcall','vectorcall','thiscall','syscall',
    'noreturn','deprecated','has','module','break',
}

IDEKA_TYPES = {
    'int','uint','long','ulong','short','ushort','byte','ubyte','char',
    'float','double','bool','size_t','void',
    'i8','i16','i32','i64','i128',
    'u8','u16','u32','u64','u128',
    'f32','f64',
}

def highlight_IDEKA(code: str) -> str:
    """Simple token-based IDEKA syntax highlighter producing HTML spans."""
    result = []
    i = 0

    while i < len(code):
        # newline
        if code[i] == '\n':
            result.append('\n')
            i += 1
            continue

        # line comment
        if code[i:i+2] == '//':
            end = code.find('\n', i)
            if end == -1:
                end = len(code)
            result.append(f'<span class="ck-cmt">{html.escape(code[i:end])}</span>')
            i = end
            continue

        # block comment ///
        if code[i:i+3] == '///':
            end = code.find('///', i + 3)
            if end == -1:
                end = len(code)
            else:
                end += 3
            result.append(f'<span class="ck-cmt">{html.escape(code[i:end])}</span>')
            i = end
            continue

        # string literal
        if code[i] in ('"', "'"):
            q = code[i]
            j = i + 1
            while j < len(code) and code[j] != q:
                if code[j] == '\\':
                    j += 1
                j += 1
            j += 1
            result.append(f'<span class="ck-str">{html.escape(code[i:j])}</span>')
            i = j
            continue

        # number
        if code[i].isdigit() or (code[i] == '-' and i+1 < len(code) and code[i+1].isdigit()):
            j = i + 1
            while j < len(code) and (code[j].isalnum() or code[j] in '.xXabcdefABCDEF_'):
                j += 1
            result.append(f'<span class="ck-num">{html.escape(code[i:j])}</span>')
            i = j
            continue

        # identifier or keyword
        if code[i].isalpha() or code[i] == '_':
            j = i
            while j < len(code) and (code[j].isalnum() or code[j] == '_'):
                j += 1
            word = code[i:j]
            if word in IDEKA_KEYWORDS:
                result.append(f'<span class="ck-kw">{html.escape(word)}</span>')
            elif word in IDEKA_TYPES:
                result.append(f'<span class="ck-ty">{html.escape(word)}</span>')
            else:
                result.append(html.escape(word))
            i = j
            continue

        # preprocessor
        if code[i] == '#':
            j = i
            while j < len(code) and code[j] not in (' ', '\n', ';', '('):
                j += 1
            result.append(f'<span class="ck-pp">{html.escape(code[i:j])}</span>')
            i = j
            continue

        # operator / punctuation
        result.append(html.escape(code[i]))
        i += 1

    return ''.join(result)

def apply_highlighting(body: str) -> str:
    """Post-process HTML to apply IDEKA highlighting to code blocks."""
    def replace_block(m):
        code = html.unescape(m.group(1))
        highlighted = highlight_IDEKA(code)
        return f'<pre class="doc-pre"><code>{highlighted}</code></pre>'
    return re.sub(r'<pre class="doc-pre"><code>(.*?)</code></pre>',
                  replace_block, body, flags=re.DOTALL)

# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

NAV_HTML = '''<nav>
  <a href="/" class="nav-logo">
    <svg class="nav-logo-mark" viewBox="0 0 28 28" fill="none">
      <polygon points="14,2 26,24 2,24" fill="none" stroke="#00aaff" stroke-width="1.5"/>
      <polygon points="14,8 21,21 7,21" fill="none" stroke="#00aaff" stroke-width="0.8" opacity="0.45"/>
      <circle cx="14" cy="14" r="1.5" fill="#00aaff"/>
    </svg>
    <span class="nav-logo-text">IDEKA</span>
  </a>
  <ul class="nav-links">
    <li><a href="/">Home</a></li>
    <li><a href="/docs/">Docs</a></li>
    <li><a href="https://discord.gg/RAHjbYuNUc" target="_blank">Discord</a></li>
    <li><a href="https://IDEKAspl.org/ide" target="_blank">Try Online</a></li>
  </ul>
  <div class="nav-spacer"></div>
  <a href="https://github.com/kvthweatt/IDEKALang" target="_blank" class="nav-cta">GitHub</a>
  <button class="nav-hamburger" id="nav-hamburger" aria-label="Menu" aria-expanded="false">
    <span></span><span></span><span></span>
  </button>
</nav>
<div class="nav-mobile-menu" id="nav-mobile-menu" aria-hidden="true">
  <a href="/" class="nav-mobile-link">Home</a>
  <a href="/docs/" class="nav-mobile-link">Docs</a>
  <a href="https://discord.gg/RAHjbYuNUc" target="_blank" class="nav-mobile-link">Discord</a>
  <a href="https://IDEKAspl.org/ide" target="_blank" class="nav-mobile-link">Try Online</a>
  <a href="https://github.com/kvthweatt/IDEKALang" target="_blank" class="nav-mobile-link cta">GitHub &rarr;</a>
</div>'''

FOOTER_HTML = '''<footer>
  <div class="container">
    <div class="footer-inner">
      <a href="/" class="nav-logo footer-logo">
        <svg class="nav-logo-mark" viewBox="0 0 28 28" fill="none">
          <polygon points="14,2 26,24 2,24" fill="none" stroke="#00aaff" stroke-width="1.5"/>
          <polygon points="14,8 21,21 7,21" fill="none" stroke="#00aaff" stroke-width="0.8" opacity="0.45"/>
          <circle cx="14" cy="14" r="1.5" fill="#00aaff"/>
        </svg>
        <span class="nav-logo-text">IDEKA</span>
      </a>
      <div class="footer-sep"></div>
      <span class="footer-copy">&copy; Karac Von Thweatt. All rights reserved.</span>
      <div class="footer-links">
        <a href="https://github.com/kvthweatt/IDEKALang" target="_blank">GitHub</a>
        <a href="https://discord.gg/RAHjbYuNUc" target="_blank">Discord</a>
      </div>
    </div>
  </div>
</footer>'''

DOC_CSS = '''
/* ── Doc page layout ─────────────────────────────────────────────────── */
.doc-layout {
    display: flex;
    min-height: calc(100vh - 64px);
    max-width: 1400px;
    margin: 0 auto;
    padding: 0 24px;
    gap: 0;
}

.doc-sidebar {
    width: 260px;
    flex-shrink: 0;
    position: sticky;
    top: 64px;
    height: calc(100vh - 64px);
    overflow-y: auto;
    padding: 32px 0 32px 0;
    border-right: 1px solid var(--border);
    scrollbar-width: thin;
    scrollbar-color: var(--border2) transparent;
}

.doc-sidebar::-webkit-scrollbar { width: 3px; }
.doc-sidebar::-webkit-scrollbar-thumb { background: var(--border2); }

.doc-sidebar-title {
    font-family: var(--mono);
    font-size: 10px;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: var(--text-mute);
    padding: 0 24px;
    margin-bottom: 12px;
}

.doc-toc-link {
    display: block;
    padding: 4px 24px;
    font-size: 12px;
    color: var(--text-dim);
    text-decoration: none;
    line-height: 1.5;
    transition: color 0.15s;
    border-left: 2px solid transparent;
}
.doc-toc-link:hover { color: var(--text); }
.doc-toc-link.active { color: var(--blue); border-left-color: var(--blue); }
.doc-toc-link.toc-h1 { padding-left: 24px; font-weight: 600; color: var(--text); font-size: 12px; }
.doc-toc-link.toc-h2 { padding-left: 24px; }
.doc-toc-link.toc-h3 { padding-left: 38px; font-size: 11px; }
.doc-toc-link.toc-h4 { padding-left: 52px; font-size: 11px; color: var(--text-mute); }

.doc-content {
    flex: 1;
    min-width: 0;
    padding: 40px 0 80px 48px;
    max-width: 860px;
}

/* ── Doc typography ──────────────────────────────────────────────────── */
.doc-h1 {
    font-family: var(--display);
    font-size: clamp(26px, 4vw, 36px);
    font-weight: 700;
    color: #fff;
    letter-spacing: -0.02em;
    margin: 0 0 24px;
    padding-bottom: 16px;
    border-bottom: 1px solid var(--border2);
}
.doc-h2 {
    font-family: var(--mono);
    font-size: 16px;
    font-weight: 700;
    color: var(--text);
    letter-spacing: 0.02em;
    margin: 40px 0 12px;
    padding-top: 8px;
}
.doc-h3 {
    font-family: var(--mono);
    font-size: 13px;
    font-weight: 700;
    color: var(--blue);
    letter-spacing: 0.04em;
    margin: 28px 0 8px;
}
.doc-h4 {
    font-family: var(--mono);
    font-size: 12px;
    font-weight: 700;
    color: var(--text-dim);
    letter-spacing: 0.04em;
    margin: 20px 0 6px;
    text-transform: uppercase;
}
.doc-h5, .doc-h6 {
    font-family: var(--mono);
    font-size: 11px;
    color: var(--text-mute);
    margin: 16px 0 4px;
}

.doc-p {
    font-size: 14px;
    line-height: 1.75;
    color: var(--text-dim);
    margin: 0 0 14px;
}

.doc-p code, .doc-ul code, .doc-ol code, li code {
    font-family: var(--mono);
    font-size: 12px;
    color: var(--blue);
    background: var(--blue-soft);
    padding: 1px 5px;
    border-radius: 2px;
}

.doc-ul, .doc-ol {
    margin: 0 0 14px 20px;
    color: var(--text-dim);
    font-size: 13px;
    line-height: 1.8;
}

.doc-hr {
    border: none;
    border-top: 1px solid var(--border2);
    margin: 32px 0;
}

.doc-blockquote {
    border-left: 3px solid var(--blue-dim);
    padding: 8px 16px;
    margin: 16px 0;
    background: var(--blue-soft);
    color: var(--text-dim);
    font-size: 13px;
    font-style: italic;
}

.doc-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
    font-family: var(--mono);
    margin: 16px 0 24px;
}
.doc-table th {
    background: var(--dark);
    color: var(--blue);
    padding: 8px 12px;
    text-align: left;
    border: 1px solid var(--border2);
    font-size: 11px;
    letter-spacing: 0.06em;
    text-transform: uppercase;
}
.doc-table td {
    padding: 7px 12px;
    border: 1px solid var(--border);
    color: var(--text-dim);
    vertical-align: top;
}
.doc-table tr:nth-child(even) td { background: var(--dark); }

/* ── Code blocks ─────────────────────────────────────────────────────── */
.doc-code-wrap {
    background: var(--panel);
    border: 1px solid var(--border2);
    border-radius: 3px;
    overflow: hidden;
    margin: 12px 0 20px;
}
.doc-code-bar {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 14px;
    background: var(--dark);
    border-bottom: 1px solid var(--border);
}
.code-dot { width: 9px; height: 9px; border-radius: 50%; }
.code-dot-r { background: #3a1c1c; }
.code-dot-y { background: #2e2a12; }
.code-dot-g { background: #122e18; }
.code-lang {
    font-family: var(--mono);
    font-size: 10px;
    color: var(--text-mute);
    margin-left: 8px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}
.doc-pre {
    margin: 0;
    padding: 18px 22px;
    font-family: var(--mono);
    font-size: 12.5px;
    line-height: 1.7;
    color: var(--text);
    overflow-x: auto;
    background: transparent;
}
.doc-pre code { background: none; padding: 0; color: inherit; font-size: inherit; }

/* ── Syntax highlight spans ──────────────────────────────────────────── */
.ck-kw  { color: #00aaff; font-weight: 700; }
.ck-ty  { color: #68c4e8; }
.ck-str { color: #7ec68a; }
.ck-num { color: #c0956e; }
.ck-cmt { color: #3a4a5a; font-style: italic; }
.ck-pp  { color: #a07bd0; }

/* ── Doc index page ──────────────────────────────────────────────────── */
.doc-index-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 1px;
    background: var(--border);
    border: 1px solid var(--border);
    border-radius: 3px;
    overflow: hidden;
    margin-top: 32px;
}
.doc-index-card {
    background: var(--dark);
    padding: 28px 24px;
    text-decoration: none;
    display: flex;
    flex-direction: column;
    gap: 8px;
    transition: background 0.2s;
    position: relative;
}
.doc-index-card::after {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 1px;
    background: transparent;
    transition: background 0.25s;
}
.doc-index-card:hover { background: var(--panel); }
.doc-index-card:hover::after { background: var(--blue); }
.doc-index-card-label {
    font-family: var(--mono);
    font-size: 10px;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: var(--text-mute);
}
.doc-index-card-title {
    font-family: var(--mono);
    font-size: 14px;
    font-weight: 700;
    color: #fff;
    letter-spacing: 0.02em;
}
.doc-index-card-arrow {
    font-family: var(--mono);
    font-size: 11px;
    color: var(--blue);
    margin-top: auto;
    padding-top: 8px;
    opacity: 0.7;
    transition: opacity 0.2s;
}
.doc-index-card:hover .doc-index-card-arrow { opacity: 1; }

/* ── Responsive ──────────────────────────────────────────────────────── */
@media (max-width: 900px) {
    .doc-sidebar { display: none; }
    .doc-content { padding: 24px 0 60px; }
    .doc-layout { padding: 0 18px; }
}
'''

DOC_JS = '''
// Active TOC link on scroll
(function() {
    const links = document.querySelectorAll('.doc-toc-link');
    if (!links.length) return;
    const headings = Array.from(document.querySelectorAll(
        '.doc-content h1[id],h2[id],h3[id],h4[id]'
    ));
    function onScroll() {
        const scrollY = window.scrollY + 90;
        let active = null;
        for (const h of headings) {
            if (h.offsetTop <= scrollY) active = h.id;
        }
        links.forEach(l => {
            const href = l.getAttribute('href');
            l.classList.toggle('active', href === '#' + active);
        });
    }
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
})();

// Hamburger
(function() {
    const btn  = document.getElementById('nav-hamburger');
    const menu = document.getElementById('nav-mobile-menu');
    if (!btn || !menu) return;
    function toggle(open) {
        btn.classList.toggle('open', open);
        menu.classList.toggle('open', open);
        btn.setAttribute('aria-expanded', String(open));
        menu.setAttribute('aria-hidden', String(!open));
    }
    btn.addEventListener('click', () => toggle(!btn.classList.contains('open')));
    menu.querySelectorAll('.nav-mobile-link').forEach(l => l.addEventListener('click', () => toggle(false)));
    document.addEventListener('click', e => {
        if (btn.classList.contains('open') && !btn.contains(e.target) && !menu.contains(e.target))
            toggle(false);
    });
})();
'''

def build_toc_html(toc):
    items = []
    for entry in toc:
        slug, text, level = entry
        clean = re.sub(r'<[^>]+>', '', text)
        cls = f'toc-h{level}'
        items.append(f'<a href="#{slug}" class="doc-toc-link {cls}">{html.escape(clean)}</a>')
    return '\n'.join(items)

def page_template(title: str, body: str, toc_html: str, breadcrumb: str = '') -> str:
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} - IDEKA Documentation</title>
<meta name="description" content="IDEKA programming language documentation: {html.escape(title)}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,300..700;1,9..40,300..700&family=Space+Mono:ital,wght@0,400;0,700;1,400&family=Syne:wght@400..800&display=swap" rel="stylesheet">
<style>
:root {{
    --black:    #050608;
    --dark:     #080a0f;
    --panel:    #0b0e16;
    --border:   #0f1520;
    --border2:  #1a2235;
    --blue:     #00aaff;
    --blue-dim: #0066bb;
    --blue-glow:#00aaff44;
    --blue-soft:#00aaff12;
    --text:     #c8d4e8;
    --text-dim: #5a6880;
    --text-mute:#2a3445;
    --mono:     'Space Mono', monospace;
    --sans:     'DM Sans', sans-serif;
    --display:  'Syne', sans-serif;
}}
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
    background: var(--black);
    color: var(--text);
    font-family: var(--sans);
    font-size: 14px;
    line-height: 1.6;
    -webkit-font-smoothing: antialiased;
}}
a {{ color: var(--blue); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.container {{ max-width: 1200px; margin: 0 auto; padding: 0 40px; }}

/* Nav */
nav {{
    position: sticky;
    top: 0;
    z-index: 100;
    display: flex;
    align-items: center;
    height: 64px;
    padding: 0 40px;
    background: rgba(5,6,8,0.92);
    border-bottom: 1px solid var(--border);
    backdrop-filter: blur(12px);
    gap: 32px;
}}
.nav-logo {{
    display: flex;
    align-items: center;
    gap: 10px;
    text-decoration: none;
    flex-shrink: 0;
}}
.nav-logo-mark {{ width: 26px; height: 26px; }}
.nav-logo-text {{
    font-family: var(--mono);
    font-size: 14px;
    font-weight: 700;
    color: var(--blue);
    letter-spacing: 0.06em;
}}
.nav-links {{
    display: flex;
    list-style: none;
    gap: 28px;
}}
.nav-links a {{
    font-size: 13px;
    color: var(--text-dim);
    text-decoration: none;
    letter-spacing: 0.02em;
    transition: color 0.15s;
}}
.nav-links a:hover {{ color: var(--text); }}
.nav-spacer {{ flex: 1; }}
.nav-cta {{
    font-family: var(--mono);
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--blue);
    background: transparent;
    border: 1px solid var(--blue-dim);
    padding: 7px 16px;
    border-radius: 2px;
    text-decoration: none;
    transition: background 0.2s, box-shadow 0.2s;
}}
.nav-cta:hover {{
    background: var(--blue-soft);
    box-shadow: 0 0 20px var(--blue-glow);
    text-decoration: none;
}}
.nav-hamburger {{
    display: none;
    flex-direction: column;
    justify-content: center;
    gap: 5px;
    width: 36px; height: 36px;
    padding: 6px;
    background: none; border: none;
    cursor: pointer; flex-shrink: 0;
}}
.nav-hamburger span {{
    display: block; height: 1.5px;
    background: var(--text-dim); border-radius: 2px;
    transition: transform 0.25s ease, opacity 0.25s ease;
    transform-origin: center;
}}
.nav-hamburger.open span:nth-child(1) {{ transform: translateY(6.5px) rotate(45deg); background: var(--text); }}
.nav-hamburger.open span:nth-child(2) {{ opacity: 0; transform: scaleX(0); }}
.nav-hamburger.open span:nth-child(3) {{ transform: translateY(-6.5px) rotate(-45deg); background: var(--text); }}
.nav-mobile-menu {{
    display: none;
    flex-direction: column;
    position: fixed;
    top: 64px; left: 0; right: 0;
    background: rgba(5,6,8,0.97);
    backdrop-filter: blur(16px);
    border-bottom: 1px solid var(--border2);
    z-index: 99;
    transform: translateY(-8px); opacity: 0;
    pointer-events: none;
    transition: transform 0.22s ease, opacity 0.22s ease;
}}
.nav-mobile-menu.open {{ transform: translateY(0); opacity: 1; pointer-events: auto; }}
.nav-mobile-link {{
    display: flex; align-items: center;
    padding: 16px 24px; font-size: 13px; font-weight: 500;
    color: var(--text-dim); text-decoration: none;
    border-bottom: 1px solid var(--border);
    transition: color 0.15s, background 0.15s;
}}
.nav-mobile-link:last-child {{ border-bottom: none; }}
.nav-mobile-link:active {{ background: var(--panel); color: var(--text); }}
.nav-mobile-link.cta {{
    color: var(--blue); font-family: var(--mono);
    font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase;
}}

/* Footer */
footer {{
    border-top: 1px solid var(--border);
    padding: 28px 0;
    background: var(--dark);
}}
.footer-inner {{
    display: flex; align-items: center; gap: 20px;
    max-width: 1200px; margin: 0 auto; padding: 0 40px;
}}
.footer-logo {{ text-decoration: none; }}
.footer-sep {{
    width: 1px; height: 18px;
    background: var(--border2);
}}
.footer-copy {{ font-size: 12px; color: var(--text-mute); }}
.footer-links {{
    display: flex; gap: 20px; margin-left: auto;
}}
.footer-links a {{
    font-size: 12px; color: var(--text-mute);
    text-decoration: none; transition: color 0.15s;
}}
.footer-links a:hover {{ color: var(--text); }}

::-webkit-scrollbar {{ width: 5px; }}
::-webkit-scrollbar-track {{ background: var(--black); }}
::-webkit-scrollbar-thumb {{ background: var(--border2); border-radius: 2px; }}

@media (max-width: 900px) {{
    nav {{ padding: 0 20px; gap: 16px; }}
    .nav-links {{ display: none; }}
    .nav-hamburger {{ display: flex; }}
    .nav-mobile-menu {{ display: flex; }}
    .footer-inner {{ padding: 0 20px; flex-wrap: wrap; gap: 12px; }}
    .footer-sep {{ display: none; }}
    .footer-links {{ margin-left: 0; }}
}}

{DOC_CSS}
</style>
</head>
<body>

{NAV_HTML}

<div class="doc-layout">
  <aside class="doc-sidebar">
    <div class="doc-sidebar-title">On this page</div>
    {toc_html}
  </aside>
  <main class="doc-content">
    {body}
  </main>
</div>

{FOOTER_HTML}

<script>
{DOC_JS}
</script>
</body>
</html>'''

def index_template(cards_html: str) -> str:
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>IDEKA Documentation</title>
<meta name="description" content="Official documentation for the IDEKA programming language.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,300..700;1,9..40,300..700&family=Space+Mono:ital,wght@0,400;0,700;1,400&family=Syne:wght@400..800&display=swap" rel="stylesheet">
<style>
:root {{
    --black:#050608;--dark:#080a0f;--panel:#0b0e16;
    --border:#0f1520;--border2:#1a2235;
    --blue:#00aaff;--blue-dim:#0066bb;--blue-glow:#00aaff44;--blue-soft:#00aaff12;
    --text:#c8d4e8;--text-dim:#5a6880;--text-mute:#2a3445;
    --mono:'Space Mono',monospace;--sans:'DM Sans',sans-serif;--display:'Syne',sans-serif;
}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0;}}
body{{background:var(--black);color:var(--text);font-family:var(--sans);-webkit-font-smoothing:antialiased;}}
a{{color:var(--blue);text-decoration:none;}}
.container{{max-width:1100px;margin:0 auto;padding:0 40px;}}
nav{{position:sticky;top:0;z-index:100;display:flex;align-items:center;height:64px;
     padding:0 40px;background:rgba(5,6,8,0.92);border-bottom:1px solid var(--border);
     backdrop-filter:blur(12px);gap:32px;}}
.nav-logo{{display:flex;align-items:center;gap:10px;text-decoration:none;flex-shrink:0;}}
.nav-logo-mark{{width:26px;height:26px;}}
.nav-logo-text{{font-family:var(--mono);font-size:14px;font-weight:700;color:var(--blue);letter-spacing:.06em;}}
.nav-links{{display:flex;list-style:none;gap:28px;}}
.nav-links a{{font-size:13px;color:var(--text-dim);text-decoration:none;transition:color .15s;}}
.nav-links a:hover{{color:var(--text);}}
.nav-spacer{{flex:1;}}
.nav-cta{{font-family:var(--mono);font-size:11px;font-weight:700;letter-spacing:.12em;
           text-transform:uppercase;color:var(--blue);background:transparent;
           border:1px solid var(--blue-dim);padding:7px 16px;border-radius:2px;
           text-decoration:none;transition:background .2s,box-shadow .2s;}}
.nav-cta:hover{{background:var(--blue-soft);box-shadow:0 0 20px var(--blue-glow);}}
.nav-hamburger{{display:none;flex-direction:column;justify-content:center;gap:5px;
                width:36px;height:36px;padding:6px;background:none;border:none;cursor:pointer;}}
.nav-hamburger span{{display:block;height:1.5px;background:var(--text-dim);border-radius:2px;transition:transform .25s ease,opacity .25s ease;transform-origin:center;}}
.nav-hamburger.open span:nth-child(1){{transform:translateY(6.5px) rotate(45deg);background:var(--text);}}
.nav-hamburger.open span:nth-child(2){{opacity:0;transform:scaleX(0);}}
.nav-hamburger.open span:nth-child(3){{transform:translateY(-6.5px) rotate(-45deg);background:var(--text);}}
.nav-mobile-menu{{display:none;flex-direction:column;position:fixed;top:64px;left:0;right:0;
                  background:rgba(5,6,8,.97);backdrop-filter:blur(16px);
                  border-bottom:1px solid var(--border2);z-index:99;
                  transform:translateY(-8px);opacity:0;pointer-events:none;
                  transition:transform .22s ease,opacity .22s ease;}}
.nav-mobile-menu.open{{transform:translateY(0);opacity:1;pointer-events:auto;}}
.nav-mobile-link{{display:flex;align-items:center;padding:16px 24px;font-size:13px;font-weight:500;
                  color:var(--text-dim);text-decoration:none;border-bottom:1px solid var(--border);transition:color .15s,background .15s;}}
.nav-mobile-link:last-child{{border-bottom:none;}}
.nav-mobile-link.cta{{color:var(--blue);font-family:var(--mono);font-size:11px;letter-spacing:.1em;text-transform:uppercase;}}
footer{{border-top:1px solid var(--border);padding:28px 0;background:var(--dark);}}
.footer-inner{{display:flex;align-items:center;gap:20px;max-width:1100px;margin:0 auto;padding:0 40px;}}
.footer-sep{{width:1px;height:18px;background:var(--border2);}}
.footer-copy{{font-size:12px;color:var(--text-mute);}}
.footer-links{{display:flex;gap:20px;margin-left:auto;}}
.footer-links a{{font-size:12px;color:var(--text-mute);text-decoration:none;transition:color .15s;}}
.footer-links a:hover{{color:var(--text);}}
::-webkit-scrollbar{{width:5px;}}
::-webkit-scrollbar-track{{background:var(--black);}}
::-webkit-scrollbar-thumb{{background:var(--border2);border-radius:2px;}}
@media(max-width:900px){{
    nav{{padding:0 20px;gap:16px;}}
    .nav-links{{display:none;}}
    .nav-hamburger{{display:flex;}}
    .nav-mobile-menu{{display:flex;}}
    .container{{padding:0 20px;}}
    .footer-inner{{padding:0 20px;flex-wrap:wrap;gap:12px;}}
    .footer-sep{{display:none;}}
    .footer-links{{margin-left:0;}}
}}
.doc-index-hero{{padding:72px 0 48px;}}
.doc-index-label{{font-family:var(--mono);font-size:10px;letter-spacing:.18em;text-transform:uppercase;color:var(--blue);margin-bottom:16px;}}
.doc-index-title{{font-family:var(--display);font-size:clamp(32px,5vw,52px);font-weight:700;color:#fff;letter-spacing:-.02em;margin-bottom:16px;}}
.doc-index-desc{{font-size:15px;color:var(--text-dim);max-width:560px;line-height:1.7;}}
{DOC_CSS}
</style>
</head>
<body>
{NAV_HTML}

<div class="container">
  <div class="doc-index-hero">
    <div class="doc-index-label">Documentation</div>
    <h1 class="doc-index-title">IDEKA Reference</h1>
    <p class="doc-index-desc">Complete language specification, standard library reference, and guides for the IDEKA programming language.</p>
  </div>
  <div class="doc-index-grid">
    {cards_html}
  </div>
  <div style="height:80px;"></div>
</div>

{FOOTER_HTML}

<script>
(function() {{
    const btn  = document.getElementById('nav-hamburger');
    const menu = document.getElementById('nav-mobile-menu');
    if (!btn || !menu) return;
    function toggle(open) {{
        btn.classList.toggle('open', open);
        menu.classList.toggle('open', open);
        btn.setAttribute('aria-expanded', String(open));
        menu.setAttribute('aria-hidden', String(!open));
    }}
    btn.addEventListener('click', () => toggle(!btn.classList.contains('open')));
    menu.querySelectorAll('.nav-mobile-link').forEach(l => l.addEventListener('click', () => toggle(false)));
    document.addEventListener('click', e => {{
        if (btn.classList.contains('open') && !btn.contains(e.target) && !menu.contains(e.target))
            toggle(false);
    }});
}})();
</script>
</body>
</html>'''

# ---------------------------------------------------------------------------
# Doc metadata
# ---------------------------------------------------------------------------

DOC_META = {
    'language_specification': {
        'label': 'Language Reference',
        'desc': 'Complete specification of the IDEKA language: syntax, types, memory model, operators, templates, comptime, and more.',
    },
    'standard': {
        'label': 'Standard Library',
        'desc': 'The IDEKA standard library: I/O, string utilities, collections, math, and system interfaces.',
    },
}

def get_meta(stem: str) -> dict:
    for key, meta in DOC_META.items():
        if key in stem.lower():
            return meta
    return {
        'label': 'Documentation',
        'desc': f'IDEKA documentation: {stem.replace("_", " ").title()}.',
    }

def nice_title(stem: str) -> str:
    return stem.replace('_', ' ').replace('-', ' ').title()

# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

def generate_site(input_dir: str, output_dir: str):
    in_path = Path(input_dir)
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    md_files = sorted(in_path.glob('*.md'))
    if not md_files:
        print(f'No .md files found in {input_dir}')
        return

    cards = []

    for md_file in md_files:
        stem = md_file.stem
        title = nice_title(stem)
        meta = get_meta(stem)

        print(f'  Processing {md_file.name} ...')
        md_text = md_file.read_text(encoding='utf-8')
        body_raw, toc = md_to_html(md_text)
        body = apply_highlighting(body_raw)
        toc_html = build_toc_html(toc)

        out_file = out_path / f'{stem}.html'
        html_out = page_template(title, body, toc_html)
        out_file.write_text(html_out, encoding='utf-8')
        print(f'    -> {out_file}')

        # index card
        href = f'{stem}.html'
        cards.append(f'''<a href="{href}" class="doc-index-card">
  <div class="doc-index-card-label">{html.escape(meta["label"])}</div>
  <div class="doc-index-card-title">{html.escape(title)}</div>
  <p class="doc-p" style="font-size:13px;margin:0;">{html.escape(meta["desc"])}</p>
  <div class="doc-index-card-arrow">{html.escape(stem)}.html &rarr;</div>
</a>''')

    # write index
    index_html = index_template('\n'.join(cards))
    (out_path / 'index.html').write_text(index_html, encoding='utf-8')
    print(f'  -> {out_path / "index.html"}')
    print(f'\nDone. {len(md_files)} page(s) + index generated in {out_path}/')

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 3:
        print('Usage: python3 IDEKA_docgen.py <input_dir> <output_dir>')
        print('Example: python3 IDEKA_docgen.py ./docs ./site')
        sys.exit(1)
    input_dir = sys.argv[1]
    output_dir = sys.argv[2]
    if not os.path.isdir(input_dir):
        print(f'Error: input directory not found: {input_dir}')
        sys.exit(1)
    print(f'IDEKA Doc Generator')
    print(f'  Input:  {input_dir}')
    print(f'  Output: {output_dir}')
    generate_site(input_dir, output_dir)

if __name__ == '__main__':
    main()