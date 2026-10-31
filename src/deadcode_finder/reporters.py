"""Output formats: text (terminal), json, html, github (Actions annotations)."""

from __future__ import annotations

import html
import json
from collections import Counter
from datetime import datetime, timezone

from . import __version__
from .analyzer import Finding

_COLORS = {"red": "\033[31m", "yellow": "\033[33m", "dim": "\033[2m", "bold": "\033[1m", "reset": "\033[0m"}


def _c(text: str, color: str, enabled: bool) -> str:
    return f"{_COLORS[color]}{text}{_COLORS['reset']}" if enabled else text


def render_text(findings: list[Finding], files_scanned: int, color: bool = False) -> str:
    out = []
    for f in findings:
        loc = _c(f"{f.path}:{f.line}", "bold", color)
        kind = _c(f.kind, "red" if f.confidence >= 80 else "yellow", color)
        conf = _c(f"({f.confidence}% confidence)", "dim", color)
        fix = _c(" [fixable]", "dim", color) if f.fixable else ""
        out.append(f"{loc}: {kind} {f.message} {conf}{fix}")
    out.append("")
    if findings:
        counts = Counter(f.kind for f in findings)
        summary = ", ".join(f"{n} {k}" for k, n in counts.most_common())
        fixable = sum(f.fixable for f in findings)
        out.append(f"Found {len(findings)} issue(s) in {files_scanned} file(s): {summary}")
        if fixable:
            out.append(f"{fixable} can be removed automatically with --fix")
    else:
        out.append(_c(f"No dead code found in {files_scanned} file(s). Clean!", "bold", color))
    return "\n".join(out)


def render_json(findings: list[Finding], files_scanned: int) -> str:
    return json.dumps({
        "tool": "deadcode-finder",
        "version": __version__,
        "files_scanned": files_scanned,
        "total": len(findings),
        "by_kind": dict(Counter(f.kind for f in findings)),
        "findings": [f.to_dict() for f in findings],
    }, indent=2)


def render_github(findings: list[Finding]) -> str:
    """GitHub Actions workflow commands -> inline annotations on PRs."""
    lines = []
    for f in findings:
        level = "warning" if f.confidence >= 80 else "notice"
        msg = f.message.replace("%", "%25").replace("\n", "%0A")
        lines.append(f"::{level} file={f.path},line={f.line},endLine={f.end_line},"
                     f"title=deadcode-finder ({f.kind})::{msg} ({f.confidence}% confidence)")
    return "\n".join(lines)


def render_html(findings: list[Finding], files_scanned: int) -> str:
    counts = Counter(f.kind for f in findings)
    files = Counter(f.path for f in findings)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    esc = html.escape

    cards = "".join(
        f'<div class="card"><div class="num">{n}</div><div class="lbl">{esc(k)}</div></div>'
        for k, n in counts.most_common()
    ) or '<div class="card ok"><div class="num">0</div><div class="lbl">issues</div></div>'

    rows = "".join(
        f'<tr data-kind="{esc(f.kind)}"><td class="mono">{esc(f.path)}:{f.line}</td>'
        f'<td><span class="tag k-{esc(f.kind)}">{esc(f.kind)}</span></td>'
        f'<td>{esc(f.message)}</td>'
        f'<td><div class="bar"><span style="width:{f.confidence}%"></span></div>{f.confidence}%</td>'
        f'<td>{"yes" if f.fixable else ""}</td></tr>'
        for f in findings
    )
    options = "".join(f'<option value="{esc(k)}">{esc(k)} ({n})</option>' for k, n in counts.most_common())
    worst = "".join(f"<li><span class='mono'>{esc(p)}</span> <b>{n}</b></li>" for p, n in files.most_common(5))

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dead Code Report</title>
<style>
:root{{--bg:#f7f7f5;--fg:#1c1c1a;--muted:#6b6b66;--card:#fff;--line:#e4e4df;--accent:#c2410c;--ok:#15803d}}
@media (prefers-color-scheme:dark){{:root{{--bg:#141413;--fg:#ececea;--muted:#9a9a94;--card:#1e1e1c;--line:#2e2e2b;--accent:#fb923c;--ok:#4ade80}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:1100px;margin:0 auto;padding:32px 16px}}
h1{{margin:0 0 4px;font-size:26px}}.sub{{color:var(--muted);margin-bottom:24px}}
.cards{{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:24px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 18px;min-width:140px}}
.card .num{{font-size:28px;font-weight:700;color:var(--accent)}}.card.ok .num{{color:var(--ok)}}.card .lbl{{color:var(--muted);font-size:13px}}
.panel{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:20px;overflow-x:auto}}
table{{width:100%;border-collapse:collapse;font-size:14px}}th,td{{text-align:left;padding:8px;border-bottom:1px solid var(--line);vertical-align:top}}
th{{color:var(--muted);font-weight:600}}.mono{{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px;word-break:break-all}}
.tag{{font-size:12px;padding:2px 8px;border-radius:99px;border:1px solid var(--line);white-space:nowrap}}
.bar{{display:inline-block;width:50px;height:6px;background:var(--line);border-radius:3px;margin-right:6px;vertical-align:middle}}
.bar span{{display:block;height:100%;background:var(--accent);border-radius:3px}}
select{{font:inherit;padding:6px;border-radius:6px;border:1px solid var(--line);background:var(--card);color:var(--fg);margin-bottom:12px}}
ul{{margin:0;padding-left:18px}}
</style></head><body><main>
<h1>Dead Code Report</h1>
<div class="sub">{len(findings)} issue(s) across {files_scanned} scanned file(s) · generated {generated} · deadcode-finder {__version__}</div>
<div class="cards">{cards}</div>
{f'<div class="panel"><b>Files with most issues</b><ul>{worst}</ul></div>' if files else ''}
<div class="panel">
<select id="kind" aria-label="Filter by kind"><option value="">All kinds</option>{options}</select>
<table><thead><tr><th>Location</th><th>Kind</th><th>Message</th><th>Confidence</th><th>Auto-fix</th></tr></thead>
<tbody>{rows or '<tr><td colspan="5">No dead code found. Clean!</td></tr>'}</tbody></table>
</div></main>
<script>
document.getElementById('kind').addEventListener('change',e=>{{
  document.querySelectorAll('tbody tr[data-kind]').forEach(r=>{{r.style.display=!e.target.value||r.dataset.kind===e.target.value?'':'none'}});
}});
</script></body></html>"""
