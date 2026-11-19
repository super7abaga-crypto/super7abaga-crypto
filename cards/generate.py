"""
Self-rendered profile cards.

Every card on the profile README is an SVG drawn here from live GitHub data, then
committed back to the repo by .github/workflows/cards.yml. No third-party badge
services, no rate-limited widget hosts, no broken images when someone else's
free tier dies.

Cards
    header.svg         whoami block: uptime, repo/star/follower counts, focus, languages
    training_log.svg   the contribution year as a training run (loss = work still owed)
    scope.svg          daily contributions as an oscilloscope trace
    portscan.svg       repos as open/filtered/closed ports on host github.com
    registry.svg       repos as models in a registry (version=stars, params=disk)
    langs.svg          language mix by tracked bytes
    activity.svg       30-day sparkline and headline numbers
    heatmap.svg        the year, one cell per day

Usage
    python cards/generate.py                 # live fetch, write assets/cards/*.svg
    python cards/generate.py --offline       # reuse data/*.json (no network)
    python cards/generate.py --out some/dir
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

# ----------------------------------------------------------------------------
# identity — the only place personal strings live
# ----------------------------------------------------------------------------

USER = os.getenv("PROFILE_USER", "super7abaga-crypto")

# Rendered verbatim into the header card. Placeholders are intentional until
# they are replaced with real answers.
HANDLE = "@super7abaga-crypto"
ROLE = "developer · backend builder · problem solver"
FOCUS = "backend engineering · Python automation · AI engineering"
BUILDING = "deepfake detection system (final-year project)"

# ----------------------------------------------------------------------------
# palette — BIG7 ODDBYTE
# ----------------------------------------------------------------------------

BG = "#191B27"
PANEL = "#1F2230"
PANEL_ALT = "#232634"
STROKE = "#2F3340"
GRID = "#272B38"
ORANGE = "#FF7642"
CYAN = "#0FCCE9"
TEXT = "#C7D1DD"
BRIGHT = "#E9EDF5"
MUTED = "#7C879C"
GREEN = "#37D67A"
AMBER = "#FFC53D"
RED = "#FF5A5A"

MONO = ("ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,"
        "'Liberation Mono','Courier New',monospace")

W = 880  # every card shares this width so the README column lines up


# ----------------------------------------------------------------------------
# svg primitives
# ----------------------------------------------------------------------------

def esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def txt(x, y, s, size=12, fill=TEXT, weight="400", anchor="start",
        spacing=None, opacity=None):
    extra = f' letter-spacing="{spacing}"' if spacing else ""
    extra += f' opacity="{opacity}"' if opacity is not None else ""
    return (f'<text x="{x}" y="{y}" font-family="{MONO}" font-size="{size}" '
            f'fill="{fill}" font-weight="{weight}" text-anchor="{anchor}"{extra}>'
            f'{esc(s)}</text>')


def rect(x, y, w, h, fill=PANEL, stroke=None, rx=0, sw=1, opacity=None):
    s = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ""
    o = f' opacity="{opacity}"' if opacity is not None else ""
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
            f'fill="{fill}"{s}{o}/>')


def line(x1, y1, x2, y2, stroke=GRID, sw=1, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="{stroke}" stroke-width="{sw}"{d}/>')


def circle(cx, cy, r, fill="none", stroke=None, sw=1, opacity=None):
    s = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ""
    o = f' opacity="{opacity}"' if opacity is not None else ""
    return f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}"{s}{o}/>'


def frame(height: int, title: str, subtitle: str = "") -> list[str]:
    """Terminal window chrome: title bar, traffic lights, filename label."""
    out = [
        rect(0, 0, W, height, BG, rx=10),
        rect(0.5, 0.5, W - 1, height - 1, "none", STROKE, rx=10),
        rect(0, 0, W, 34, PANEL_ALT, rx=10),
        rect(0, 24, W, 10, PANEL_ALT),
        line(0, 34, W, 34, STROKE),
        circle(20, 17, 5, RED), circle(38, 17, 5, AMBER), circle(56, 17, 5, GREEN),
    ]
    if subtitle:
        out.append(txt(78, 21, subtitle, 11.5, MUTED))
    out.append(txt(W - 16, 21, title, 11.5, MUTED, anchor="end"))
    return out


def prompt(y: int, cmd: str) -> list[str]:
    """A shell prompt line: orange $, then the command in bright text."""
    return [
        txt(20, y, "$", 12.5, ORANGE, "700"),
        txt(36, y, cmd, 12.5, BRIGHT),
    ]


def write(path: Path, body: list[str], height: int) -> None:
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height}" '
           f'viewBox="0 0 {W} {height}" role="img">'
           f'<title>{esc(path.stem)}</title>' + "".join(body) + "</svg>")
    path.write_text(svg, encoding="utf-8")


# ----------------------------------------------------------------------------
# data
# ----------------------------------------------------------------------------

def _get(url: str, token: str | None = None):
    headers = {"User-Agent": "profile-card-generator", "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def fetch_live(token: str | None) -> dict:
    user = _get(f"https://api.github.com/users/{USER}", token)
    repos, page = [], 1
    while True:
        batch = _get(f"https://api.github.com/users/{USER}/repos"
                     f"?per_page=100&page={page}&sort=pushed", token)
        if not batch:
            break
        repos += batch
        if len(batch) < 100:
            break
        page += 1

    langs: dict[str, dict] = {}
    for r in repos:
        if r.get("fork"):
            continue
        try:
            langs[r["name"]] = _get(
                f"https://api.github.com/repos/{USER}/{r['name']}/languages", token)
        except Exception:
            langs[r["name"]] = {}

    # contribution calendar: the public contributions endpoint needs no auth.
    # Each cell <td> carries its own ISO date; the tooltip only carries a
    # month/day string, so the date must come from the cell, not the text.
    counts: dict[str, int] = {}
    calendar: list[str] = []
    try:
        req = urllib.request.Request(f"https://github.com/users/{USER}/contributions",
                                     headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "ignore")

        id2date: dict[str, str] = {}
        for tag in re.findall(r"<td[^>]*>", html):
            i = re.search(r'id="(contribution-day-component-[^"]+)"', tag)
            d = re.search(r'data-date="([0-9]{4}-[0-9]{2}-[0-9]{2})"', tag)
            if i and d:
                id2date[i.group(1)] = d.group(1)
                calendar.append(d.group(1))

        for m in re.finditer(r'for="(contribution-day-component-[^"]+)"[^>]*>([^<]*)<', html):
            cid, text = m.group(1), m.group(2).strip()
            day = id2date.get(cid)
            if not day:
                continue
            n = re.match(r"(\d+)\s+contribution", text)
            counts[day] = int(n.group(1)) if n else 0
    except Exception as exc:
        print(f"  ! contribution calendar unavailable: {exc}", file=sys.stderr)

    return {
        "user": {k: user.get(k) for k in
                 ("name", "created_at", "public_repos", "followers", "following", "bio")},
        "repos": [{
            "name": r["name"], "desc": r.get("description"), "lang": r.get("language"),
            "stars": r.get("stargazers_count", 0), "size_kb": r.get("size", 0),
            "pushed": r.get("pushed_at"), "created": r.get("created_at"),
            "fork": r.get("fork", False), "topics": r.get("topics") or [],
            "homepage": r.get("homepage"), "archived": r.get("archived", False),
        } for r in repos],
        "languages": langs,
        "contributions": {"counts": counts, "days": calendar},
    }


def load_offline(root: Path) -> dict:
    def j(name):
        p = root / "data" / name
        return json.loads(p.read_text()) if p.exists() else {}

    gh = j("github.json")
    langs = j("languages.json")
    contrib = j("contributions.json")
    counts = {k: int(v) for k, v in (contrib.get("counts") or {}).items()}
    return {"user": gh.get("user", {}), "repos": gh.get("repos", []),
            "languages": langs,
            "contributions": {"counts": counts, "days": contrib.get("levels", [])}}


# ----------------------------------------------------------------------------
# derived numbers
# ----------------------------------------------------------------------------

def parse_date(s):
    if not s:
        return None
    try:
        return dt.datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def months_since(d: dt.date | None) -> str:
    if not d:
        return "?"
    today = dt.date.today()
    m = (today.year - d.year) * 12 + (today.month - d.month)
    if today.day < d.day:
        m -= 1
    m = max(m, 0)
    return f"{m}m" if m < 12 else f"{m // 12}y {m % 12}m"


def daily_series(contrib: dict) -> list[tuple[dt.date, int]]:
    """Full 365-day series, zeros included, oldest first."""
    counts = contrib.get("counts") or {}
    parsed = {}
    for k, v in counts.items():
        d = parse_date(k) if re.match(r"\d{4}-\d{2}-\d{2}", str(k)) else None
        if d:
            parsed[d] = int(v)
    today = dt.date.today()
    start = today - dt.timedelta(days=364)
    return [(start + dt.timedelta(days=i), parsed.get(start + dt.timedelta(days=i), 0))
            for i in range(365)]


def stable_port(name: str) -> int:
    return 1024 + int(hashlib.sha256(name.encode()).hexdigest(), 16) % (65535 - 1024)


def state_for(pushed: dt.date | None) -> tuple[str, str]:
    """open if pushed in 30 days, filtered within 90, closed beyond."""
    if not pushed:
        return "closed", RED
    age = (dt.date.today() - pushed).days
    if age <= 30:
        return "open", GREEN
    if age <= 90:
        return "filtered", AMBER
    return "closed", RED


# ----------------------------------------------------------------------------
# cards
# ----------------------------------------------------------------------------

def card_header(d: dict) -> tuple[list[str], int]:
    u = d["user"]
    created = parse_date(u.get("created_at"))
    repos = [r for r in d["repos"] if not r["fork"]]
    stars = sum(r["stars"] for r in d["repos"])
    langs = top_languages(d, 8)

    h = 286
    out = frame(h, "header.svg", f"{USER} / README.md")
    out += prompt(62, f"ssh visitor@github auth ok")
    out += prompt(86, "./whoami --verbose")

    # identity panel
    out.append(rect(20, 102, W - 40, 74, PANEL, STROKE, rx=8))
    # shield glyph
    out.append(f'<path d="M46 118 l14 5 v12 c0 9 -7 15 -14 18 c-7 -3 -14 -9 -14 -18 v-12 z" '
               f'fill="none" stroke="{ORANGE}" stroke-width="1.6"/>')
    out.append(circle(46, 133, 3.2, ORANGE))
    out.append(rect(45.2, 135, 1.6, 6, ORANGE))

    out.append(txt(74, 122, "HOST", 9.5, MUTED, "700", spacing="1.4"))
    out.append(txt(74, 138, HANDLE, 13, BRIGHT, "700"))
    out.append(txt(74, 158, f"UPTIME  {months_since(created)} since "
                            f"{created.strftime('%b %Y') if created else '?'}", 10.5, MUTED))

    stats = [
        ("REPOS", f"{u.get('public_repos', len(d['repos']))} public"),
        ("STARS", str(stars)),
        ("FOLLOWERS", str(u.get("followers", 0))),
    ]
    sx = 400
    for i, (k, v) in enumerate(stats):
        x = sx + i * 150
        out.append(txt(x, 122, k, 9.5, MUTED, "700", spacing="1.4"))
        out.append(txt(x, 140, v, 13, CYAN, "700"))

    # role + focus
    out.append(txt(20, 200, "ROLE", 9.5, MUTED, "700", spacing="1.4"))
    out.append(txt(20, 218, ROLE, 12.5, BRIGHT))
    out.append(txt(20, 240, "FOCUS", 9.5, MUTED, "700", spacing="1.4"))
    out.append(txt(20, 258, FOCUS, 12.5, TEXT))

    # language tags, right side
    out.append(txt(W - 20, 200, "LANGUAGES", 9.5, MUTED, "700", anchor="end", spacing="1.4"))
    x = W - 20
    y = 216
    for name, pct in langs[:8]:
        label = f"{name} {pct:.0f}%"
        w = 8 + len(label) * 6.4
        if x - w < 430:
            x = W - 20
            y += 22
        x -= w
        out.append(rect(x, y, w, 17, PANEL_ALT, STROKE, rx=4))
        out.append(txt(x + w / 2, y + 12, label, 9.5, TEXT, anchor="middle"))
        x -= 6

    out.append(txt(20, h - 14, "read-only session · rendered from the live GitHub API · "
                                "no credentials stored", 9.5, MUTED))
    out.append(txt(W - 20, h - 14, dt.date.today().isoformat(), 9.5, MUTED, anchor="end"))
    return out, h


def top_languages(d: dict, n: int = 8) -> list[tuple[str, float]]:
    per_repo = d.get("languages") or {}
    totals: dict[str, int] = {}
    for name, langs in per_repo.items():
        for k, v in (langs or {}).items():
            totals[k] = totals.get(k, 0) + int(v)
    if not totals:
        return []
    grand = sum(totals.values())
    # a single vendored repo can swamp the mix; drop anything over half the bytes
    heavy = [n_ for n_, l in per_repo.items()
             if sum((l or {}).values()) > 0.5 * grand]
    if heavy:
        totals = {}
        for name, langs in per_repo.items():
            if name in heavy:
                continue
            for k, v in (langs or {}).items():
                totals[k] = totals.get(k, 0) + int(v)
        grand = sum(totals.values()) or 1
    return [(k, 100 * v / grand) for k, v in
            sorted(totals.items(), key=lambda x: -x[1])[:n]]


def card_training_log(d: dict) -> tuple[list[str], int]:
    series = daily_series(d["contributions"])
    total = sum(v for _, v in series)
    h = 318
    out = frame(h, "training_log.svg", "train_contributor.py")

    out += prompt(62, "./train_contributor.py --epochs 52")
    out.append(txt(20, 86, "the contribution year as a training run: loss is the share of "
                           "the year's work still owed", 10.5, MUTED))

    # plot area
    px, py, pw, ph = 56, 108, 500, 130
    out.append(rect(px, py, pw, ph, PANEL, STROKE, rx=6))
    for i in range(5):
        y = py + ph * i / 4
        out.append(line(px, y, px + pw, y, GRID, 1, "2 4"))
        out.append(txt(px - 8, y + 3.5, f"{1 - i * 0.25:.2f}", 9, MUTED, anchor="end"))

    # weekly cumulative owed
    weekly = []
    for w in range(52):
        chunk = series[w * 7:(w + 1) * 7]
        weekly.append(sum(v for _, v in chunk))
    cum, owed = 0, []
    for w in range(52):
        cum += weekly[w]
        owed.append(max(total - cum, 0) / total if total else 0)

    pts = []
    for i, val in enumerate(owed):
        x = px + pw * i / 51
        y = py + ph * val
        pts.append((x, y))
    path = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in pts)
    out.append(f'<path d="{path}" fill="none" stroke="{GREEN}" stroke-width="2"/>')
    out.append(f'<path d="{path} L {px + pw} {py + ph} L {px} {py + ph} Z" '
               f'fill="{GREEN}" opacity="0.08"/>')
    # final marker
    fx, fy = pts[-1]
    out.append(circle(fx, fy, 7, GREEN, opacity="0.18"))
    out.append(circle(fx, fy, 3.4, GREEN))

    for i in range(0, 52, 13):
        x = px + pw * i / 51
        out.append(txt(x, py + ph + 16, str(i + 1), 9, MUTED, anchor="middle"))
    out.append(txt(px + pw / 2, py + ph + 30, "week", 9, MUTED, anchor="middle"))
    out.append(txt(px - 40, py - 6, "loss", 9, MUTED))

    # stats column
    sx = px + pw + 28
    streak = 0
    for _, v in reversed(series):
        if v > 0:
            streak += 1
        else:
            break
    active = sum(1 for _, v in series if v > 0)
    best = max(series, key=lambda t: t[1])
    rows = [
        ("TRAINING LOG", "", MUTED),
        ("epoch", "52/52", BRIGHT),
        ("loss", f"{owed[-1]:.4f}", GREEN),
        ("val_loss(streak)", f"{streak}d", CYAN),
        ("optimizer", "streak", TEXT),
        ("checkpoint", "github.com/" + USER, TEXT),
        ("status", "converged" if owed[-1] == 0 else "resuming",
         GREEN if owed[-1] == 0 else AMBER),
    ]
    y = py + 6
    for k, v, c in rows:
        if k == "TRAINING LOG":
            out.append(txt(sx, y + 4, k, 9.5, MUTED, "700", spacing="1.4"))
        else:
            out.append(txt(sx, y + 4, k, 10, MUTED))
            out.append(txt(W - 24, y + 4, v, 10, c, anchor="end"))
        y += 17

    out.append(txt(20, h - 26, f"loss = share of the year's {total} contributions still owed "
                               f"— commits drive it to zero", 9.5, MUTED))
    out.append(txt(20, h - 12, f"{active} active days · best day {best[1]} on "
                               f"{best[0].isoformat()}", 9.5, MUTED))
    return out, h


def card_scope(d: dict) -> tuple[list[str], int]:
    series = daily_series(d["contributions"])
    h = 272
    out = frame(h, "scope.svg", "contributions.scope")
    out += prompt(62, "./scope --ch1 contributions --window 365d")

    px, py, pw, ph = 56, 96, W - 120, 92
    out.append(rect(px, py, pw, ph, PANEL, STROKE, rx=6))
    for i in range(1, 8):
        x = px + pw * i / 8
        out.append(line(x, py, x, py + ph, GRID, 1))
    for i in range(1, 4):
        y = py + ph * i / 4
        out.append(line(px, y, px + pw, y, GRID, 1))
    out.append(line(px, py + ph, px + pw, py + ph, MUTED, 1))

    peak = max((v for _, v in series), default=1) or 1
    pts = []
    for i, (_, v) in enumerate(series):
        x = px + pw * i / (len(series) - 1)
        y = py + ph - (ph * 0.92) * (v / peak)
        pts.append((x, y))
    path = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in pts)
    out.append(f'<path d="{path}" fill="none" stroke="{CYAN}" stroke-width="1.6"/>')

    total = sum(v for _, v in series)
    active = sum(1 for _, v in series if v > 0)
    stats = [
        ("samples", str(total)),
        ("peak", str(peak)),
        ("mean", f"{total / 365:.2f}/day"),
        ("duty cycle", f"{100 * active / 365:.0f}%"),
    ]
    sx = px
    y = py + ph + 26
    for k, v in stats:
        out.append(txt(sx, y, k, 9.5, MUTED))
        out.append(txt(sx, y + 15, v, 12, BRIGHT, "700"))
        sx += 130
    out.append(txt(W - 24, py + 18, "TRIG: RUN", 10, GREEN, "700", anchor="end"))
    out.append(txt(W - 24, py + 34, "CH1 · V/DIV 10 commits", 9, MUTED, anchor="end"))
    out.append(txt(20, h - 12, "one sample per day over the rolling 365-day window", 9.5, MUTED))
    return out, h


def card_portscan(d: dict) -> tuple[list[str], int]:
    repos = [r for r in d["repos"] if not r["fork"]]
    repos.sort(key=lambda r: (state_for(parse_date(r["pushed"]))[0] != "open",
                              r["name"].lower()))
    rows = repos[:22]
    h = 96 + len(rows) * 17 + 44
    out = frame(h, "portscan.svg", "nmap profile-scan")
    out += prompt(62, f"nmap -sV --profile github.com/{USER}")
    out.append(txt(20, 84, "PORT", 9.5, MUTED, "700", spacing="1.2"))
    out.append(txt(110, 84, "STATE", 9.5, MUTED, "700", spacing="1.2"))
    out.append(txt(200, 84, "SERVICE", 9.5, MUTED, "700", spacing="1.2"))
    out.append(txt(320, 84, "VERSION (repo, stars, size)", 9.5, MUTED, "700", spacing="1.2"))

    y = 104
    for r in rows:
        st, colour = state_for(parse_date(r["pushed"]))
        svc = (r["lang"] or "unknown").lower()
        size = r["size_kb"] / 1024
        size_s = f"{size:.1f} MB" if size >= 1 else f"{r['size_kb']} KB"
        out.append(txt(20, y, f"{stable_port(r['name'])}/tcp", 10.5, TEXT))
        out.append(txt(110, y, st, 10.5, colour, "700"))
        out.append(txt(200, y, svc, 10.5, TEXT))
        out.append(txt(320, y, f"{r['name']} ({r['stars']}*, {size_s})", 10.5, BRIGHT))
        y += 17

    out.append(txt(20, h - 24, "every repo is a service on this host — open if pushed in the "
                               "last 30 days, filtered within 90, closed beyond", 9.5, MUTED))
    out.append(txt(20, h - 10, "ports are stable hashes of the repo name", 9.5, MUTED))
    return out, h


def card_registry(d: dict) -> tuple[list[str], int]:
    repos = [r for r in d["repos"] if not r["fork"]]
    repos.sort(key=lambda r: (-r["stars"], r["name"].lower()))
    rows = repos[:22]
    h = 96 + len(rows) * 17 + 44
    out = frame(h, "registry.svg", "model registry")
    out += prompt(62, "./registry --list --format table")
    for label, x in (("MODEL", 20), ("VER", 300), ("STATUS", 366),
                     ("PARAMS", 470), ("LAST DEPLOY", 590), ("TRAIN LOSS", 720)):
        out.append(txt(x, 84, label, 9.5, MUTED, "700", spacing="1.2"))

    y = 104
    serving = 0
    for r in rows:
        pushed = parse_date(r["pushed"])
        age = (dt.date.today() - pushed).days if pushed else 999
        if age <= 30:
            status, colour = "serving", GREEN
            serving += 1
        elif age <= 90:
            status, colour = "canary", AMBER
        else:
            status, colour = "deprecated", RED
        size = r["size_kb"] / 1024
        out.append(txt(20, y, r["name"], 10.5, BRIGHT))
        out.append(txt(300, y, f"v{r['stars']}", 10.5, TEXT))
        out.append(txt(366, y, status, 10.5, colour, "700"))
        out.append(txt(470, y, f"{size:.1f} MB", 10.5, TEXT))
        out.append(txt(590, y, pushed.isoformat() if pushed else "—", 10.5, TEXT))
        out.append(txt(720, y, f"{age}d", 10.5, MUTED))
        y += 17

    out.append(txt(20, h - 24, f"{serving} serving · registry: github.com/{USER}", 9.5, MUTED))
    out.append(txt(20, h - 10, "version = stars · params = disk footprint · "
                               "train loss = days since last deploy", 9.5, MUTED))
    return out, h


def card_langs(d: dict) -> tuple[list[str], int]:
    langs = top_languages(d, 7)
    h = 74 + max(len(langs), 1) * 24 + 40
    out = frame(h, "langs.svg", "langs.mix")
    own = [r for r in d["repos"] if not r["fork"]]
    out += prompt(62, "./langs --rank --by bytes")

    y = 88
    bar_x, bar_w = 190, 520
    for name, pct in langs:
        out.append(txt(20, y + 9, name, 10.5, TEXT))
        w = max(bar_w * pct / 100, 1.5)
        out.append(rect(bar_x, y, bar_w, 11, PANEL_ALT, rx=3))
        out.append(rect(bar_x, y, w, 11, ORANGE if pct > 5 else CYAN, rx=3))
        out.append(txt(W - 24, y + 9, f"{pct:.1f}%", 10.5, BRIGHT, anchor="end"))
        y += 24

    out.append(txt(20, h - 22, f"{len(own)} repos · share of tracked bytes, ranked", 9.5, MUTED))
    out.append(txt(20, h - 8, "a single vendored repo over half the bytes is excluded so the "
                             "mix stays readable", 9.5, MUTED))
    return out, h


def card_activity(d: dict) -> tuple[list[str], int]:
    series = daily_series(d["contributions"])
    last30 = series[-30:]
    total = sum(v for _, v in series)
    h = 210
    out = frame(h, "activity.svg", "contributions.activity")
    out += prompt(62, "./activity --window 30d --headline")

    big = [(str(total), "in 365d"),
           (str(sum(v for _, v in last30)), "in 30d"),
           (str(sum(1 for _, v in series if v > 0)), "active days")]
    x = 20
    for val, label in big:
        out.append(txt(x, 118, val, 26, ORANGE, "700"))
        out.append(txt(x, 136, label, 10, MUTED))
        x += 160

    # 30-day sparkline
    px, py, pw, ph = 520, 92, 336, 58
    out.append(rect(px, py, pw, ph, PANEL, STROKE, rx=6))
    peak = max((v for _, v in last30), default=1) or 1
    pts = [(px + 8 + (pw - 16) * i / (len(last30) - 1),
            py + ph - 8 - (ph - 16) * v / peak) for i, (_, v) in enumerate(last30)]
    path = "M " + " L ".join(f"{a:.1f} {b:.1f}" for a, b in pts)
    out.append(f'<path d="{path}" fill="none" stroke="{CYAN}" stroke-width="1.5"/>')
    out.append(txt(px + 8, py - 6, "30-day sparkline", 9, MUTED))

    out.append(txt(20, h - 22, "commits, pull requests and issues counted together, "
                               "as GitHub reports them", 9.5, MUTED))
    out.append(txt(20, h - 8, f"generated {dt.date.today().isoformat()}", 9.5, MUTED))
    return out, h


def card_heatmap(d: dict) -> tuple[list[str], int]:
    series = daily_series(d["contributions"])
    # pad to start on Sunday
    pad = (series[0][0].weekday() + 1) % 7
    cells = [(None, 0)] * pad + series
    weeks = (len(cells) + 6) // 7
    cell, gap = 11, 3
    grid_w = weeks * (cell + gap)
    h = 92 + 7 * (cell + gap) + 46
    out = frame(h, "heatmap.svg", "contributions.heatmap")
    out += prompt(62, "./heatmap --year --legend")

    top = max((v for _, v in series), default=1) or 1
    active = [v for _, v in series if v > 0]
    bands = [0, 0, 0, 0]
    if active:
        q = sorted(active)
        for i, v in enumerate(q):
            pct = i / len(q)
            bands[min(int(pct * 4), 3)] = max(bands[min(int(pct * 4), 3)], v)

    def shade(v):
        if v == 0:
            return "#2A2E3B"
        if v <= bands[0] or bands[0] == 0:
            return "#4A3B33"
        if v <= bands[1]:
            return "#7A4B33"
        if v <= bands[2]:
            return "#C15F3A"
        return ORANGE

    x0, y0 = 20, 88
    for i, (day, v) in enumerate(cells):
        if day is None:
            continue
        wk, dow = divmod(i, 7)
        out.append(rect(x0 + wk * (cell + gap), y0 + dow * (cell + gap),
                        cell, cell, shade(v), rx=2))

    lx = x0 + grid_w + 20
    out.append(txt(lx, y0 + 12, "less", 9, MUTED))
    for i, v in enumerate([0] + bands):
        out.append(rect(lx + 30 + i * 16, y0 + 4, cell, cell, shade(v), rx=2))
    out.append(txt(lx, y0 + 34, "more", 9, MUTED))
    out.append(txt(lx + 30, y0 + 34, "→", 9, MUTED))

    out.append(txt(20, h - 22, "one cell per day; four shades are quartiles of active days, "
                               "not fractions of the busiest", 9.5, MUTED))
    out.append(txt(20, h - 8, f"busiest day {top} · generated "
                              f"{dt.date.today().isoformat()}", 9.5, MUTED))
    return out, h


CARDS = {
    "header": card_header,
    "training_log": card_training_log,
    "scope": card_scope,
    "portscan": card_portscan,
    "registry": card_registry,
    "langs": card_langs,
    "activity": card_activity,
    "heatmap": card_heatmap,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="assets/cards")
    ap.add_argument("--offline", action="store_true", help="reuse data/*.json")
    ap.add_argument("--only", nargs="*", help="subset of cards to render")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    outdir = Path(args.out)
    if not outdir.is_absolute():
        outdir = root / outdir
    outdir.mkdir(parents=True, exist_ok=True)

    if args.offline:
        data = load_offline(root)
        print("offline data:", len(data["repos"]), "repos")
    else:
        print(f"fetching live data for {USER} ...")
        data = fetch_live(os.getenv("GITHUB_TOKEN"))
        print(f"  {len(data['repos'])} repos, "
              f"{len(data['contributions'].get('counts') or {})} contribution days")

    wanted = args.only or list(CARDS)
    for name in wanted:
        body, height = CARDS[name](data)
        path = outdir / f"{name}.svg"
        write(path, body, height)
        try:
            shown = path.relative_to(root)
        except ValueError:
            shown = path
        print(f"  wrote {shown} ({height}px)")


if __name__ == "__main__":
    main()
