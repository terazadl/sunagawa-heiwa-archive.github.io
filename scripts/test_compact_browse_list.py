#!/usr/bin/env python3
"""
Test suite for SITES-23 (PRD SUNA-19):
Compact row list in browse mode, hide month headers, page height <= 18,000px,
card mode in search, hide Japanese language tags, and preserve back-to-top styling.
100% standard library Python — zero external dependencies.
"""

import os
import re
import sys
import shutil
import socket
import threading
import subprocess
import json
import urllib.request
import http.server
from html.parser import HTMLParser

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

def test_css_rules():
    """Verify required CSS rules in assets/style.css."""
    css_path = os.path.join(ROOT, "assets", "style.css")
    with open(css_path, "r", encoding="utf-8") as f:
        css = f.read()

    # 1. Month headers hidden in browse mode and shown in search mode (strict regex)
    assert re.search(r'\.month-section\s+h3\s*\{\s*display:\s*none;', css), \
        "CSS must hide .month-section h3 by default in browse mode"
    assert re.search(r'body\.has-search\s+\.month-section\s+h3\s*\{\s*display:\s*block;', css), \
        "CSS must restore .month-section h3 in search mode"

    # 2. Compact row styling for .entry (height <= 64px, single-line ellipsis, locked column)
    assert re.search(r'\.entry-list\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)', css), \
        "CSS must lock .entry-list column to minmax(0, 1fr) to prevent overflow blowout"
    assert re.search(r'\.entry\s*\{[^}]*max-height:\s*64px', css), \
        "CSS must specify max-height <= 64px for compact entries"
    assert re.search(r'\.entry-title\s*\{[^}]*text-overflow:\s*ellipsis', css), \
        "CSS must specify text-overflow: ellipsis for compact entry titles"
    assert re.search(r'\.entry-title\s*\{[^}]*white-space:\s*nowrap', css), \
        "CSS must specify white-space: nowrap for compact entry titles"

    # 3. Japanese language tag hidden
    assert re.search(r'\.entry\[data-language="ja"\]\s+\.entry-language\s*\{\s*display:\s*none;\s*\}', css), \
        "CSS must hide .entry-language for ja articles"

    # 4. Search card mode overrides
    assert "body.has-search .entry" in css, \
        "CSS must provide search mode overrides for entries"
    assert re.search(r'(?:body\.has-search\s+\.entry|\.search-results-list\s+\.entry)[^}]*max-height:\s*none', css), \
        "CSS must remove max-height limit in search mode"
    assert re.search(r'(?:body\.has-search\s+\.entry-title|\.search-results-list\s+\.entry-title)[^}]*white-space:\s*normal', css), \
        "CSS must restore normal wrapping in search mode"

    # 5. Desktop browse mode styling
    assert "@media (min-width:701px)" in css or "@media (min-width: 701px)" in css, \
        "CSS must include desktop media query"
    assert "body:not(.has-search) .entry" in css, \
        "CSS must format desktop browse mode entries as horizontal rows"

    # 6. Back-to-top button styling preservation (regression guard)
    assert re.search(r'\.back-to-top\s*\{[^}]*position:\s*fixed', css), \
        "CSS must maintain fixed positioning for .back-to-top"
    assert re.search(r'\.back-to-top\.is-visible\s*\{[^}]*visibility:\s*visible', css), \
        "CSS must make .back-to-top visible when .is-visible is added"

    print("PASS: CSS rules verified (including strict regex and back-to-top preservation)")

def test_archive_html_structure():
    """Verify HTML markup in archive.html."""
    html_path = os.path.join(ROOT, "archive.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Verify no double dots in entry metadata when ja language tag is hidden
    # Format should be <span class="entry-language"> · Japanese / 日本語</span>
    assert " · <span class=\"entry-language\">" not in html, \
        "Leading dot must be inside .entry-language to avoid doubled dots when hidden"
    assert "<span class=\"entry-language\"> · " in html, \
        "Separator dot should be inside .entry-language span"

    # Check total entries
    entry_count = html.count('class="entry"')
    assert entry_count == 208, f"Expected 208 entries, found {entry_count}"

    # Verify month sections exist in DOM for date order sorting
    month_h3_count = html.count('<section class="month-section"><h3>')
    assert month_h3_count == 75, f"Expected 75 month sections in DOM, found {month_h3_count}"

    # Verify body.classList.toggle('has-search', ...) in JS
    assert "document.body.classList.toggle('has-search'" in html, \
        "archive.html JS must toggle has-search class on body"

    # Verify back-to-top markup exists in HTML
    assert '<a class="back-to-top" href="#top">' in html, \
        "archive.html must include back-to-top link"

    print("PASS: archive.html structure verified")

def find_chrome_binary():
    """Find Chrome or Chromium binary."""
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("chrome"),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None

def start_temp_server():
    """Start an ephemeral HTTP server in ROOT if none running."""
    # First check if port 8000 is already serving archive.html
    try:
        with urllib.request.urlopen("http://localhost:8000/archive.html", timeout=1) as resp:
            if resp.status == 200:
                return 8000, None
    except Exception:
        pass

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=ROOT, **kwargs)
        def log_message(self, format, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return port, server

def test_live_browser_metrics():
    """Test live rendering in headless Chrome to rigorously verify AC 1-5."""
    chrome_bin = find_chrome_binary()
    assert chrome_bin is not None, "Chrome/Chromium is required to verify live browser metrics (AC 1-5)"

    port, server = start_temp_server()
    base_url = f"http://localhost:{port}"

    # Use an available remote debugging port
    with socket.socket() as s:
        s.bind(('', 0))
        debug_port = s.getsockname()[1]

    node_script = f"""
const {{ spawn }} = require('child_process');
async function run() {{
  const chrome = spawn('{chrome_bin}', [
    '--headless=new',
    '--disable-gpu',
    '--remote-debugging-port={debug_port}'
  ]);
  await new Promise(r => setTimeout(r, 1200));
  const res = await fetch('http://localhost:{debug_port}/json');
  const tabs = await res.json();
  const pageTab = tabs.find(t => t.type === 'page');
  const ws = new WebSocket(pageTab.webSocketDebuggerUrl);

  const send = (method, params = {{}}) => new Promise((resolve) => {{
    const id = Math.floor(Math.random() * 100000);
    const handler = (msg) => {{
      const data = JSON.parse(msg.data);
      if (data.id === id) {{
        ws.removeEventListener('message', handler);
        resolve(data.result);
      }}
    }};
    ws.addEventListener('message', handler);
    ws.send(JSON.stringify({{ id, method, params }}));
  }});

  ws.onopen = async () => {{
    // 1. Mobile browse mode
    await send('Emulation.setDeviceMetricsOverride', {{ width: 375, height: 812, deviceScaleFactor: 2, mobile: true }});
    await send('Page.navigate', {{ url: '{base_url}/archive.html' }});
    await new Promise(r => setTimeout(r, 800));

    const mobileBrowse = await send('Runtime.evaluate', {{
      returnByValue: true,
      expression: `(() => {{
        const entries = Array.from(document.querySelectorAll('.entry'));
        const heights = entries.map(e => e.getBoundingClientRect().height);
        const monthH3s = Array.from(document.querySelectorAll('.month-section h3'));
        const visibleMonthH3s = monthH3s.filter(h => window.getComputedStyle(h).display !== 'none');
        const jaEntries = Array.from(document.querySelectorAll('.entry[data-language="ja"]'));
        const jaLangVisible = jaEntries.filter(e => {{
          const l = e.querySelector('.entry-language');
          return l && window.getComputedStyle(l).display !== 'none';
        }});
        const nonJaEntries = Array.from(document.querySelectorAll('.entry:not([data-language="ja"])'));
        const nonJaLangVisible = nonJaEntries.filter(e => {{
          const l = e.querySelector('.entry-language');
          return l && window.getComputedStyle(l).display !== 'none';
        }});
        const sampleJaText = jaEntries[0].querySelector('.entry-meta').innerText;
        const hasDoubleDot = sampleJaText.includes('·  ·') || sampleJaText.includes('··');

        const btt = document.querySelector('.back-to-top');
        const bttStyle = btt ? window.getComputedStyle(btt) : null;

        return {{
          scrollHeight: document.documentElement.scrollHeight,
          totalEntries: entries.length,
          maxEntryHeight: Math.max(...heights),
          visibleMonthH3s: visibleMonthH3s.length,
          jaLangVisible: jaLangVisible.length,
          nonJaTotal: nonJaEntries.length,
          nonJaLangVisible: nonJaLangVisible.length,
          hasDoubleDot,
          bttPosition: bttStyle ? bttStyle.position : null,
          bttVisibility: bttStyle ? bttStyle.visibility : null
        }};
      }})()`
    }});

    // 2. Mobile search mode
    await send('Page.navigate', {{ url: '{base_url}/archive.html?q=伊達判決' }});
    await new Promise(r => setTimeout(r, 800));

    const mobileSearch = await send('Runtime.evaluate', {{
      returnByValue: true,
      expression: `(() => {{
        const entries = Array.from(document.querySelectorAll('.entry:not([hidden])'));
        const snippets = Array.from(document.querySelectorAll('.search-snippet'));
        return {{
          visibleEntries: entries.length,
          snippetsCount: snippets.length,
          firstEntryHeight: entries[0] ? entries[0].getBoundingClientRect().height : 0
        }};
      }})()`
    }});

    // 3. Desktop browse mode
    await send('Emulation.setDeviceMetricsOverride', {{ width: 1280, height: 800, deviceScaleFactor: 2, mobile: false }});
    await send('Page.navigate', {{ url: '{base_url}/archive.html' }});
    await new Promise(r => setTimeout(r, 800));

    const desktopBrowse = await send('Runtime.evaluate', {{
      returnByValue: true,
      expression: `(() => {{
        const firstEntry = document.querySelector('.entry');
        const style = window.getComputedStyle(firstEntry);
        const entries = Array.from(document.querySelectorAll('.entry'));
        const widths = entries.map(e => e.getBoundingClientRect().width);
        const minW = Math.min(...widths);
        const maxW = Math.max(...widths);
        return {{
          flexDirection: style.flexDirection,
          height: firstEntry.getBoundingClientRect().height,
          allWidthsEqual: minW === maxW,
          minEntryWidth: minW,
          maxEntryWidth: maxW
        }};
      }})()`
    }});

    // 4. Desktop search mode (regression guard against text overlap/collision)
    await send('Emulation.setDeviceMetricsOverride', {{ width: 1436, height: 818, deviceScaleFactor: 2, mobile: false }});
    await send('Page.navigate', {{ url: '{base_url}/archive.html?q=伊達判決&sort=relevance' }});
    await new Promise(r => setTimeout(r, 800));

    const desktopSearch = await send('Runtime.evaluate', {{
      returnByValue: true,
      expression: `(() => {{
        const searchInput = document.querySelector('#article-search');
        const yearNav = document.querySelector('.sticky-bar-main .year-nav');
        const statusText = document.querySelector('#filter-status-text');
        const stickyBar = document.querySelector('.sticky-bar');
        const filterStatus = document.querySelector('.filter-status');

        const sRect = searchInput.getBoundingClientRect();
        const yRect = yearNav.getBoundingClientRect();
        const tRect = statusText.getBoundingClientRect();

        // Check vertical separation: filter-status text must be below the sticky bar input
        const verticalClearance = tRect.top - sRect.bottom;
        // Check horizontal search bar integrity: input must not be crushed to 0
        const searchInputWidth = sRect.width;

        return {{
          verticalClearance,
          searchInputWidth,
          hasSearchClass: document.body.classList.contains('has-search')
        }};
      }})()`
    }});

    ws.close();
    chrome.kill();
    console.log(JSON.stringify({{
      mobileBrowse: mobileBrowse.result.value,
      mobileSearch: mobileSearch.result.value,
      desktopBrowse: desktopBrowse.result.value,
      desktopSearch: desktopSearch.result.value
    }}));
    process.exit(0);
  }};
}}
run().catch(e => {{ console.error(e); process.exit(1); }});
"""
    try:
        result = subprocess.run(["node", "-e", node_script], capture_output=True, text=True, check=True)
    finally:
        if server:
            server.shutdown()

    data = json.loads(result.stdout)

    mb = data["mobileBrowse"]
    assert mb["scrollHeight"] <= 18000, f"AC 3 failed: Mobile scroll height {mb['scrollHeight']} exceeds 18000px"
    assert mb["maxEntryHeight"] <= 64, f"AC 1 failed: Max entry height {mb['maxEntryHeight']} exceeds 64px"
    assert mb["visibleMonthH3s"] == 0, f"AC 2 failed: Expected 0 visible month headers, found {mb['visibleMonthH3s']}"
    assert mb["jaLangVisible"] == 0, f"AC 5 failed: Expected 0 visible ja tags, found {mb['jaLangVisible']}"
    assert mb["nonJaLangVisible"] == mb["nonJaTotal"], "AC 5 failed: All non-ja tags must be visible"
    assert not mb["hasDoubleDot"], "AC 5 failed: Found doubled dots in article meta line"
    assert mb["bttPosition"] == "fixed", f"Back-to-top button lost fixed position: {mb['bttPosition']}"
    assert mb["bttVisibility"] == "hidden", f"Back-to-top button should be hidden initially: {mb['bttVisibility']}"

    ms = data["mobileSearch"]
    assert ms["visibleEntries"] > 0, "AC 4 failed: Search results should be visible"
    assert ms["snippetsCount"] > 0, "AC 4 failed: Snippets should be present in search mode"
    assert ms["firstEntryHeight"] > 64, f"AC 4 failed: Search card height {ms['firstEntryHeight']} should expand beyond compact row 64px"

    db = data["desktopBrowse"]
    assert db["flexDirection"] == "row", f"Desktop flex-direction should be row, got {db['flexDirection']}"
    assert db["height"] <= 64, f"Desktop entry height {db['height']} exceeds 64px"
    assert db["allWidthsEqual"], f"All desktop entry widths must be equal (got min={db['minEntryWidth']}px, max={db['maxEntryWidth']}px)"
    assert db["maxEntryWidth"] <= 940, f"Desktop entry width {db['maxEntryWidth']}px exceeds container width 940px"

    ds = data["desktopSearch"]
    assert ds["hasSearchClass"], "Desktop search mode must have has-search class on body"
    assert ds["searchInputWidth"] >= 180, f"Search input crushed: width {ds['searchInputWidth']} < 180px"
    assert ds["verticalClearance"] >= 0, f"Search status text overlaps with sticky search bar: clearance {ds['verticalClearance']}px < 0"

    print("PASS: Live browser rendering metrics rigorously verified (AC 1-5, no skips, no collisions)")

if __name__ == "__main__":
    test_css_rules()
    test_archive_html_structure()
    test_live_browser_metrics()
    print("ALL TESTS PASSED")
