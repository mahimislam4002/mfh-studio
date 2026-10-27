#!/usr/bin/env python3
"""
Portfolio SaaS - User Dashboard + Update Center
Version: 0.1.0
"""

import os
import re
import json
import uuid
import shutil
import zipfile
import hashlib
from datetime import datetime
from pathlib import Path
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, send_from_directory
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

# ==================== CONFIG ====================
BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
USERS_DIR = DATA_DIR / "users"
PORTFOLIOS_DIR = DATA_DIR / "portfolios"
UPDATES_DIR = DATA_DIR / "updates"
BACKUPS_DIR = DATA_DIR / "backups"
UPLOADS_DIR = BASE_DIR / "uploads"
IMG_UPLOADS = UPLOADS_DIR / "img"
NOTIFICATIONS_DIR = DATA_DIR / "notifications"
CVS_DIR = DATA_DIR / "cvs"
COVER_DIR = DATA_DIR / "cover_letters"
MODULES_DIR = DATA_DIR / "modules"
PAYMENTS_DIR = DATA_DIR / "payments"
VERSION_FILE = DATA_DIR / "VERSION"
HISTORY_FILE = DATA_DIR / "version_history.json"
SITE_SETTINGS_FILE = DATA_DIR / "site_settings.json"
ENV_FILE = BASE_DIR / ".env"
PLATFORM_SECRETS_FILE = DATA_DIR / "platform_secrets.json"  # backup if .env write fails (Windows/OneDrive)
PLATFORM_AI_FILE = DATA_DIR / "platform_ai.json"  # PRIMARY store for AI keys (always writable)

app = Flask(__name__)

@app.template_filter("sb_time")
def sb_time_filter(val):
    """Format ISO timestamps for display."""
    if not val:
        return ""
    s = str(val).strip()
    try:
        if "T" in s:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00") if s.endswith("Z") else s)
        else:
            dt = datetime.strptime(s[:10], "%Y-%m-%d")
        return dt.strftime("%b %d, %Y · %I:%M %p").lstrip("0").replace(" 0", " ")
    except Exception:
        return s[:16]



app.secret_key = "portfolio-saas-secret-change-in-production-2026"
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB

# Ensure folders exist
for d in [USERS_DIR, PORTFOLIOS_DIR, UPDATES_DIR, BACKUPS_DIR, UPLOADS_DIR, IMG_UPLOADS, NOTIFICATIONS_DIR, PAYMENTS_DIR, CVS_DIR, COVER_DIR, MODULES_DIR]:
    d.mkdir(parents=True, exist_ok=True)

if not VERSION_FILE.exists():
    VERSION_FILE.write_text("0.1.0", encoding="utf-8")

if not HISTORY_FILE.exists():
    HISTORY_FILE.write_text(json.dumps([
        {
            "version": "0.1.0",
            "message": "Initial release - User Dashboard + Update Center",
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "type": "initial"
        }
    ], indent=2), encoding="utf-8")


# ==================== HELPERS ====================
def get_version():
    return VERSION_FILE.read_text().strip()


def get_history():
    try:
        return json.loads(HISTORY_FILE.read_text())
    except Exception:
        return []


def save_history(history):
    HISTORY_FILE.write_text(json.dumps(history, indent=2), encoding="utf-8")


def get_user(username):
    path = USERS_DIR / f"{username}.json"
    if path.exists():
        return json.loads(path.read_text())
    return None


def save_user(user):
    path = USERS_DIR / f"{user['username']}.json"
    path.write_text(json.dumps(user, indent=2), encoding="utf-8")


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            flash("Please log in", "warning")
            return redirect(url_for("login"))
        if not get_user(session["user"]):
            session.clear()
            flash("Session expired. Please log in again.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            flash("Please log in", "warning")
            return redirect(url_for("login"))
        user = get_user(session["user"])
        if not user or user.get("role") != "admin":
            flash("Admin access required", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


def create_backup(reason="manual"):
    version = get_version()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_id = f"backup-{timestamp}-{hashlib.md5(timestamp.encode()).hexdigest()[:8]}"
    backup_path = BACKUPS_DIR / backup_id
    backup_path.mkdir(parents=True, exist_ok=True)

    for folder in ["templates", "static"]:
        src = BASE_DIR / folder
        if src.exists():
            shutil.copytree(src, backup_path / folder, dirs_exist_ok=True)

    shutil.copy2(BASE_DIR / "app.py", backup_path / "app.py")
    shutil.copy2(VERSION_FILE, backup_path / "VERSION")

    meta = {
        "id": backup_id,
        "from_version": version,
        "reason": reason,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "files": 2
    }
    (backup_path / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return backup_id, meta


def list_backups():
    backups = []
    for item in sorted(BACKUPS_DIR.iterdir(), reverse=True):
        if item.is_dir():
            meta_path = item / "meta.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text())
                backups.append(meta)
            else:
                backups.append({
                    "id": item.name,
                    "from_version": "?",
                    "reason": "unknown",
                    "date": "",
                    "files": 0
                })
    return backups



# ==================== CONTEXT PROCESSOR ====================
@app.context_processor
def inject_globals():
    site = {}
    if SITE_SETTINGS_FILE.exists():
        try:
            site = json.loads(SITE_SETTINGS_FILE.read_text())
        except Exception:
            pass
    user_photo = None
    user_display_name = None
    user_portfolio_published = False
    if session.get("user"):
        u = get_user(session["user"])
        if u:
            user_photo = u.get("photo")
            user_display_name = u.get("full_name") or u.get("username")
            user_portfolio_published = u.get("portfolio_published", False)
    unread = 0
    if session.get("user"):
        try:
            unread = unread_count(session["user"])
        except Exception:
            unread = 0
    sidebar_modules = []
    if session.get("user"):
        try:
            u = get_user(session["user"])
            unlocked = user_unlocked_modules(u)
            all_m = get_modules(site)
            sidebar_modules = [m for m in all_m if m["id"] in unlocked and m.get("enabled", True)]
        except Exception:
            sidebar_modules = []
    return {
        "site_name": site.get("site_name", "Portfolio SaaS"),
        "site_logo": site.get("site_logo", ""),
        "user_photo": user_photo,
        "user_display_name": user_display_name,
        "user_portfolio_published": user_portfolio_published,
        "version": get_version(),
        "unread_notifications": unread,
        "sidebar_modules": sidebar_modules,
    }




# ==================== PRODUCTIVITY MODULES (18 categories) ====================
DEFAULT_MODULES = [
    # Final 9 — overlapping modules merged into these
    {"id": "ultimate-second-brain", "name": "Ultimate Second Brain", "price": 19.99,
     "desc": "Tasks, habits, goals, daily/weekly planner, notes, projects & personal life OS in one workspace", "icon": "🧠"},
    {"id": "content-creator-os", "name": "Content Creator OS", "price": 19.99,
     "desc": "Ideas → pipeline → calendar → library; YouTube & multi-platform content planner included", "icon": "🎬"},
    {"id": "freelance-agency-os", "name": "Freelance & Agency OS", "price": 22.99,
     "desc": "Clients, projects, retainers, delivery & weekly focus for freelancers and agencies", "icon": "💼"},
    {"id": "student-productivity", "name": "Student Productivity System", "price": 14.99,
     "desc": "Classes, assignments, exams, GPA, flashcards, attendance, goals & AI study assist", "icon": "🎓"},
    {"id": "digital-product-seller", "name": "Digital Product Seller", "price": 18.99,
     "desc": "Products, sales, customers & launches", "icon": "🛒"},
    {"id": "small-business-os", "name": "Small Business OS", "price": 21.99,
     "desc": "Operations, team tasks and ops dashboard for small business owners", "icon": "🏢"},
    {"id": "personal-finance-os", "name": "Personal Finance OS", "price": 18.99,
     "desc": "Budget, expenses, debt payoff, savings, profit-first buckets & investments", "icon": "💰"},
    {"id": "freelance-finance-invoice", "name": "Freelance Finance & Invoice", "price": 17.99,
     "desc": "Invoices, income tracking and freelance money", "icon": "🧾"},
    {"id": "creator-money-dashboard", "name": "Creator Money Dashboard", "price": 17.99,
     "desc": "Creator revenue streams, sponsorships and content income", "icon": "💵"},
]



# Old module ids → new (for users who unlocked removed products)
MODULE_ID_ALIASES = {
    "habit-goal-tracker": "ultimate-second-brain",
    "personal-life-os": "ultimate-second-brain",
    "minimalist-daily-planner": "ultimate-second-brain",
    "all-in-one-productivity": "ultimate-second-brain",
    "youtube-content-planner": "content-creator-os",
    "freelance-business-os": "freelance-agency-os",
    "agency-service-os": "freelance-agency-os",
    "debt-payoff-savings": "personal-finance-os",
    "profit-first-money": "personal-finance-os",
    "investment-portfolio-tracker": "personal-finance-os",
    "content-creator-money": "creator-money-dashboard",
}


def resolve_module_id(mid):
    return MODULE_ID_ALIASES.get(mid, mid)

def get_modules(site=None):
    if site is None:
        site = load_site_settings()
    custom = site.get("modules") or {}
    result = []
    for d in DEFAULT_MODULES:
        m = dict(d)
        c = custom.get(m["id"]) or {}
        if c.get("name"):
            m["name"] = c["name"]
        if c.get("desc"):
            m["desc"] = c["desc"]
        if c.get("icon"):
            m["icon"] = c["icon"]
        if c.get("image"):
            m["image"] = c["image"]
        if c.get("price") is not None:
            try:
                m["price"] = float(c["price"])
            except (TypeError, ValueError):
                pass
        if "enabled" in c:
            m["enabled"] = bool(c["enabled"])
        else:
            m["enabled"] = True
        result.append(m)
    return result


CORE_SERVICES = [
    {"id": "portfolio-builder", "name": "Portfolio Website", "price": 9.99, "desc": "Build and publish your portfolio site", "icon": "🌐", "kind": "core"},
    {"id": "resume-cv", "name": "Resume / CV Builder", "price": 7.99, "desc": "Create a professional resume", "icon": "📄", "kind": "core"},
    {"id": "cover-letter", "name": "Cover Letter Builder", "price": 5.99, "desc": "Write tailored cover letters", "icon": "✉", "kind": "core"},
]


def get_all_products(site=None):
    """Core services + productivity modules for landing catalog."""
    if site is None:
        site = load_site_settings()
    custom = site.get("modules") or {}
    products = []
    for d in CORE_SERVICES:
        m = dict(d)
        c = custom.get(m["id"]) or {}
        if c.get("name"):
            m["name"] = c["name"]
        if c.get("desc"):
            m["desc"] = c["desc"]
        if c.get("image"):
            m["image"] = c["image"]
        if c.get("price") is not None:
            try:
                m["price"] = float(c["price"])
            except (TypeError, ValueError):
                pass
        m["enabled"] = c.get("enabled", True) if "enabled" in c else True
        products.append(m)
    for m in get_modules(site):
        if m.get("enabled", True):
            mm = dict(m)
            mm["kind"] = "module"
            products.append(mm)
    return products


def get_full_access_price(site=None):
    if site is None:
        site = load_site_settings()
    try:
        return float(site.get("full_access_price", 99.99))
    except (TypeError, ValueError):
        return 99.99


def user_unlocked_modules(user):
    """Admin / lifetime / full_access = all modules. Else only unlocked_modules list."""
    if not user:
        return []
    role = (user.get("role") or "").lower()
    plan = (user.get("plan") or "").lower()
    if role == "admin" or plan in ("lifetime", "lifetime_free"):
        return [m["id"] for m in DEFAULT_MODULES]
    if user.get("full_access"):
        return [m["id"] for m in DEFAULT_MODULES]
    unlocked = user.get("unlocked_modules") or []
    if isinstance(unlocked, str):
        unlocked = [x.strip() for x in unlocked.split(",") if x.strip()]
    # Map legacy module ids → final 9
    resolved = []
    seen = set()
    for mid in unlocked:
        rid = resolve_module_id(mid)
        if rid not in seen:
            seen.add(rid)
            resolved.append(rid)
    return resolved


def user_has_core(user, core_id):
    """Core tools: free trial always has portfolio/resume/cover. Paid unlocks via unlocked_core."""
    if not user:
        return False
    if user.get("role") == "admin" or is_lifetime_user(user) or user.get("full_access"):
        return True
    plan = (user.get("plan") or "free").lower()
    if plan in ("free", "trial", ""):
        return core_id in ("portfolio-builder", "resume-cv", "cover-letter")
    core = user.get("unlocked_core") or []
    if core_id in core:
        return True
    # paid plans get core tools
    if plan in ("basic", "pro", "business"):
        return True
    return False

def user_has_module(user, module_id):
    return module_id in user_unlocked_modules(user)



# ==================== LIVE PORTFOLIO (site.js) ====================
LIVE_THEMES = {
    "gold_luxe": "Midnight Gold",
    "ocean_light": "Ocean Light",
    "violet_glass": "Neon Violet",
    "emerald_aurora": "Emerald Aurora",
    "modern_light": "Modern Light",
    "dark_neon": "Dark Neon",
    "pulse_dark": "Pulse Dark",
}

DEMO_SITE = {
    "profile": {
        "name": "Alex Robert",
        "role": "UI/UX Designer & Developer",
        "badge": "Available for new projects",
        "tagline": "I craft premium digital experiences that help brands grow and people love.",
        "photo": "/portfolio/demo/avatar.svg",
        "aboutImg": "/portfolio/demo/about.svg",
        "chip1": "Top Rated",
        "chip2": "Award Winner",
        "about": "I am a passionate designer and developer with 10+ years of experience. I turn ideas into beautiful, high-performing products for clients around the world.",
        "email": "hello@example.com",
        "phone": "+880 1700 000000",
        "location": "Dhaka, Bangladesh",
        "stats": [
            {"n": "10+", "l": "Years Experience"},
            {"n": "120+", "l": "Projects Done"},
            {"n": "98%", "l": "Happy Clients"},
        ],
    },
    "skills": [
        {"title": "UI/UX Design", "percent": 96, "desc": "Wireframes, prototypes and design systems in Figma.", "img": "/portfolio/demo/a1.svg"},
        {"title": "Web Development", "percent": 92, "desc": "HTML, CSS, JavaScript, React and Node.", "img": "/portfolio/demo/a2.svg"},
        {"title": "Branding", "percent": 86, "desc": "Logos and identity systems that stand out.", "img": "/portfolio/demo/a3.svg"},
    ],
    "services": [
        {"title": "UI/UX Design", "desc": "User-centred interfaces for web and mobile apps.", "img": "/portfolio/demo/a4.svg"},
        {"title": "Website Development", "desc": "Fast, responsive, pixel-perfect websites.", "img": "/portfolio/demo/a5.svg"},
        {"title": "Brand Identity", "desc": "Complete visual identity from logo to guidelines.", "img": "/portfolio/demo/a6.svg"},
    ],
    "projects": [
        {"title": "Fintech Dashboard", "desc": "Analytics dashboard for a finance startup.", "img": "/portfolio/demo/a2.svg"},
        {"title": "Travel Booking App", "desc": "Mobile app with 100k+ downloads.", "img": "/portfolio/demo/a3.svg"},
        {"title": "E-commerce Redesign", "desc": "Store redesign that doubled conversions.", "img": "/portfolio/demo/a5.svg"},
    ],
    "experience": [
        {"title": "Senior UI/UX Designer · Sift Media", "desc": "2022 – Present. Led design for 40+ products.", "img": "/portfolio/demo/a1.svg"},
        {"title": "Front-end Developer · Pixel Studio", "desc": "2019 – 2022. Built responsive web apps.", "img": "/portfolio/demo/a4.svg"},
        {"title": "Freelance Designer", "desc": "2015 – 2019. Worked with 100+ clients worldwide.", "img": "/portfolio/demo/a6.svg"},
    ],
}


def deep_copy_demo():
    return json.loads(json.dumps(DEMO_SITE))


def load_portfolio(username):
    path = PORTFOLIOS_DIR / f"{username}.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}
    return {}


def save_portfolio(username, data):
    PORTFOLIOS_DIR.mkdir(parents=True, exist_ok=True)
    (PORTFOLIOS_DIR / f"{username}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def seed_site_from_portfolio(portfolio):
    """Build site dict from portfolio fields + preserve existing site."""
    site = portfolio.get("site")
    if site and isinstance(site, dict) and site.get("profile"):
        return site
    site = deep_copy_demo()
    p = site["profile"]
    if portfolio.get("full_name"):
        p["name"] = portfolio["full_name"]
    if portfolio.get("role"):
        p["role"] = portfolio["role"]
    if portfolio.get("bio"):
        p["tagline"] = portfolio["bio"]
    if portfolio.get("about"):
        p["about"] = portfolio["about"]
    if portfolio.get("email"):
        p["email"] = portfolio["email"]
    if portfolio.get("phone"):
        p["phone"] = portfolio["phone"]
    if portfolio.get("location"):
        p["location"] = portfolio["location"]
    if portfolio.get("photo"):
        p["photo"] = portfolio["photo"]
    if portfolio.get("years_exp"):
        p["stats"][0] = {"n": str(portfolio["years_exp"]) + "+", "l": "Years Experience"}
    # skills as strings -> cards
    if portfolio.get("skills") and isinstance(portfolio["skills"], list):
        imgs = ["/portfolio/demo/a1.svg", "/portfolio/demo/a2.svg", "/portfolio/demo/a3.svg"]
        new_skills = []
        for i, s in enumerate(portfolio["skills"]):
            if isinstance(s, dict):
                new_skills.append(s)
            else:
                new_skills.append({
                    "title": str(s), "percent": 90 - i * 3,
                    "desc": "", "img": imgs[i % 3]
                })
        if new_skills:
            site["skills"] = new_skills
    if portfolio.get("projects"):
        site["projects"] = []
        for pr in portfolio["projects"]:
            site["projects"].append({
                "title": pr.get("title", ""),
                "desc": pr.get("description", pr.get("desc", "")),
                "img": pr.get("image") or pr.get("img") or "/portfolio/demo/a2.svg",
            })
    if portfolio.get("experience"):
        site["experience"] = []
        for ex in portfolio["experience"]:
            title = ex.get("title", "")
            if ex.get("company"):
                title = f"{title} · {ex['company']}"
            period = ex.get("period", "")
            desc = ex.get("description", ex.get("desc", ""))
            if period:
                desc = f"{period}. {desc}".strip()
            site["experience"].append({
                "title": title, "desc": desc,
                "img": ex.get("img") or "/portfolio/demo/a1.svg",
            })
    return site


def get_user_site(username):
    portfolio = load_portfolio(username)
    site = seed_site_from_portfolio(portfolio)
    theme = portfolio.get("template") or "gold_luxe"
    if theme not in LIVE_THEMES:
        theme = "gold_luxe"
    return portfolio, site, theme


def render_live_shell(site, theme, edit, save_url="", upload_url="", back_url="/portfolio/templates"):
    css = (BASE_DIR / "templates" / "live" / "site.css").read_text(encoding="utf-8")
    js = (BASE_DIR / "templates" / "live" / "site.js").read_text(encoding="utf-8")
    cfg = {
        "data": site,
        "theme": theme if theme in LIVE_THEMES else "gold_luxe",
        "edit": bool(edit),
        "saveUrl": save_url,
        "uploadUrl": upload_url,
        "backUrl": back_url,
    }
    name = (site.get("profile") or {}).get("name") or "Portfolio"
    # Escape name for title only
    safe_name = name.replace("<", "").replace(">", "").replace("&", "")
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{safe_name}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Playfair+Display:wght@600;800&family=Space+Grotesk:wght@500;700&display=swap" rel="stylesheet">
<style>{css}</style>
</head>
<body>
<div id="app"></div>
<script>window.CFG={json.dumps(cfg, ensure_ascii=False).replace('<', '\\\\u003c')};</script>
<script>{js}</script>
</body>
</html>"""
    return html




def load_site_settings():
    site = {}
    if SITE_SETTINGS_FILE.exists():
        try:
            site = json.loads(SITE_SETTINGS_FILE.read_text())
        except Exception:
            pass
    return site


# ==================== .ENV / PLATFORM AI BRAIN ====================
def _parse_env_file(path=None):
    """Parse KEY=VALUE lines from .env (no export of secrets to logs)."""
    path = path or ENV_FILE
    out = {}
    if not path.exists():
        return out
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k:
                out[k] = v
    except Exception:
        pass
    return out


def load_dotenv_into_environ():
    """Load .env into os.environ (does not override already-set process env)."""
    data = _parse_env_file()
    for k, v in data.items():
        if k and v is not None and k not in os.environ:
            os.environ[k] = v
    # Always prefer .env values for AI keys when present (admin UI is source of truth)
    for k in (
        "AI_BRAIN_PROVIDER", "OPENAI_API_KEY", "OPENAI_MODEL",
        "GEMINI_API_KEY", "GEMINI_MODEL",
        "ANTHROPIC_API_KEY", "CLAUDE_MODEL",
        "FLASK_SECRET_KEY",
    ):
        if k in data and data[k]:
            os.environ[k] = data[k]
    if data.get("FLASK_SECRET_KEY"):
        try:
            app.secret_key = data["FLASK_SECRET_KEY"]
        except Exception:
            pass


def write_env_keys(updates: dict):
    """
    Merge updates into .env file. Empty string values mean 'leave unchanged'
    unless the key is explicitly cleared with updates[key] is None.
    Also mirrors AI secrets into data/platform_secrets.json so Windows/OneDrive
    path issues cannot silently drop keys.
    """
    current = _parse_env_file()
    # merge backup secrets file
    try:
        if PLATFORM_SECRETS_FILE.exists():
            backup = json.loads(PLATFORM_SECRETS_FILE.read_text(encoding="utf-8"))
            if isinstance(backup, dict):
                for k, v in backup.items():
                    if k not in current and v:
                        current[k] = str(v)
    except Exception:
        pass
    for k, v in updates.items():
        if v is None:
            current.pop(k, None)
        elif isinstance(v, str) and v.strip() == "":
            continue
        else:
            current[k] = str(v).strip()
    lines = [
        "# MFH Studio — managed by Admin Site Settings. Do not commit real secrets.",
        "# Updated: " + datetime.now().isoformat(timespec="seconds"),
        "",
    ]
    preferred_order = [
        "FLASK_SECRET_KEY", "FLASK_DEBUG",
        "AI_BRAIN_PROVIDER",
        "OPENAI_API_KEY", "OPENAI_MODEL",
        "GEMINI_API_KEY", "GEMINI_MODEL",
        "ANTHROPIC_API_KEY", "CLAUDE_MODEL",
        "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "SMTP_FROM",
    ]
    written = set()
    for k in preferred_order:
        if k in current:
            lines.append(f"{k}={current[k]}")
            written.add(k)
    for k in sorted(current.keys()):
        if k not in written:
            lines.append(f"{k}={current[k]}")
    # Atomic-ish write for .env
    env_ok = False
    payload_text = chr(10).join(lines) + chr(10)
    try:
        tmp = ENV_FILE.with_suffix(".env.tmp")
        tmp.write_text(payload_text, encoding="utf-8")
        tmp.replace(ENV_FILE)
        env_ok = True
    except Exception as e1:
        try:
            ENV_FILE.write_text(payload_text, encoding="utf-8")
            env_ok = True
        except Exception as e2:
            print("ENV write failed:", e1, e2)
    # Always write JSON backup (DATA_DIR is usually writable)
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        secret_keys = {
            "AI_BRAIN_PROVIDER", "OPENAI_API_KEY", "OPENAI_MODEL",
            "GEMINI_API_KEY", "GEMINI_MODEL",
            "ANTHROPIC_API_KEY", "CLAUDE_MODEL",
        }
        payload = {k: current[k] for k in secret_keys if k in current and current[k]}
        PLATFORM_SECRETS_FILE.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:
        print("platform_secrets write failed:", e)
        if not env_ok:
            raise
    # Reflect into process env
    for k, v in current.items():
        if v is not None:
            os.environ[k] = str(v)
    if current.get("FLASK_SECRET_KEY"):
        try:
            app.secret_key = current["FLASK_SECRET_KEY"]
        except Exception:
            pass
    return current



def mask_secret(val: str, show=4):
    if not val:
        return ""
    s = str(val)
    if len(s) <= show:
        return "•" * len(s)
    return ("•" * max(8, len(s) - show)) + s[-show:]


def get_platform_ai_config():
    """Platform-level AI brain. PRIMARY: data/platform_ai.json, then platform_secrets.json, then .env."""
    env = {}
    # 1) Primary JSON (most reliable on Windows)
    try:
        if PLATFORM_AI_FILE.exists():
            raw = json.loads(PLATFORM_AI_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                env.update({k: str(v) for k, v in raw.items() if v is not None and str(v).strip()})
    except Exception as e:
        print("platform_ai.json read error:", e)
    # 2) Backup secrets
    try:
        if PLATFORM_SECRETS_FILE.exists():
            backup = json.loads(PLATFORM_SECRETS_FILE.read_text(encoding="utf-8"))
            if isinstance(backup, dict):
                for k, v in backup.items():
                    if v and not env.get(k):
                        env[k] = str(v)
    except Exception:
        pass
    # 3) .env
    try:
        file_env = _parse_env_file()
        for k, v in file_env.items():
            if v and not env.get(k):
                env[k] = v
    except Exception:
        pass
    # 4) process env last
    for k in ("AI_BRAIN_PROVIDER", "OPENAI_API_KEY", "OPENAI_MODEL", "GEMINI_API_KEY", "GEMINI_MODEL", "ANTHROPIC_API_KEY", "CLAUDE_MODEL"):
        if not env.get(k) and os.environ.get(k):
            env[k] = os.environ.get(k)

    provider = (env.get("AI_BRAIN_PROVIDER") or "gemini").strip().lower()
    if provider in ("chatgpt", "gpt", "gpt-4", "gpt4"):
        provider = "openai"
    if provider in ("anthropic",):
        provider = "claude"
    if provider in ("google",):
        provider = "gemini"
    if provider not in ("openai", "gemini", "claude"):
        provider = "gemini"

    keys = {
        "openai": (env.get("OPENAI_API_KEY") or "").strip(),
        "gemini": (env.get("GEMINI_API_KEY") or "").strip(),
        "claude": (env.get("ANTHROPIC_API_KEY") or "").strip(),
    }
    models = {
        "openai": (env.get("OPENAI_MODEL") or "gpt-4o-mini").strip() or "gpt-4o-mini",
        "gemini": (env.get("GEMINI_MODEL") or "gemini-2.0-flash").strip() or "gemini-2.0-flash",
        "claude": (env.get("CLAUDE_MODEL") or "claude-3-5-sonnet-latest").strip() or "claude-3-5-sonnet-latest",
    }
    api_key = (keys.get(provider) or "").strip()
    if not api_key:
        for p in ("gemini", "openai", "claude"):
            if keys.get(p):
                api_key = keys[p]
                break
    any_key = any(bool(v) for v in keys.values())
    return {
        "provider": provider,
        "api_key": api_key,
        "model": models.get(provider) or models["gemini"],
        "configured": bool(any_key),
        "keys_present": {k: bool(v) for k, v in keys.items()},
        "masked": {
            "openai": mask_secret(keys["openai"]),
            "gemini": mask_secret(keys["gemini"]),
            "claude": mask_secret(keys["claude"]),
        },
        "models": models,
    }


def resolve_ai_api_key(user_key: str = ""):
    """
    Prefer customer/user key from OS Settings; else platform brain key from admin .env.
    Returns (api_key, provider, model, source) where source is 'user' | 'platform' | ''.
    Always re-reads .env so Site Settings saves apply without full process restart.
    """
    try:
        load_dotenv_into_environ()
    except Exception:
        pass
    uk = (user_key or "").strip()
    if uk:
        model = os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"
        return uk, "openai", model, "user"
    cfg = get_platform_ai_config()
    if cfg.get("api_key"):
        return cfg["api_key"], cfg["provider"], cfg["model"], "platform"
    # Fallback: any key present in .env (prefer OpenAI for CV/Cover structuring)
    env = _parse_env_file()
    for env_key, prov, model_key, default_model in (
        ("OPENAI_API_KEY", "openai", "OPENAI_MODEL", "gpt-4o-mini"),
        ("GEMINI_API_KEY", "gemini", "GEMINI_MODEL", "gemini-2.0-flash"),
        ("ANTHROPIC_API_KEY", "claude", "CLAUDE_MODEL", "claude-3-5-sonnet-latest"),
    ):
        k = (env.get(env_key) or os.environ.get(env_key) or "").strip()
        if k:
            model = (env.get(model_key) or os.environ.get(model_key) or default_model).strip()
            return k, prov, model, "platform"
    return "", (cfg.get("provider") or "openai"), (cfg.get("model") or "gpt-4o-mini"), ""



def get_plans_list(site=None):
    if site is None:
        site = load_site_settings()
    plans = []
    for key, default_name, default_price in [
        ("plan_basic", "Basic", 9.99),
        ("plan_pro", "Pro", 19.99),
        ("plan_business", "Business", 39.99),
    ]:
        p = site.get(key) or {}
        try:
            price = float(p.get("price", default_price))
        except (TypeError, ValueError):
            price = default_price
        if price <= 0:
            continue
        features = p.get("features") or []
        if isinstance(features, str):
            features = [x.strip() for x in features.split("\n") if x.strip()]
        slug = "basic" if "basic" in key else ("pro" if "pro" in key else "business")
        plans.append({
            "key": key,
            "slug": slug,
            "name": p.get("name") or default_name,
            "price": price,
            "features": features,
            "featured": bool(p.get("featured")),
        })
    return plans



# ==================== PAYMENTS ====================
def _pay_path(name):
    PAYMENTS_DIR.mkdir(parents=True, exist_ok=True)
    return PAYMENTS_DIR / name


def load_received_txns():
    path = _pay_path("received_txns.json")
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def save_received_txns(items):
    _pay_path("received_txns.json").write_text(json.dumps(items, indent=2), encoding="utf-8")


def load_payment_requests():
    path = _pay_path("requests.json")
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def save_payment_requests(items):
    _pay_path("requests.json").write_text(json.dumps(items, indent=2), encoding="utf-8")


def normalize_txn(txn):
    return re.sub(r"\s+", "", (txn or "").strip().upper())


def find_received_txn(txn_id):
    nid = normalize_txn(txn_id)
    for item in load_received_txns():
        if normalize_txn(item.get("txn_id")) == nid and not item.get("used"):
            return item
    return None


def mark_txn_used(txn_id, username):
    items = load_received_txns()
    nid = normalize_txn(txn_id)
    for item in items:
        if normalize_txn(item.get("txn_id")) == nid and not item.get("used"):
            item["used"] = True
            item["used_by"] = username
            item["used_at"] = datetime.now().isoformat()
            save_received_txns(items)
            return True
    return False


def activate_user_plan(user, plan_slug, plan_name, price, method, txn_id):
    user["plan"] = plan_slug
    user["plan_name"] = plan_name
    user["plan_price"] = price
    user["plan_updated_at"] = datetime.now().isoformat()
    user["last_payment_method"] = method
    user["last_payment_txn"] = txn_id
    save_user(user)


def get_payment_config(site=None):
    if site is None:
        site = load_site_settings()
    return {
        "bkash_number": site.get("bkash_number", ""),
        "nagad_number": site.get("nagad_number", ""),
        "rocket_number": site.get("rocket_number", ""),
        "payoneer_email": site.get("payoneer_email", ""),
        "payoneer_link": site.get("payoneer_link", ""),
        "payment_note": site.get("payment_note", ""),
    }


def is_lifetime_user(user):
    if not user:
        return False
    if user.get("role") == "admin":
        return True
    plan = (user.get("plan") or "").lower()
    return plan in ("lifetime", "lifetime_free")


def ensure_admin_lifetime(user):
    """Master admin is always lifetime free."""
    if user and user.get("role") == "admin":
        if (user.get("plan") or "").lower() not in ("lifetime", "lifetime_free"):
            user["plan"] = "lifetime"
            user["plan_name"] = "Lifetime Free"
            save_user(user)
    return user


def trial_info(user):
    """Return (days_left or None, expired bool)."""
    if not user:
        return None, False
    if is_lifetime_user(user):
        return None, False
    site = load_site_settings()
    try:
        trial_days = int(site.get("trial_days", 7))
    except (TypeError, ValueError):
        trial_days = 7
    plan = (user.get("plan") or "free").lower()
    # Paid plans: no trial countdown
    if plan not in ("free", "", "trial"):
        return None, False
    created = user.get("created_at") or ""
    try:
        from datetime import datetime as _dt
        start = _dt.fromisoformat(created)
        elapsed = (_dt.now() - start).days
        left = max(0, trial_days - elapsed)
        return left, left <= 0 and trial_days > 0
    except Exception:
        return trial_days, False



def add_notification(to_username, title, body, ntype="info", from_user=None):
    """Append a notification for a user (or 'admin' broadcast to all admins)."""
    NOTIFICATIONS_DIR.mkdir(parents=True, exist_ok=True)
    targets = []
    if to_username == "__admins__":
        for f in USERS_DIR.glob("*.json"):
            try:
                u = json.loads(f.read_text())
                if u.get("role") == "admin":
                    targets.append(u["username"])
            except Exception:
                pass
    else:
        targets = [to_username]
    for uname in targets:
        path = NOTIFICATIONS_DIR / f"{uname}.json"
        items = []
        if path.exists():
            try:
                items = json.loads(path.read_text())
            except Exception:
                items = []
        items.insert(0, {
            "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
            "title": title,
            "body": body,
            "type": ntype,
            "from": from_user,
            "read": False,
            "created_at": datetime.now().isoformat(),
        })
        path.write_text(json.dumps(items[:100], indent=2), encoding="utf-8")


def get_notifications(username, limit=30):
    path = NOTIFICATIONS_DIR / f"{username}.json"
    if not path.exists():
        return []
    try:
        items = json.loads(path.read_text())
        return items[:limit]
    except Exception:
        return []


def unread_count(username):
    return sum(1 for n in get_notifications(username, 50) if not n.get("read"))


def count_referral_stats(username):
    """Total referred + paid referred (basic/pro/business only)."""
    total = 0
    paid = 0
    for f in USERS_DIR.glob("*.json"):
        try:
            u = json.loads(f.read_text())
        except Exception:
            continue
        if u.get("referred_by") != username:
            continue
        total += 1
        plan = (u.get("plan") or "free").lower()
        if plan in ("basic", "pro", "business"):
            paid += 1
    return total, paid


# ==================== AUTH ====================
@app.route("/")
def index():
    if session.get("user"):
        return redirect(url_for("dashboard"))
    site = load_site_settings()
    service_link = url_for("register")
    try:
        trial_days = int(site.get("trial_days", 7))
    except (TypeError, ValueError):
        trial_days = 7
    modules = [m for m in get_modules(site) if m.get("enabled", True)]
    products = get_all_products(site)
    return render_template(
        "landing.html",
        site_name=site.get("site_name", "Portfolio SaaS"),
        site_logo=site.get("site_logo", ""),
        tagline=site.get("tagline", ""),
        welcome_message=site.get("welcome_message", ""),
        support_email=site.get("support_email", ""),
        service_link=service_link,
        plans=get_plans_list(site),
        trial_days=trial_days,
        modules=modules,
        products=products,
        full_access_price=get_full_access_price(site),
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        full_name = request.form.get("full_name", "").strip()

        if not username or not password or not email:
            flash("Please fill in all fields", "danger")
            return render_template("register.html")

        if get_user(username):
            flash("This username is already taken", "danger")
            return render_template("register.html")

        photo = ""
        fphoto = request.files.get("photo_file")
        if fphoto and fphoto.filename:
            ext = Path(fphoto.filename).suffix.lower()
            if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
                folder = IMG_UPLOADS / username
                folder.mkdir(parents=True, exist_ok=True)
                fname = f"avatar_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}"
                fphoto.save(folder / fname)
                photo = f"/uploads/img/{username}/{fname}"
            else:
                flash("Invalid photo type", "danger")
                return redirect(url_for("register"))
        ref_code = request.form.get("referral_code", "").strip().upper()
        referred_by = None
        if ref_code:
            for f in USERS_DIR.glob("*.json"):
                u = json.loads(f.read_text())
                if u.get("referral_code") == ref_code:
                    referred_by = u["username"]
                    break

        user = {
            "username": username,
            "email": email,
            "full_name": full_name or username,
            "password": generate_password_hash(password),
            "photo": photo,
            "phone": request.form.get("phone", "").strip(),
            "role": "user",
            "created_at": datetime.now().isoformat(),
            "plan": "free",
            "referral_code": hashlib.md5(username.encode()).hexdigest()[:8].upper(),
            "referred_by": referred_by,
            "portfolio_published": False,
            "portfolio_slug": username
        }
        save_user(user)
        if referred_by:
            add_notification(
                referred_by,
                "New referral signup",
                f"{username} registered using your referral code.",
                "referral",
                from_user=username,
            )

        portfolio = {
            "username": username,
            "title": f"{full_name or username}'s Portfolio",
            "bio": "",
            "skills": [],
            "projects": [],
            "experience": [],
            "education": [],
            "social": {},
            "theme": "default",
            "published": False,
            "updated_at": datetime.now().isoformat()
        }
        (PORTFOLIOS_DIR / f"{username}.json").write_text(
            json.dumps(portfolio, indent=2)
        )

        # Auto login after register
        session["user"] = username
        session["role"] = "user"
        # Free trial defaults: core tools only (no OS modules until paid)
        if session.get("pending_cart") or session.get("pending_full_access") or session.get("pending_plan_key"):
            flash("Account created. Choose a payment method to continue.", "success")
            return redirect(url_for("payment_methods"))
        flash("Welcome! Your free trial includes Portfolio, Resume and Cover Letter.", "success")
        return redirect(url_for("dashboard"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")

        user = get_user(username)
        if user and check_password_hash(user["password"], password):
            session["user"] = username
            session["role"] = user.get("role", "user")

            flash(f"Welcome, {user.get('full_name', username)}!", "success")
            ensure_admin_lifetime(get_user(session["user"]))
            if session.get("pending_cart") or session.get("pending_full_access") or session.get("pending_plan_key"):
                return redirect(url_for("payment_methods"))
            return redirect(url_for("dashboard"))

        flash("Invalid username or password", "danger")
    # If already logged in, go dashboard (avoid login page with sidebar)
    if session.get("user") and get_user(session.get("user")):
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out", "info")
    return redirect(url_for("login"))


# ==================== USER DASHBOARD ====================
@app.route("/dashboard")
@login_required
def dashboard():
    username = session["user"]
    user = get_user(username)
    if not user:
        session.clear()
        flash("Account not found. Please log in again.", "warning")
        return redirect(url_for("login"))
    portfolio = load_portfolio(username)
    my_referrals = 0
    total_users = 0
    published_count = 0
    free_users = 0
    paid_users = 0
    trial_users = 0
    paid_subscribers = 0
    lifetime_users = 0
    referral_year_free = 0
    for f in USERS_DIR.glob("*.json"):
        try:
            u = json.loads(f.read_text())
        except Exception:
            continue
        total_users += 1
        if u.get("referred_by") == username:
            my_referrals += 1
        if u.get("portfolio_published") or load_portfolio(u.get("username") or f.stem).get("published"):
            published_count += 1
        plan = (u.get("plan") or "free").lower()
        role = u.get("role") or "user"
        if role == "admin" or plan in ("lifetime", "lifetime_free"):
            lifetime_users += 1
        elif plan in ("basic", "pro", "business"):
            paid_subscribers += 1
            paid_users += 1
        else:
            # free / trial
            free_users += 1
            # count as active trial if not expired
            days_left, expired = trial_info(u)
            if not expired:
                trial_users += 1
        if u.get("referral_reward") == "year_free" or u.get("plan_grant") == "year_free":
            referral_year_free += 1
    user = ensure_admin_lifetime(user)
    days_left, expired = trial_info(user)
    site = load_site_settings()
    ref_total, ref_paid = count_referral_stats(username)
    return render_template(
        "dashboard.html",
        user=user,
        portfolio=portfolio,
        version=get_version(),
        my_referrals=my_referrals,
        total_users=total_users,
        published_count=published_count,
        free_users=free_users,
        paid_users=paid_users,
        trial_users=trial_users,
        paid_subscribers=paid_subscribers,
        lifetime_users=lifetime_users,
        referral_year_free=referral_year_free,
        trial_days_left=days_left,
        trial_expired=expired,
        is_lifetime=is_lifetime_user(user),
        plans=get_plans_list(site),
        ref_total=ref_total,
        ref_paid=ref_paid,
        unread_notifications=unread_count(username),
    )


@app.route("/portfolio/edit", methods=["GET", "POST"])
@login_required
def portfolio_edit():
    username = session["user"]
    portfolio_path = PORTFOLIOS_DIR / f"{username}.json"

    if request.method == "POST":
        experience = []
        for line in request.form.get("experience_raw", "").strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 4:
                experience.append({
                    "title": parts[0], "company": parts[1], "period": parts[2],
                    "description": parts[3],
                    "proof_link": parts[4] if len(parts) > 4 else ""
                })
            elif len(parts) >= 3:
                experience.append({
                    "title": parts[0], "company": parts[1], "period": parts[2],
                    "description": "", "proof_link": ""
                })

        projects = []
        for line in request.form.get("projects_raw", "").strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 2:
                tags = [t.strip() for t in parts[2].split(",") if t.strip()] if len(parts) > 2 else []
                projects.append({
                    "title": parts[0],
                    "description": parts[1] if len(parts) > 1 else "",
                    "tags": tags,
                    "link": parts[3] if len(parts) > 3 else "",
                    "github": parts[4] if len(parts) > 4 else "",
                    "icon": "📁"
                })

        education = []
        for line in request.form.get("education_raw", "").strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 2:
                education.append({
                    "degree": parts[0], "school": parts[1],
                    "period": parts[2] if len(parts) > 2 else ""
                })

        do_publish = request.form.get("action") == "publish"
        was_published = False
        if portfolio_path.exists():
            was_published = json.loads(portfolio_path.read_text()).get("published", False)

        data = {
            "username": username,
            "template": request.form.get("template", "modern_light"),
            "photo": request.form.get("photo", "").strip(),
            "full_name": request.form.get("full_name", "").strip(),
            "role": request.form.get("role", "").strip(),
            "title": request.form.get("full_name", "").strip() + " Portfolio",
            "bio": request.form.get("bio", "").strip(),
            "about": request.form.get("about", "").strip(),
            "about_title": request.form.get("about_title", "").strip(),
            "years_exp": request.form.get("years_exp", "").strip(),
            "email": request.form.get("email", "").strip(),
            "phone": request.form.get("phone", "").strip(),
            "location": request.form.get("location", "").strip(),
            "website": request.form.get("website", "").strip(),
            "skills": [s.strip() for s in request.form.get("skills", "").split(",") if s.strip()],
            "experience": experience,
            "projects": projects,
            "education": education,
            "social": {
                "github": request.form.get("github", "").strip(),
                "linkedin": request.form.get("linkedin", "").strip(),
                "twitter": request.form.get("twitter", "").strip(),
                "website": request.form.get("social_website", "").strip() or request.form.get("website", "").strip(),
            },
            "published": True if do_publish else was_published,
            "updated_at": datetime.now().isoformat()
        }

        portfolio_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        if do_publish:
            user = get_user(username)
            user["portfolio_published"] = True
            save_user(user)
            flash(f"Portfolio saved & published! Link: /p/{username}", "success")
        else:
            flash("Portfolio saved successfully", "success")

        return redirect(url_for("dashboard"))

    portfolio = {"username": username}
    if portfolio_path.exists():
        portfolio = json.loads(portfolio_path.read_text())
    # Pre-select template from gallery query param
    tpl = request.args.get("template", "").strip()
    if tpl in ("pulse_dark", "modern_light", "dark_neon"):
        portfolio["template"] = tpl
    return render_template("portfolio_edit.html", portfolio=portfolio)


@app.route("/portfolio/publish", methods=["POST"])
@login_required
def portfolio_publish():
    username = session["user"]
    portfolio_path = PORTFOLIOS_DIR / f"{username}.json"
    if not portfolio_path.exists():
        flash("Please create your portfolio first", "warning")
        return redirect(url_for("portfolio_edit"))

    portfolio = json.loads(portfolio_path.read_text())
    portfolio["published"] = True
    portfolio["updated_at"] = datetime.now().isoformat()
    portfolio_path.write_text(json.dumps(portfolio, indent=2), encoding="utf-8")

    user = get_user(username)
    user["portfolio_published"] = True
    save_user(user)

    flash(f"Portfolio published! Link: /p/{username}", "success")
    return redirect(url_for("dashboard"))


@app.route("/portfolio/templates")
@login_required
def template_gallery():
    return render_template(
        "template_gallery.html",
        version=get_version(),
        themes=LIVE_THEMES,
    )


@app.route("/portfolio/demo/<path:filename>")
def portfolio_demo(filename):
    demo_dir = BASE_DIR / "templates" / "live" / "demo"
    return send_from_directory(demo_dir, filename)


@app.route("/uploads/img/<username>/<path:filename>")
def serve_user_img(username, filename):
    folder = IMG_UPLOADS / username
    return send_from_directory(folder, filename)


@app.route("/portfolio/view/<design>")
@login_required
def portfolio_view(design):
    if design not in LIVE_THEMES:
        design = "gold_luxe"
    _, site, _ = get_user_site(session["user"])
    return render_live_shell(site, design, edit=False)


@app.route("/portfolio/editor/<design>")
@login_required
def portfolio_editor(design):
    if design not in LIVE_THEMES:
        design = "gold_luxe"
    _, site, _ = get_user_site(session["user"])
    return render_live_shell(
        site, design, edit=True,
        save_url=url_for("portfolio_live_save", design=design),
        upload_url=url_for("portfolio_live_upload"),
        back_url=url_for("template_gallery"),
    )


@app.route("/portfolio/use/<design>", methods=["POST"])
@login_required
def portfolio_use(design):
    if design not in LIVE_THEMES:
        flash("Unknown design", "danger")
        return redirect(url_for("template_gallery"))
    username = session["user"]
    portfolio = load_portfolio(username)
    site = seed_site_from_portfolio(portfolio)
    portfolio["site"] = site
    portfolio["template"] = design
    portfolio["username"] = username
    if not portfolio.get("full_name"):
        portfolio["full_name"] = site["profile"].get("name", username)
    save_portfolio(username, portfolio)
    flash(f"Design set to {LIVE_THEMES[design]}. Open Edit Live to customize, then Publish.", "success")
    return redirect(url_for("template_gallery"))


@app.route("/portfolio/live-save/<design>", methods=["POST"])
@login_required
def portfolio_live_save(design):
    username = session["user"]
    try:
        payload = request.get_json(force=True, silent=True) or {}
    except Exception:
        payload = {}
    # site.js: { site: D, use: true|false }
    site = payload.get("site") if isinstance(payload, dict) else None
    if not site and isinstance(payload, dict) and "profile" in payload:
        site = payload
    if not site or not isinstance(site, dict):
        return jsonify({"ok": False, "error": "Invalid payload"}), 400
    use_design = bool(payload.get("use"))
    portfolio = load_portfolio(username)
    portfolio["site"] = site
    if use_design or design in LIVE_THEMES:
        portfolio["template"] = design if design in LIVE_THEMES else portfolio.get("template", "gold_luxe")
    portfolio["username"] = username
    # Mirror key fields for dashboard
    prof = site.get("profile") or {}
    portfolio["full_name"] = prof.get("name") or portfolio.get("full_name", username)
    portfolio["role"] = prof.get("role") or portfolio.get("role", "")
    portfolio["bio"] = prof.get("tagline") or portfolio.get("bio", "")
    portfolio["about"] = prof.get("about") or portfolio.get("about", "")
    portfolio["email"] = prof.get("email") or portfolio.get("email", "")
    portfolio["phone"] = prof.get("phone") or portfolio.get("phone", "")
    portfolio["location"] = prof.get("location") or portfolio.get("location", "")
    portfolio["photo"] = prof.get("photo") or portfolio.get("photo", "")
    portfolio["updated_at"] = datetime.now().isoformat()
    save_portfolio(username, portfolio)
    return jsonify({"ok": True})


@app.route("/portfolio/live-upload", methods=["POST"])
@login_required
def portfolio_live_upload():
    """site.js posts raw file body with header x-name."""
    username = session["user"]
    raw = request.get_data()
    name = request.headers.get("x-name") or "upload.png"
    if not raw:
        # fallback multipart
        f = None
        for key in request.files:
            f = request.files[key]
            break
        if f is None:
            return jsonify({"ok": False, "error": "No file"}), 400
        name = f.filename or name
        raw = f.read()
    ext = Path(name).suffix.lower() or ".png"
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"):
        return jsonify({"ok": False, "error": "Invalid type"}), 400
    folder = IMG_UPLOADS / username
    folder.mkdir(parents=True, exist_ok=True)
    fname = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(name)}"
    (folder / fname).write_bytes(raw)
    url = f"/uploads/img/{username}/{fname}"
    return jsonify({"ok": True, "url": url})


@app.route("/p/<slug>")
def public_portfolio(slug):
    portfolio = load_portfolio(slug)
    if not portfolio:
        return "Portfolio not found", 404
    if not portfolio.get("published"):
        return "This portfolio is not published yet", 403
    template_name = portfolio.get("template", "gold_luxe")
    if template_name in LIVE_THEMES:
        site = seed_site_from_portfolio(portfolio)
        return render_live_shell(site, template_name, edit=False)
    # Legacy HTML templates (fallback)
    if template_name == "pulse_dark":
        return render_template("public_pulse_dark.html", portfolio=portfolio)
    if template_name == "dark_neon":
        return render_template("public_dark_neon.html", portfolio=portfolio)
    return render_template("public_portfolio.html", portfolio=portfolio)


# ==================== UPDATE CENTER (Admin) ====================
@app.route("/admin/update-center")
@admin_required
def update_center():
    version = get_version()
    history = get_history()
    backups = list_backups()
    return render_template(
        "update_center.html",
        version=version,
        history=history,
        backups=backups
    )


@app.route("/admin/update-center/upload", methods=["POST"])
@admin_required
def update_upload():
    if "zipfile" not in request.files:
        flash("No file selected", "danger")
        return redirect(url_for("update_center"))

    file = request.files["zipfile"]
    if file.filename == "":
        flash("No file selected", "danger")
        return redirect(url_for("update_center"))

    if not file.filename.lower().endswith(".zip"):
        flash("Only ZIP files are allowed", "danger")
        return redirect(url_for("update_center"))

    filename = secure_filename(file.filename)
    zip_path = UPLOADS_DIR / filename
    file.save(zip_path)

    stage_dir = UPDATES_DIR / "staging"
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True)

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(stage_dir)

        version_in_zip = None
        for root, dirs, files in os.walk(stage_dir):
            if "VERSION" in files:
                version_in_zip = (Path(root) / "VERSION").read_text().strip()
                break

        if not version_in_zip:
            flash("VERSION file not found inside ZIP. Update cancelled.", "danger")
            shutil.rmtree(stage_dir)
            return redirect(url_for("update_center"))

        stage_info = {
            "filename": filename,
            "version": version_in_zip,
            "staged_at": datetime.now().isoformat(),
            "status": "staged"
        }
        (UPDATES_DIR / "stage_info.json").write_text(
            json.dumps(stage_info, indent=2)
        )

        flash(f"ZIP staged successfully (v{version_in_zip}). Now click Apply.", "success")
    except Exception as e:
        flash(f"Failed to extract ZIP: {e}", "danger")
        if stage_dir.exists():
            shutil.rmtree(stage_dir)

    return redirect(url_for("update_center"))


@app.route("/admin/update-center/apply", methods=["POST"])
@admin_required
def update_apply():
    stage_info_path = UPDATES_DIR / "stage_info.json"
    stage_dir = UPDATES_DIR / "staging"

    if not stage_info_path.exists() or not stage_dir.exists():
        flash("No staged update found", "warning")
        return redirect(url_for("update_center"))

    stage_info = json.loads(stage_info_path.read_text())
    new_version = stage_info["version"]
    old_version = get_version()

    backup_id, _ = create_backup(reason=f"before-update-to-{new_version}")

    try:
        # Prefer merging files into folders instead of deleting whole tree first
        # (safer on Windows / OneDrive if copy fails mid-way)
        for item in stage_dir.iterdir():
            dest = BASE_DIR / item.name
            if item.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
                for root, dirs, files in os.walk(item):
                    rel = Path(root).relative_to(item)
                    target_root = dest / rel
                    target_root.mkdir(parents=True, exist_ok=True)
                    for fn in files:
                        shutil.copy2(Path(root) / fn, target_root / fn)
            else:
                shutil.copy2(item, dest)

        # Validate critical templates exist after apply
        required = [
            BASE_DIR / "templates" / "dashboard.html",
            BASE_DIR / "templates" / "base.html",
            BASE_DIR / "templates" / "login.html",
            BASE_DIR / "app.py",
        ]
        missing = [str(p.name) for p in required if not p.exists()]
        if missing:
            raise RuntimeError(
                "Update incomplete — missing files: " + ", ".join(missing)
                + ". Rolling back."
            )

        VERSION_FILE.write_text(new_version)

        history = get_history()
        history.insert(0, {
            "version": new_version,
            "message": f"Applied via Update Center. Backup: {backup_id}",
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "type": "update",
            "from_version": old_version,
            "backup": backup_id
        })
        save_history(history)

        shutil.rmtree(stage_dir)
        stage_info_path.unlink(missing_ok=True)

        flash(f"Successfully updated: {old_version} → {new_version}. Restart the server.", "success")
    except Exception as e:
        # Auto rollback from the backup we just made
        try:
            bp = BACKUPS_DIR / backup_id
            for folder in ["templates", "static"]:
                src = bp / folder
                dest = BASE_DIR / folder
                if src.exists():
                    if dest.exists():
                        shutil.rmtree(dest)
                    shutil.copytree(src, dest)
            if (bp / "app.py").exists():
                shutil.copy2(bp / "app.py", BASE_DIR / "app.py")
            if (bp / "VERSION").exists():
                shutil.copy2(bp / "VERSION", VERSION_FILE)
            flash(f"Update failed and was rolled back: {e}", "danger")
        except Exception as e2:
            flash(f"Update failed: {e}. Rollback also failed: {e2}. Restore from backups manually.", "danger")

    return redirect(url_for("update_center"))


@app.route("/admin/update-center/rollback/<backup_id>", methods=["POST"])
@admin_required
def update_rollback(backup_id):
    backup_path = BACKUPS_DIR / backup_id
    if not backup_path.exists():
        flash("Backup not found", "danger")
        return redirect(url_for("update_center"))

    meta_path = backup_path / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    old_version = get_version()

    try:
        for folder in ["templates", "static"]:
            src = backup_path / folder
            dest = BASE_DIR / folder
            if src.exists():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(src, dest)

        if (backup_path / "app.py").exists():
            shutil.copy2(backup_path / "app.py", BASE_DIR / "app.py")

        if (backup_path / "VERSION").exists():
            shutil.copy2(backup_path / "VERSION", VERSION_FILE)

        new_version = get_version()

        history = get_history()
        history.insert(0, {
            "version": new_version,
            "message": f"Rollback from {old_version} using {backup_id}",
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "type": "rollback",
            "backup": backup_id
        })
        save_history(history)

        flash(f"Rollback successful: {old_version} → {new_version}", "success")
    except Exception as e:
        flash(f"Rollback failed: {e}", "danger")

    return redirect(url_for("update_center"))


# ==================== ADMIN USERS ====================
@app.route("/admin/users")
@admin_required
def admin_users():
    users = []
    for f in USERS_DIR.glob("*.json"):
        users.append(json.loads(f.read_text()))
    return render_template("admin_users.html", users=users, version=get_version())



# ==================== PROFILE / REFERRAL / SITE SETTINGS ====================
@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile_settings():
    username = session["user"]
    user = get_user(username)
    if request.method == "POST":
        user["full_name"] = request.form.get("full_name", "").strip() or user.get("full_name")
        user["email"] = request.form.get("email", "").strip() or user.get("email")
        user["phone"] = request.form.get("phone", "").strip()
        # Payout account for referral commission
        user["payout_method"] = request.form.get("payout_method", "").strip().lower()
        user["payout_account"] = request.form.get("payout_account", "").strip()
        user["payout_account_name"] = request.form.get("payout_account_name", "").strip()
        user["payout_bank_name"] = request.form.get("payout_bank_name", "").strip()
        user["payout_note"] = request.form.get("payout_note", "").strip()
        f = request.files.get("photo_file")
        if f and f.filename:
            ext = Path(f.filename).suffix.lower()
            if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
                folder = IMG_UPLOADS / username
                folder.mkdir(parents=True, exist_ok=True)
                fname = f"avatar_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}"
                f.save(folder / fname)
                user["photo"] = f"/uploads/img/{username}/{fname}"
            else:
                flash("Invalid image type", "danger")
                return redirect(url_for("profile_settings"))
        save_user(user)
        flash("Profile updated", "success")
        return redirect(url_for("profile_settings"))
    return render_template("profile.html", user=user)


@app.route("/referral")
@login_required
def referral_page():
    user = get_user(session["user"])
    referred = []
    for f in USERS_DIR.glob("*.json"):
        u = json.loads(f.read_text())
        if u.get("referred_by") == session["user"]:
            referred.append(u)
    ref_total, ref_paid = count_referral_stats(session["user"])
    return render_template(
        "referral.html",
        user=user,
        referred=referred,
        ref_total=ref_total,
        ref_paid=ref_paid,
    )


@app.route("/admin/site-settings/save-ai-key", methods=["POST"])
@admin_required
def save_platform_ai_key():
    """Save AI keys to data/platform_ai.json (PRIMARY). Also try .env."""
    provider = (request.form.get("ai_brain_provider") or "gemini").strip().lower()
    if provider not in ("openai", "gemini", "claude"):
        provider = "gemini"

    # Accept keys from dedicated fields OR single field "api_key"
    openai_key = (request.form.get("openai_api_key") or "").strip()
    gemini_key = (request.form.get("gemini_api_key") or request.form.get("api_key") or "").strip()
    claude_key = (request.form.get("anthropic_api_key") or "").strip()
    openai_key = openai_key.replace("﻿", "").replace("​", "").replace(" ", "").strip()
    gemini_key = gemini_key.replace("﻿", "").replace("​", "").replace(" ", "").strip()
    claude_key = claude_key.replace("﻿", "").replace("​", "").replace(" ", "").strip()

    def _ok(k):
        if not k or len(k) < 8:
            return False
        if k.startswith("•") or k.startswith("Saved:") or k.startswith("Paste "):
            return False
        return True

    # Load existing so we don't wipe other keys
    existing = {}
    try:
        if PLATFORM_AI_FILE.exists():
            existing = json.loads(PLATFORM_AI_FILE.read_text(encoding="utf-8")) or {}
    except Exception:
        existing = {}

    data = {
        "AI_BRAIN_PROVIDER": provider,
        "OPENAI_MODEL": (request.form.get("openai_model") or existing.get("OPENAI_MODEL") or "gpt-4o-mini").strip(),
        "GEMINI_MODEL": (request.form.get("gemini_model") or existing.get("GEMINI_MODEL") or "gemini-2.0-flash").strip(),
        "CLAUDE_MODEL": (request.form.get("claude_model") or existing.get("CLAUDE_MODEL") or "claude-3-5-sonnet-latest").strip(),
        "OPENAI_API_KEY": existing.get("OPENAI_API_KEY") or "",
        "GEMINI_API_KEY": existing.get("GEMINI_API_KEY") or "",
        "ANTHROPIC_API_KEY": existing.get("ANTHROPIC_API_KEY") or "",
    }
    received = []
    if _ok(openai_key):
        data["OPENAI_API_KEY"] = openai_key
        received.append(f"OpenAI({len(openai_key)})")
    if _ok(gemini_key):
        data["GEMINI_API_KEY"] = gemini_key
        received.append(f"Gemini({len(gemini_key)})")
    if _ok(claude_key):
        data["ANTHROPIC_API_KEY"] = claude_key
        received.append(f"Claude({len(claude_key)})")

    if request.form.get("clear_openai_key") == "1":
        data["OPENAI_API_KEY"] = ""
    if request.form.get("clear_gemini_key") == "1":
        data["GEMINI_API_KEY"] = ""
    if request.form.get("clear_claude_key") == "1":
        data["ANTHROPIC_API_KEY"] = ""

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        PLATFORM_AI_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        # mirror to secrets + env best-effort
        try:
            PLATFORM_SECRETS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        try:
            write_env_keys({k: (v if v else None) for k, v in data.items()})
        except Exception as e:
            print("env write optional fail:", e)
        for k, v in data.items():
            if v:
                os.environ[k] = str(v)
        (DATA_DIR / "ai_key_last_save.json").write_text(
            json.dumps({"ok": True, "at": datetime.now().isoformat(), "provider": provider, "received": received, "file": str(PLATFORM_AI_FILE)}, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        flash(f"Could not save AI key file: {e}", "danger")
        return redirect(url_for("site_settings"))

    cfg = get_platform_ai_config()
    if received:
        flash("AI key SAVED: " + ", ".join(received) + f" | provider={cfg.get('provider')} | configured={cfg.get('configured')}", "success")
    elif cfg.get("configured"):
        flash(f"Provider set to {provider}. Existing keys still present.", "success")
    else:
        flash("No key text received. Paste the FULL key into the Gemini box, then click Save AI Key again.", "warning")
    return redirect(url_for("site_settings"))



@app.route("/admin/site-settings/save-ai-key-ajax", methods=["POST"])
@admin_required
def save_platform_ai_key_ajax():
    """AJAX save — returns JSON so the browser can show exact result."""
    if request.is_json:
        payload = request.get_json(silent=True) or {}
    else:
        payload = request.form
    provider = (payload.get("ai_brain_provider") or "gemini")
    if hasattr(provider, "strip"):
        provider = provider.strip().lower()
    else:
        provider = "gemini"
    if provider not in ("openai", "gemini", "claude"):
        provider = "gemini"
    openai_key = (payload.get("openai_api_key") or "").strip()
    gemini_key = (payload.get("gemini_api_key") or payload.get("api_key") or "").strip()
    claude_key = (payload.get("anthropic_api_key") or "").strip()

    def _ok(k):
        return bool(k) and len(k) >= 8 and not k.startswith("Paste ") and not k.startswith("•")

    existing = {}
    try:
        if PLATFORM_AI_FILE.exists():
            existing = json.loads(PLATFORM_AI_FILE.read_text(encoding="utf-8")) or {}
    except Exception:
        existing = {}

    data = {
        "AI_BRAIN_PROVIDER": provider,
        "OPENAI_MODEL": (payload.get("openai_model") or existing.get("OPENAI_MODEL") or "gpt-4o-mini"),
        "GEMINI_MODEL": (payload.get("gemini_model") or existing.get("GEMINI_MODEL") or "gemini-2.0-flash"),
        "CLAUDE_MODEL": (payload.get("claude_model") or existing.get("CLAUDE_MODEL") or "claude-3-5-sonnet-latest"),
        "OPENAI_API_KEY": existing.get("OPENAI_API_KEY") or "",
        "GEMINI_API_KEY": existing.get("GEMINI_API_KEY") or "",
        "ANTHROPIC_API_KEY": existing.get("ANTHROPIC_API_KEY") or "",
    }
    received = []
    if _ok(openai_key):
        data["OPENAI_API_KEY"] = openai_key
        received.append({"which": "openai", "len": len(openai_key)})
    if _ok(gemini_key):
        data["GEMINI_API_KEY"] = gemini_key
        received.append({"which": "gemini", "len": len(gemini_key)})
    if _ok(claude_key):
        data["ANTHROPIC_API_KEY"] = claude_key
        received.append({"which": "claude", "len": len(claude_key)})

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    abs_path = str(PLATFORM_AI_FILE.resolve())
    try:
        PLATFORM_AI_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        for k, v in data.items():
            if v:
                os.environ[str(k)] = str(v)
        cfg = get_platform_ai_config()
        return jsonify({
            "ok": True,
            "received": received,
            "path": abs_path,
            "exists": PLATFORM_AI_FILE.exists(),
            "configured": cfg.get("configured"),
            "keys_present": cfg.get("keys_present"),
            "provider": cfg.get("provider"),
            "message": "Saved" if received else "No key text in request — paste key into the box first",
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "path": abs_path}), 500



@app.route("/admin/site-settings", methods=["GET", "POST"])
@admin_required
def site_settings():
    site = {}
    if SITE_SETTINGS_FILE.exists():
        try:
            site = json.loads(SITE_SETTINGS_FILE.read_text())
        except Exception:
            pass
    if request.method == "POST":
        site["site_name"] = request.form.get("site_name", "Portfolio SaaS").strip()
        site["tagline"] = request.form.get("tagline", "").strip()
        site["support_email"] = request.form.get("support_email", "").strip()
        site["welcome_message"] = request.form.get("welcome_message", "").strip()
        site["bkash_number"] = request.form.get("bkash_number", "").strip()
        site["nagad_number"] = request.form.get("nagad_number", "").strip()
        site["rocket_number"] = request.form.get("rocket_number", "").strip()
        site["payoneer_email"] = request.form.get("payoneer_email", "").strip()
        site["payoneer_link"] = request.form.get("payoneer_link", "").strip()
        site["payment_note"] = request.form.get("payment_note", "").strip()
        try:
            site["trial_days"] = int(request.form.get("trial_days") or 7)
        except ValueError:
            site["trial_days"] = 7
        for key in ("plan_basic", "plan_pro", "plan_business"):
            feats = request.form.get(f"{key}_features", "")
            features = [x.strip() for x in feats.splitlines() if x.strip()]
            try:
                price = float(request.form.get(f"{key}_price") or 0)
            except ValueError:
                price = 0
            site[key] = {
                "name": request.form.get(f"{key}_name", "").strip(),
                "price": price,
                "features": features,
                "featured": request.form.get(f"{key}_featured") == "1",
            }
        f = request.files.get("logo_file")
        if f and f.filename:
            ext = Path(f.filename).suffix.lower()
            if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"):
                folder = IMG_UPLOADS / "_site"
                folder.mkdir(parents=True, exist_ok=True)
                fname = f"logo_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}"
                f.save(folder / fname)
                site["site_logo"] = f"/uploads/img/_site/{fname}"
            else:
                flash("Invalid logo file type", "danger")
                return redirect(url_for("site_settings"))
        
        # Module / product catalog edits
        mods = site.get("modules") or {}
        for d in list(DEFAULT_MODULES) + list(CORE_SERVICES):
            mid = d["id"]
            if request.form.get(f"module_name_{mid}") is not None:
                entry = mods.get(mid) or {}
                entry["name"] = request.form.get(f"module_name_{mid}", "").strip() or d["name"]
                entry["desc"] = request.form.get(f"module_desc_{mid}", "").strip() or d.get("desc", "")
                try:
                    entry["price"] = float(request.form.get(f"module_price_{mid}") or d.get("price") or 0)
                except ValueError:
                    entry["price"] = d.get("price", 0)
                entry["enabled"] = request.form.get(f"module_enabled_{mid}") == "1"
                f = request.files.get(f"module_image_{mid}")
                if f and f.filename:
                    ext = Path(f.filename).suffix.lower()
                    if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
                        folder = IMG_UPLOADS / "_modules"
                        folder.mkdir(parents=True, exist_ok=True)
                        fname = f"{mid}_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}"
                        f.save(folder / fname)
                        entry["image"] = f"/uploads/img/_modules/{fname}"
                mods[mid] = entry
        site["modules"] = mods

        # —— Platform AI Brain → .env (admin only; never store raw keys in site_settings.json) ——
        provider = (request.form.get("ai_brain_provider") or "openai").strip().lower()
        if provider not in ("openai", "gemini", "claude"):
            provider = "openai"
        env_updates = {
            "AI_BRAIN_PROVIDER": provider,
            "OPENAI_MODEL": (request.form.get("openai_model") or "").strip() or "gpt-4o-mini",
            "GEMINI_MODEL": (request.form.get("gemini_model") or "").strip() or "gemini-2.0-flash",
            "CLAUDE_MODEL": (request.form.get("claude_model") or "").strip() or "claude-3-5-sonnet-latest",
        }
        # Only overwrite keys when admin typed a new value (non-empty)
        keys_received = []
        for form_key, env_key in (
            ("openai_api_key", "OPENAI_API_KEY"),
            ("gemini_api_key", "GEMINI_API_KEY"),
            ("anthropic_api_key", "ANTHROPIC_API_KEY"),
        ):
            raw = (request.form.get(form_key) or request.values.get(form_key) or "").strip()
            # strip zero-width / BOM that paste sometimes adds
            raw = raw.replace("﻿", "").replace("​", "").strip()
            if raw and not raw.startswith("•") and raw not in ("sk-...", "AIza...", "sk-ant-..."):
                env_updates[env_key] = raw
                keys_received.append(f"{env_key}({len(raw)} chars)")
        # Optional: clear a key if checkbox set
        if request.form.get("clear_openai_key") == "1":
            env_updates["OPENAI_API_KEY"] = None
        if request.form.get("clear_gemini_key") == "1":
            env_updates["GEMINI_API_KEY"] = None
        if request.form.get("clear_claude_key") == "1":
            env_updates["ANTHROPIC_API_KEY"] = None
        try:
            write_env_keys(env_updates)
            site["ai_brain_provider"] = provider  # non-secret preference only
        except Exception as e:
            flash(f"Site settings saved, but .env write failed: {e}", "danger")
            SITE_SETTINGS_FILE.write_text(json.dumps(site, indent=2), encoding="utf-8")
            return redirect(url_for("site_settings"))

        SITE_SETTINGS_FILE.write_text(json.dumps(site, indent=2), encoding="utf-8")
        cfg_check = get_platform_ai_config()
        if keys_received:
            flash(
                "Site settings saved. Received: " + ", ".join(keys_received) + ". "
                f"Platform AI Brain active ({cfg_check.get('provider')}).",
                "success",
            )
        elif cfg_check.get("configured"):
            flash(
                f"Site settings saved. Existing platform key kept. Brain active ({cfg_check.get('provider')}).",
                "success",
            )
        else:
            flash(
                "Site settings saved, but no API key was received from the form. "
                "Scroll to Platform AI Brain, click the API key box, paste your full key (sk-...), "
                "then click Save Settings again.",
                "warning",
            )
        return redirect(url_for("site_settings"))
    ai_cfg = get_platform_ai_config()
    ai_file_exists = PLATFORM_AI_FILE.exists()
    ai_file_path = str(PLATFORM_AI_FILE.resolve())
    return render_template(
        "site_settings.html",
        site=site,
        catalog=get_all_products(site),
        ai_cfg=ai_cfg,
        env_file_exists=ENV_FILE.exists(),
        ai_file_exists=ai_file_exists,
        ai_file_path=ai_file_path,
    )



@app.route("/settings", methods=["GET", "POST"])
@login_required
def account_settings():
    username = session["user"]
    user = get_user(username)
    if request.method == "POST":
        new_username = request.form.get("new_username", "").strip()
        old = request.form.get("old_password", "")
        new = request.form.get("new_password", "")
        conf = request.form.get("confirm_password", "")

        # Username change
        if new_username and new_username != username:
            import re as _re
            if not _re.match(r"^[a-zA-Z0-9_]{3,20}$", new_username):
                flash("Invalid username format", "danger")
                return redirect(url_for("account_settings"))
            if (USERS_DIR / f"{new_username}.json").exists():
                flash("Username already taken", "danger")
                return redirect(url_for("account_settings"))
            # rename user file
            old_path = USERS_DIR / f"{username}.json"
            user["username"] = new_username
            save_user(user)
            if old_path.exists() and old_path.name != f"{new_username}.json":
                old_path.unlink()
            # rename portfolio
            old_pf = PORTFOLIOS_DIR / f"{username}.json"
            new_pf = PORTFOLIOS_DIR / f"{new_username}.json"
            if old_pf.exists():
                pf = json.loads(old_pf.read_text())
                pf["username"] = new_username
                new_pf.write_text(json.dumps(pf, indent=2), encoding="utf-8")
                old_pf.unlink()
            # rename uploads folder
            old_up = IMG_UPLOADS / username
            new_up = IMG_UPLOADS / new_username
            if old_up.exists() and not new_up.exists():
                old_up.rename(new_up)
            session["user"] = new_username
            username = new_username
            user = get_user(username)
            flash("Username updated", "success")

        # Password change (optional)
        if old or new or conf:
            if not check_password_hash(user["password"], old):
                flash("Current password is wrong", "danger")
            elif new != conf:
                flash("New passwords do not match", "danger")
            elif len(new) < 4:
                flash("Password too short", "danger")
            else:
                user["password"] = generate_password_hash(new)
                save_user(user)
                flash("Password updated", "success")

        return redirect(url_for("account_settings"))
    return render_template("settings.html", user=user)


@app.route("/resume-builder")
@app.route("/cv-builder")
@login_required
def resume_builder():
    """Gallery (CV/Resume filter) → language/format → Magic Box."""
    username = session["user"]
    doc = load_cv(username)
    step = (request.args.get("step") or "gallery").strip()
    filt = (request.args.get("filter") or "all").strip().lower()
    templates = list(CV_TEMPLATES)
    if filt in ("cv", "resume"):
        templates = [t for t in CV_TEMPLATES if t["doc_type"] == filt]
    tid = (request.args.get("template_id") or doc.get("template_id") or "").strip()
    selected = next((t for t in CV_TEMPLATES if t["id"] == tid), None)
    return render_template(
        "resume_builder.html",
        doc=doc,
        user=get_user(username),
        step=step,
        filt=filt,
        templates=templates,
        selected=selected,
        all_templates=CV_TEMPLATES,
    )


@app.route("/cv-builder/select-template", methods=["POST"])
@login_required
def cv_select_template():
    username = session["user"]
    doc = load_cv(username)
    tid = (request.form.get("template_id") or "").strip()
    tpl = next((t for t in CV_TEMPLATES if t["id"] == tid), None)
    if not tpl:
        flash("Please select a template", "warning")
        return redirect(url_for("resume_builder", step="gallery"))
    doc["template_id"] = tid
    doc["doc_type"] = tpl["doc_type"]
    # Region/format is independent of visual theme — do not change design colors/layout
    if not doc.get("format"):
        doc["format"] = "us_standard"
    save_cv(username, doc)
    return redirect(url_for("resume_builder", step="options", template_id=tid))


@app.route("/cv-builder/save", methods=["POST"])
@login_required
def cv_builder_save():
    username = session["user"]
    doc = load_cv(username)
    doc["language"] = request.form.get("language") or "en"
    doc["format"] = request.form.get("format") or doc.get("format") or "us_standard"
    doc["full_name"] = request.form.get("full_name", "").strip()
    doc["phone"] = request.form.get("phone", "").strip()
    doc["email"] = request.form.get("email", "").strip()
    doc["address"] = request.form.get("address", "").strip()
    doc["web"] = request.form.get("web", "").strip()
    doc["education_raw"] = request.form.get("education_raw", "").strip()
    doc["personal_raw"] = request.form.get("personal_raw", "").strip()
    doc["magic_box"] = request.form.get("magic_box", "").strip()
    fphoto = request.files.get("photo_file")
    if fphoto and fphoto.filename:
        ext = Path(fphoto.filename).suffix.lower()
        if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
            folder = IMG_UPLOADS / username / "cv"
            folder.mkdir(parents=True, exist_ok=True)
            fname = f"cv_photo_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}"
            fphoto.save(folder / fname)
            doc["photo"] = f"/uploads/img/{username}/cv/{fname}"
    tid = request.form.get("template_id") or doc.get("template_id")
    if tid:
        doc["template_id"] = tid
        tpl = next((t for t in CV_TEMPLATES if t["id"] == tid), None)
        if tpl:
            doc["doc_type"] = tpl["doc_type"]
    save_cv(username, doc)
    if request.form.get("action") == "generate":
        return redirect(url_for("generate_cv"))
    flash("Saved. Your Magic Box text is stored securely.", "success")
    return redirect(url_for("resume_builder", step="write", template_id=doc.get("template_id")))


@app.route("/generate-cv", methods=["GET", "POST"])
@login_required
def generate_cv():
    """Structure Magic Box via Platform AI Brain (Gemini / OpenAI / Claude). Never invent facts."""
    username = session["user"]
    doc = load_cv(username)
    doc["last_generate_request"] = datetime.now().isoformat()
    api_key, _prov, _model, _src = resolve_ai_api_key("")
    api_key = (api_key or "").strip()
    if api_key and (doc.get("magic_box") or doc.get("full_name")):
        try:
            structured = call_openai_structure_cv(
                doc, api_key=api_key, model=_model, provider=_prov
            )
            if structured:
                doc["ai_generated_headline"] = structured.get("role") or doc.get("ai_generated_headline") or ""
                doc["ai_about"] = structured.get("about") or ""
                # Keep About short for sidebar (max ~100 words)
                if doc.get("ai_about"):
                    _aw = doc["ai_about"].split()
                    if len(_aw) > 100:
                        doc["ai_about"] = " ".join(_aw[:100]).rstrip(",.;:") + "."

                doc["ai_experience"] = structured.get("experience") or []
                # Normalize experience: spacing, self-employed location
                _loc = (doc.get("address") or "").strip()
                _norm_exp = []
                for _e in doc["ai_experience"]:
                    if not isinstance(_e, dict):
                        _norm_exp.append(_e)
                        continue
                    _co = (_e.get("company") or _e.get("employer") or "").strip()
                    _title = (_e.get("title") or "").strip()
                    if _co.lower() in ("self-employed", "self employed", "independent", "freelancer", "freelance"):
                        if _loc and _loc.lower() not in _co.lower():
                            # keep company + add city hint from address (last 2 parts)
                            parts = [p.strip() for p in _loc.replace(".", ",").split(",") if p.strip()]
                            place = ", ".join(parts[-2:]) if len(parts) >= 2 else (_loc[:40])
                            _co = f"{_co} · {place}"
                    # if company is a known restaurant name keep as-is
                    _e["company"] = _co
                    _e["employer"] = _co
                    _e["title"] = _title
                    _norm_exp.append(_e)
                doc["ai_experience"] = _norm_exp

                doc["ai_education"] = structured.get("education") or []
                doc["ai_skills"] = structured.get("skills") or []
                doc["ai_languages"] = structured.get("languages") or []
                doc["ai_awards"] = structured.get("awards") or []
                # fill contact only if model returned and user left blank
                for src, dst in (("email", "email"), ("phone", "phone"), ("location", "address"), ("website", "web"), ("name", "full_name")):
                    if structured.get(src) and not doc.get(dst):
                        doc[dst] = structured[src]
                doc["ai_status"] = "ready"
                save_cv(username, doc)
                return redirect(url_for("cv_builder_preview"))
        except Exception as e:
            print("OpenAI structure error:", e)
            doc["ai_status"] = "error"
            save_cv(username, doc)
            flash(f"AI error: {e}. Your Magic Box text is still saved.", "danger")
            return redirect(url_for("resume_builder", step="write", template_id=doc.get("template_id")))
    doc["ai_status"] = "coming_soon"
    save_cv(username, doc)
    cfg = get_platform_ai_config()
    if not api_key:
        msg = (
            "No platform AI key found. Go to Admin → Site Settings → Platform AI Brain, "
            "paste your Gemini (or OpenAI/Claude) key in Platform AI Brain, click Save AI Key, "
            "then return here and click Generate with AI again. "
            "Your Magic Box text is already saved — Preview still works."
        )
        if session.get("role") == "admin" or session.get("user") in ("admin", "forhad", "System Admin"):
            back_settings = url_for("site_settings")
        else:
            back_settings = None
    else:
        msg = (
            "AI key is present but structuring returned empty. "
            "Check that the key is valid and the model name is correct (default gpt-4o-mini). "
            "Your Magic Box text is saved."
        )
        back_settings = None
    return render_template(
        "ai_coming_soon.html",
        title="CV / Resume AI Generation",
        message=msg,
        back_url=url_for("resume_builder", step="write", template_id=doc.get("template_id")),
        back_label="Back to Magic Box",
        settings_url=back_settings,
        ai_configured=bool(cfg.get("configured")),
        ai_provider=cfg.get("provider"),
    )




def list_gemini_models(api_key: str):
    """Return model ids that support generateContent for this API key."""
    import urllib.request
    import urllib.error
    url = "https://generativelanguage.googleapis.com/v1beta/models?key=" + api_key
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            out = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print("list_gemini_models error:", e)
        return []
    ids = []
    for m in out.get("models") or []:
        name = (m.get("name") or "").replace("models/", "")
        methods = m.get("supportedGenerationMethods") or m.get("supported_generation_methods") or []
        if not name:
            continue
        if methods and "generateContent" not in methods:
            continue
        ids.append(name)
    return ids


def pick_gemini_model(api_key: str, preferred: str = ""):
    """Choose best available Gemini model for this key. Prefer flash-class free models."""
    preferred = (preferred or "").strip()
    available = list_gemini_models(api_key)
    if not available:
        # offline fallback list (newest first)
        return [
            preferred,
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "gemini-2.0-flash-001",
            "gemini-1.5-flash-latest",
            "gemini-1.5-flash-8b",
            "gemini-flash-latest",
            "gemini-pro-latest",
            "gemini-1.5-pro-latest",
        ]
    # rank: exact preferred, then flash, then others
    ranked = []
    if preferred and preferred in available:
        ranked.append(preferred)
    # prefer names containing flash (cheaper/faster)
    for m in available:
        if m not in ranked and "flash" in m.lower():
            ranked.append(m)
    for m in available:
        if m not in ranked:
            ranked.append(m)
    return ranked


def platform_ai_chat(system_prompt, user_prompt, *, json_mode=False, api_key=None, provider=None, model=None):
    """
    Single entry for all platform AI calls.
    Routes to OpenAI / Gemini / Claude based on Platform AI Brain (or explicit args).
    Returns assistant text (str) or raises Exception.
    """
    import urllib.request
    import urllib.error
    if not api_key or not provider:
        k, p, m, _src = resolve_ai_api_key("")
        api_key = api_key or k
        provider = (provider or p or "openai").lower()
        model = model or m
    api_key = (api_key or "").strip()
    provider = (provider or "openai").lower()
    if provider in ("chatgpt", "gpt", "gpt-4", "gpt4"):
        provider = "openai"
    if provider in ("anthropic",):
        provider = "claude"
    if provider in ("google",):
        provider = "gemini"
    if not api_key:
        raise RuntimeError("No platform AI API key configured. Set one in Site Settings → Platform AI Brain.")

    if provider == "openai":
        model = model or "gpt-4o-mini"
        body = {
            "model": model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + api_key,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            out = json.loads(resp.read().decode("utf-8"))
        return (out["choices"][0]["message"]["content"] or "").strip()

    if provider == "gemini":
        preferred = (model or "gemini-2.0-flash").strip()
        legacy_map = {
            "gemini-1.5-flash": "gemini-2.0-flash",
            "gemini-1.5-pro": "gemini-1.5-pro-latest",
            "gemini-pro": "gemini-2.0-flash",
            "gemini-3.8": "gemini-2.0-flash",
            "3.8": "gemini-2.0-flash",
        }
        preferred = legacy_map.get(preferred, preferred)
        candidates = pick_gemini_model(api_key, preferred)

        full_user = user_prompt
        if json_mode:
            full_user = user_prompt + "\n\nRespond with ONLY valid JSON. No markdown fences, no commentary."
        body = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": full_user}]}],
            "generationConfig": {"temperature": 0.2},
        }
        if json_mode:
            body["generationConfig"]["responseMimeType"] = "application/json"
        data = json.dumps(body).encode("utf-8")
        last_err = None
        for model_id in candidates:
            if not model_id:
                continue
            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                + model_id
                + ":generateContent?key="
                + api_key
            )
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=90) as resp:
                    out = json.loads(resp.read().decode("utf-8"))
                cands = out.get("candidates") or []
                if not cands:
                    last_err = RuntimeError("Gemini returned no candidates from %s: %s" % (model_id, str(out)[:300]))
                    continue
                parts = (((cands[0] or {}).get("content") or {}).get("parts")) or []
                text = "".join((p.get("text") or "") for p in parts).strip()
                if text:
                    return text
                last_err = RuntimeError("Empty text from model " + model_id)
            except urllib.error.HTTPError as he:
                err_body = he.read().decode("utf-8", errors="replace")
                last_err = RuntimeError("Gemini HTTP %s (%s): %s" % (he.code, model_id, err_body[:400]))
                if he.code in (404, 400, 429):
                    continue
                # other errors: still try next, but keep error
                continue
            except Exception as e:
                last_err = e
                continue
        # include available models in error for debugging
        avail = list_gemini_models(api_key)
        raise RuntimeError(
            str(last_err)
            + " | Tried: "
            + ", ".join(candidates[:8])
            + (" | Available for your key: " + ", ".join(avail[:12]) if avail else " | Could not list models for this key")
        )

    if provider == "claude":
        model = model or "claude-3-5-sonnet-latest"
        content = user_prompt
        if json_mode:
            content = user_prompt + "\n\nRespond with ONLY valid JSON."
        body = {
            "model": model,
            "max_tokens": 4096,
            "temperature": 0.2,
            "system": system_prompt,
            "messages": [{"role": "user", "content": content}],
        }
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=data,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            out = json.loads(resp.read().decode("utf-8"))
        blocks = out.get("content") or []
        text = "".join((b.get("text") or "") for b in blocks if b.get("type") == "text").strip()
        return text

    raise RuntimeError("Unsupported AI provider: %s" % provider)


def _parse_json_loose(text):
    """Extract JSON object from model text (handles markdown fences)."""
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        lines = s.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines).strip()
        if s.lower().startswith("json"):
            s = s[4:].lstrip()
    try:
        return json.loads(s)
    except Exception:
        pass
    a, b = s.find("{"), s.rfind("}")
    if a >= 0 and b > a:
        try:
            return json.loads(s[a:b + 1])
        except Exception:
            return None
    return None


def call_openai_structure_cv(doc, api_key=None, model=None, provider=None):
    """Structure Magic Box via Platform AI Brain (OpenAI / Gemini / Claude). Never invent facts."""
    system = (
        "You are a professional CV writer. Convert the user's rough notes into structured JSON for a CV/Resume. "
        "RULES: "
        "1) Use ONLY facts the user provided. Do NOT invent company names, metrics, degrees, certificates, or awards. "
        "2) Self-employed / contractor work is valid — use company as 'Self-employed' or the business name they gave. "
        "3) Write the 'about' field as a SHORT polished professional English profile (MAX 80-100 words, about 5-8 short lines). Focus on who they are and their core strengths/skills only. Do NOT list years, job timelines, or employer names in about — those belong only in experience. Still never invent facts. "
        "4) For experience bullets: write 2-4 professional English bullet points per job from what they described (no fake numbers). "
        "5) Extract real skills from their text (e.g. Plumbing, Electrical work, Computer operations, Basic web development, Hospitality, Driving). "
        "6) Extract languages exactly as stated (e.g. Bengali · Native, English · Conversational). "
        "7) Parse education from education_raw if provided. "
        "8) role = short professional headline in English (e.g. 'Self-Employed Electrician & Plumber | Computer Operator'). "
        "Return strict JSON with keys: name, role, email, phone, location, website, about, "
        "skills (string array), languages (string array like 'English · Fluent'), "
        "education (array of {title, institution, dates}), "
        "experience (array of {title, company, start, end, present, bullets}), "
        "awards (string array — empty if none)."
    )
    user_msg = {
        "full_name": doc.get("full_name"),
        "phone": doc.get("phone"),
        "email": doc.get("email"),
        "address": doc.get("address"),
        "web": doc.get("web"),
        "education_raw": doc.get("education_raw"),
        "personal_raw": doc.get("personal_raw"),
        "magic_box": doc.get("magic_box"),
        "language": doc.get("language"),
        "format": doc.get("format"),
        "doc_type": doc.get("doc_type"),
    }
    text = platform_ai_chat(
        system,
        json.dumps(user_msg, ensure_ascii=False),
        json_mode=True,
        api_key=api_key,
        provider=provider,
        model=model,
    )
    return _parse_json_loose(text)



@app.route("/cv-builder/thumb/<tid>")
@login_required
def cv_template_thumb(tid):
    """Serve pack preview HTML for gallery iframes."""
    load_cv_templates()
    tpl = next((t for t in CV_TEMPLATES if t["id"] == tid), None)
    if tpl:
        path = pack_template_path(tpl, use_preview=True)
        if path and path.exists():
            return path.read_text(encoding="utf-8", errors="ignore"), 200, {"Content-Type": "text/html; charset=utf-8"}
    # fallback legacy thumbs
    if tid in ("europass_cv",) or (tpl and tpl.get("doc_type") == "cv"):
        return render_template("cv_thumb_europass.html")
    return render_template("cv_thumb_modern.html")


@app.route("/cv-builder/preview")
@login_required
def cv_builder_preview():
    """Render selected pack template filled with user/AI profile data."""
    username = session["user"]
    doc = load_cv(username)
    load_cv_templates()
    tid = doc.get("template_id") or ""
    tpl = next((t for t in CV_TEMPLATES if t["id"] == tid), None)
    profile = build_profile_from_doc(doc)
    if tpl:
        path = pack_template_path(tpl, use_preview=False)
        if not path:
            path = pack_template_path(tpl, use_preview=True)
        if path and path.exists():
            html = path.read_text(encoding="utf-8", errors="ignore")
            html = fill_pack_template_html(html, profile)
            # toolbar inject (hidden on print via .mfh-cv-toolbar)
            bar = (
                '<div class="mfh-cv-toolbar" style="position:sticky;top:0;z-index:50;background:#0f172a;color:#fff;'
                'padding:10px 16px;display:flex;gap:10px;flex-wrap:wrap;font-family:system-ui,sans-serif;">'
                f'<a href="/cv-builder?step=write&template_id={tid}" style="color:#fff;text-decoration:none;'
                'background:#334155;padding:6px 12px;border-radius:8px;">← Edit</a>'
                '<a href="javascript:window.print()" style="color:#fff;text-decoration:none;'
                'background:#4f46e5;padding:6px 12px;border-radius:8px;">Print / PDF</a>'
                '<span style="opacity:.8;font-size:13px;align-self:center;">'
                f'{_esc(tpl.get("name") or tid)} · {_esc(doc.get("language") or "")} · {_esc(doc.get("format") or "")}'
                '</span></div>'
            )
            if "<body>" in html:
                html = html.replace("<body>", "<body>" + bar, 1)
            else:
                html = bar + html
            return html, 200, {"Content-Type": "text/html; charset=utf-8"}
    # Legacy fallback
    layout = (tpl or {}).get("layout") or "modern"
    if layout == "europass" or doc.get("format") == "europass" or doc.get("doc_type") == "cv":
        return render_template("cv_preview_europass.html", doc=doc, template=tpl)
    return render_template("cv_preview_modern.html", doc=doc, template=tpl)


@app.route("/cover-letter")
@login_required
def cover_letter_builder():
    username = session["user"]
    mode = (request.args.get("mode") or "hub").strip()
    return render_template(
        "cover_letter.html",
        mode=mode,
        letters=load_covers(username),
        templates=CL_TEMPLATES,
        cv_doc=load_cv(username),
        selected=None,
        edit_letter=None,
    )



@app.route("/admin/users/<username>/delete", methods=["POST"])
@admin_required
def admin_delete_user(username):
    if username == session.get("user"):
        flash("Cannot delete yourself", "danger")
        return redirect(url_for("admin_users"))
    target = get_user(username)
    if not target:
        flash("User not found", "danger")
        return redirect(url_for("admin_users"))
    # Do not delete the last remaining admin
    if target.get("role") == "admin":
        admin_count = 0
        for f in USERS_DIR.glob("*.json"):
            try:
                if json.loads(f.read_text()).get("role") == "admin":
                    admin_count += 1
            except Exception:
                pass
        if admin_count <= 1:
            flash("Cannot delete the last admin account", "danger")
            return redirect(url_for("admin_users"))
    path = USERS_DIR / f"{username}.json"
    if path.exists():
        path.unlink()
        # also remove portfolio file if any
        pf = PORTFOLIOS_DIR / f"{username}.json"
        if pf.exists():
            pf.unlink()
        flash(f"User {username} deleted", "success")
    else:
        flash("User not found", "danger")
    return redirect(url_for("admin_users"))

    path = USERS_DIR / f"{username}.json"
    if path.exists():
        path.unlink()
        flash(f"User {username} deleted", "success")
    else:
        flash("User not found", "danger")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<username>/toggle-publish", methods=["POST"])
@admin_required
def admin_toggle_publish(username):
    user = get_user(username)
    if not user:
        flash("User not found", "danger")
        return redirect(url_for("admin_users"))
    portfolio = load_portfolio(username)
    published = not portfolio.get("published", False)
    portfolio["published"] = published
    portfolio["username"] = username
    save_portfolio(username, portfolio)
    user["portfolio_published"] = published
    save_user(user)
    flash(f"{username} portfolio {'published' if published else 'unpublished'}", "success")
    return redirect(url_for("admin_users"))



@app.route("/choose-plan", methods=["POST"])
@login_required
def choose_plan():
    username = session["user"]
    user = get_user(username)
    if is_lifetime_user(user):
        flash("Lifetime accounts do not need a paid plan.", "info")
        return redirect(url_for("subscription_page"))
    key = request.form.get("plan_key", "")
    site = load_site_settings()
    plans = {p["key"]: p for p in get_plans_list(site)}
    if key not in plans:
        flash("Invalid plan", "danger")
        return redirect(url_for("subscription_page"))
    plan = plans[key]
    user["plan"] = plan.get("slug") or "basic"
    user["plan_name"] = plan["name"]
    user["plan_price"] = plan["price"]
    user["plan_updated_at"] = datetime.now().isoformat()
    save_user(user)
    # Notify referrer if this user was referred
    ref_by = user.get("referred_by")
    if ref_by and plan.get("slug") in ("basic", "pro", "business"):
        add_notification(
            ref_by,
            "Referral purchased a plan",
            f"{username} bought {plan['name']} (${plan['price']}/mo) using your referral.",
            "referral",
            from_user=username,
        )
    add_notification(username, "Plan activated", f"Your plan is now {plan['name']}.", "success")
    flash(f"Plan set to {plan['name']} (${plan['price']}/mo).", "success")
    return redirect(url_for("subscription_page"))


@app.route("/subscription")
@login_required
def subscription_page():
    username = session["user"]
    user = ensure_admin_lifetime(get_user(username))
    days_left, expired = trial_info(user)
    site = load_site_settings()
    my_pending = [
        r for r in load_payment_requests()
        if r.get("username") == username and r.get("status") == "pending"
    ]
    products = get_all_products(site)
    return render_template(
        "subscription.html",
        user=user,
        plans=get_plans_list(site),
        trial_days_left=days_left,
        trial_expired=expired,
        is_lifetime=is_lifetime_user(user),
        pay=get_payment_config(site),
        my_pending=my_pending,
        products=products,
        full_access_price=get_full_access_price(site),
    )


@app.route("/admin/users/<username>/set-plan", methods=["POST"])
@admin_required
def admin_set_plan(username):
    user = get_user(username)
    if not user:
        flash("User not found", "danger")
        return redirect(url_for("admin_users"))
    if user.get("role") == "admin":
        flash("Cannot change master admin plan", "danger")
        return redirect(url_for("admin_users"))
    plan = (request.form.get("plan") or "free").strip().lower()
    allowed = {"free", "basic", "pro", "business", "lifetime"}
    if plan not in allowed:
        flash("Invalid plan", "danger")
        return redirect(url_for("admin_users"))
    user["plan"] = plan
    user["plan_name"] = {
        "free": "Free Trial",
        "basic": "Basic",
        "pro": "Pro",
        "business": "Business",
        "lifetime": "Lifetime Free (Granted)",
    }.get(plan, plan)
    user["plan_granted_by"] = session.get("user")
    user["plan_updated_at"] = datetime.now().isoformat()
    if plan == "free":
        user["created_at"] = datetime.now().isoformat()
        user["full_access"] = False
        user["unlocked_modules"] = []
        user["unlocked_core"] = ["portfolio-builder", "resume-cv", "cover-letter"]
    elif plan == "lifetime":
        user["full_access"] = True
        user["unlocked_modules"] = [m["id"] for m in DEFAULT_MODULES]
        user["unlocked_core"] = [c["id"] for c in CORE_SERVICES]
    elif plan == "business":
        user["full_access"] = True
        user["unlocked_modules"] = [m["id"] for m in DEFAULT_MODULES]
        user["unlocked_core"] = [c["id"] for c in CORE_SERVICES]
    elif plan in ("basic", "pro"):
        user["full_access"] = False
        # Keep existing module unlocks; ensure core tools
        core = list(user.get("unlocked_core") or [])
        for cid in ("portfolio-builder", "resume-cv", "cover-letter"):
            if cid not in core:
                core.append(cid)
        user["unlocked_core"] = core
    save_user(user)
    add_notification(
        username,
        "Plan updated by admin",
        f"Your plan is now: {user['plan_name']}.",
        "plan",
        from_user=session.get("user"),
    )
    flash(f"Plan for {username} set to {user['plan_name']}", "success")
    return redirect(url_for("admin_users"))


@app.route("/referral/apply-year-free", methods=["POST"])
@login_required
def apply_year_free():
    username = session["user"]
    user = get_user(username)
    if is_lifetime_user(user):
        flash("You already have lifetime access", "info")
        return redirect(url_for("dashboard"))
    _, paid = count_referral_stats(username)
    if paid < 100:
        flash(f"Need 100 paid referrals. You have {paid}.", "danger")
        return redirect(url_for("dashboard"))
    if user.get("year_free_applied"):
        flash("You already applied for 1-year free. Waiting for admin.", "info")
        return redirect(url_for("dashboard"))
    user["year_free_applied"] = True
    user["year_free_applied_at"] = datetime.now().isoformat()
    save_user(user)
    add_notification(
        "__admins__",
        "1-Year Free Application",
        f"{username} applied for 1-year free plan ({paid} paid referrals).",
        "referral",
        from_user=username,
    )
    add_notification(username, "Application submitted", "Your 1-year free plan request was sent to admin.", "success")
    flash("Application sent to admin", "success")
    return redirect(url_for("dashboard"))


@app.route("/referral/apply-commission", methods=["POST"])
@login_required
def apply_commission():
    username = session["user"]
    user = get_user(username)
    _, paid = count_referral_stats(username)
    if paid < 500:
        flash(f"Need 500 paid referrals. You have {paid}.", "danger")
        return redirect(url_for("dashboard"))
    if user.get("commission_applied"):
        flash("You already applied for 5% commission. Waiting for admin.", "info")
        return redirect(url_for("dashboard"))
    if not (user.get("payout_account") or "").strip():
        flash("Add your payout account in Profile first (bKash / bank / Payoneer).", "danger")
        return redirect(url_for("profile_settings"))
    user["commission_applied"] = True
    user["commission_applied_at"] = datetime.now().isoformat()
    save_user(user)
    payout_info = (
        f"Method: {user.get('payout_method') or 'n/a'}\n"
        f"Account: {user.get('payout_account') or 'n/a'}\n"
        f"Name: {user.get('payout_account_name') or 'n/a'}\n"
        f"Bank: {user.get('payout_bank_name') or 'n/a'}\n"
        f"Note: {user.get('payout_note') or 'n/a'}"
    )
    add_notification(
        "__admins__",
        "5% Commission Application",
        f"{username} applied for 5% referral income ({paid} paid referrals).\n\nPayout details:\n{payout_info}",
        "referral",
        from_user=username,
    )
    add_notification(username, "Commission request submitted", "Your 5% income request was sent to admin.", "success")
    flash("Commission application sent to admin", "success")
    return redirect(url_for("dashboard"))


@app.route("/notifications")
@login_required
def notifications_page():
    username = session["user"]
    items = get_notifications(username)
    # mark all read
    path = NOTIFICATIONS_DIR / f"{username}.json"
    if path.exists():
        try:
            data = json.loads(path.read_text())
            for n in data:
                n["read"] = True
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass
    return render_template("notifications.html", notifications=items)


@app.route("/contact", methods=["GET", "POST"])
def contact_page():
    site = load_site_settings()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        message = request.form.get("message", "").strip()
        if not name or not message:
            flash("Name and message required", "danger")
            return redirect(url_for("contact_page"))
        add_notification(
            "__admins__",
            f"Contact from {name}",
            f"Email: {email}\n\n{message}",
            "contact",
            from_user=session.get("user") or email or name,
        )
        if session.get("user"):
            add_notification(session["user"], "Message sent", "Your message was sent to support.", "success")
        flash("Message sent. We will get back to you.", "success")
        return redirect(url_for("contact_page") if not session.get("user") else url_for("dashboard"))
    return render_template(
        "contact.html",
        site_name=site.get("site_name", "Portfolio SaaS"),
        site_logo=site.get("site_logo", ""),
        support_email=site.get("support_email", ""),
    )



@app.route("/help", methods=["GET", "POST"])
@login_required
def help_page():
    if request.method == "POST":
        subject = request.form.get("subject", "").strip()
        message = request.form.get("message", "").strip()
        if not subject or not message:
            flash("Subject and message required", "danger")
            return redirect(url_for("help_page"))
        username = session["user"]
        add_notification(
            "__admins__",
            f"Help: {subject}",
            message,
            "help",
            from_user=username,
        )
        add_notification(username, "Help request sent", f"Subject: {subject}\nWe will reply in Notifications.", "success")
        flash("Message sent to support", "success")
        return redirect(url_for("notifications_page"))
    return render_template("help.html")


@app.route("/subscription/pay", methods=["POST"])
@login_required
def submit_payment():
    flash("Online payment is Coming Soon. Contact admin if you already paid.", "info")
    return redirect(url_for("payment_methods"))


@app.route("/admin/payments", methods=["GET", "POST"])
@admin_required
def admin_payments():
    site = load_site_settings()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add_txn":
            txn_id = (request.form.get("txn_id") or "").strip()
            method = (request.form.get("method") or "bkash").strip().lower()
            note = (request.form.get("note") or "").strip()
            try:
                amount = float(request.form.get("amount") or 0)
            except ValueError:
                amount = 0
            if not txn_id or len(txn_id) < 4:
                flash("Invalid transaction ID", "danger")
            elif any(normalize_txn(x.get("txn_id")) == normalize_txn(txn_id) for x in load_received_txns()):
                flash("This Txn ID is already in the pool", "warning")
            else:
                items = load_received_txns()
                items.insert(0, {
                    "txn_id": txn_id,
                    "method": method,
                    "amount": amount,
                    "note": note,
                    "used": False,
                    "added_at": datetime.now().isoformat(),
                    "added_by": session.get("user"),
                })
                save_received_txns(items)
                flash(f"Txn ID added: {txn_id}", "success")
            return redirect(url_for("admin_payments"))

        if action == "approve":
            req_id = request.form.get("req_id")
            items = load_payment_requests()
            for rec in items:
                if rec.get("id") == req_id and rec.get("status") == "pending":
                    u = get_user(rec["username"])
                    if u:
                        activate_user_plan(
                            u,
                            rec.get("plan_slug") or "basic",
                            rec.get("plan_name") or "Plan",
                            rec.get("amount") or 0,
                            rec.get("method"),
                            rec.get("txn_id"),
                        )
                        mark_txn_used(rec.get("txn_id"), rec["username"])
                    rec["status"] = "approved"
                    rec["approved_at"] = datetime.now().isoformat()
                    rec["approved_by"] = session.get("user")
                    save_payment_requests(items)
                    add_notification(
                        rec["username"],
                        "Payment approved",
                        f"Your {rec.get('plan_name')} plan is now active.",
                        "payment",
                    )
                    flash(f"Approved payment for {rec['username']}", "success")
                    break
            return redirect(url_for("admin_payments"))

        if action == "reject":
            req_id = request.form.get("req_id")
            items = load_payment_requests()
            for rec in items:
                if rec.get("id") == req_id and rec.get("status") == "pending":
                    rec["status"] = "rejected"
                    rec["rejected_at"] = datetime.now().isoformat()
                    rec["rejected_by"] = session.get("user")
                    save_payment_requests(items)
                    add_notification(
                        rec["username"],
                        "Payment rejected",
                        f"Your payment ({rec.get('txn_id')}) was rejected. Contact support if needed.",
                        "payment",
                    )
                    flash(f"Rejected payment for {rec['username']}", "info")
                    break
            return redirect(url_for("admin_payments"))

    requests_list = load_payment_requests()
    received = load_received_txns()
    pending = [r for r in requests_list if r.get("status") == "pending"]
    return render_template(
        "admin_payments.html",
        pending=pending,
        all_requests=requests_list[:50],
        received=received[:50],
        pay=get_payment_config(site),
    )





@app.route("/cart/checkout", methods=["POST"])
def cart_checkout():
    """Store selection only — no unlock until payment (mock → Coming Soon)."""
    full = request.form.get("full_access") == "1"
    ids = [i.strip() for i in request.form.getlist("product_id") if i.strip()]
    plan_key = (request.form.get("plan_key") or "").strip()
    if full:
        ids = [c["id"] for c in CORE_SERVICES] + [m["id"] for m in DEFAULT_MODULES]
    if not ids and not full and not plan_key:
        flash("Select at least one service or plan", "warning")
        return redirect(url_for("index") + "#services")
    session["pending_cart"] = ids
    session["pending_full_access"] = full
    if plan_key:
        session["pending_plan_key"] = plan_key
    # Price for checkout display
    site = load_site_settings()
    total = 0.0
    if full:
        total = get_full_access_price(site)
    else:
        products = {p["id"]: p for p in get_all_products(site)}
        for pid in ids:
            if pid in products:
                try:
                    total += float(products[pid].get("price") or 0)
                except (TypeError, ValueError):
                    pass
        if plan_key:
            for p in get_plans_list(site):
                if p.get("key") == plan_key or p.get("slug") == plan_key:
                    try:
                        total += float(p.get("price") or 0)
                    except (TypeError, ValueError):
                        pass
                    break
    session["pending_total"] = round(total, 2)
    if not session.get("user"):
        flash("Create an account to continue", "info")
        return redirect(url_for("register"))
    return redirect(url_for("payment_methods"))


@app.route("/payment-methods", methods=["GET", "POST"])
def payment_methods():
    """Mock payment method picker — submit shows Coming Soon (no real charge)."""
    if not session.get("user"):
        flash("Please log in or register first", "warning")
        return redirect(url_for("register"))
    site = load_site_settings()
    total = session.get("pending_total")
    if total is None:
        total = 0
    items = session.get("pending_cart") or []
    full = session.get("pending_full_access")
    plan_key = session.get("pending_plan_key")
    product_names = []
    catalog = {p["id"]: p for p in get_all_products(site)}
    for pid in items:
        if pid in catalog:
            product_names.append(catalog[pid]["name"])
    methods = [
        {"id": "bkash", "name": "bKash", "color": "#e2136e", "hint": "Mobile wallet (Bangladesh)"},
        {"id": "nagad", "name": "Nagad", "color": "#f47920", "hint": "Mobile wallet (Bangladesh)"},
        {"id": "rocket", "name": "Rocket", "color": "#8b3dff", "hint": "DBBL mobile banking"},
        {"id": "stripe", "name": "Stripe", "color": "#635bff", "hint": "Cards worldwide"},
        {"id": "paypal", "name": "PayPal", "color": "#003087", "hint": "International wallet"},
        {"id": "payoneer", "name": "Payoneer", "color": "#ff6a00", "hint": "Global payouts"},
    ]
    if request.method == "POST":
        method = (request.form.get("method") or "").strip().lower()
        if not method:
            flash("Select a payment method", "warning")
            return redirect(url_for("payment_methods"))
        # Coming Soon — do NOT unlock
        return render_template(
            "payment_coming_soon.html",
            method=method,
            total=total,
            product_names=product_names,
            full_access=full,
            site_name=site.get("site_name", "Portfolio SaaS"),
        )
    return render_template(
        "payment_methods.html",
        methods=methods,
        total=total,
        product_names=product_names,
        full_access=full,
        plan_key=plan_key,
        site_name=site.get("site_name", "Portfolio SaaS"),
    )




# ==================== ULTIMATE SECOND BRAIN ====================
SB_MODULE_ID = "ultimate-second-brain"

DEFAULT_SECOND_BRAIN = {
    "settings": {
        "timezone": "Asia/Dhaka",
        "week_starts_on": 6,
        "default_view": "home",
        "openai_user_key": "",
    },
    "daily_focus": "",
    "captures": [],
    "tasks": [],
    "projects": [],
    "goals": [],
    "notes": [],
    "content_ideas": [],
    "resources": [],
    "habits": {},
    "planners": {},
    "weekly_reviews": [],
    "habit_defs": [
        {"id": "deep_work", "label": "Deep Work"},
        {"id": "workout", "label": "Workout"},
        {"id": "read", "label": "Read 20 min"},
        {"id": "meditate", "label": "Meditate"},
        {"id": "water", "label": "Drink Water"},
        {"id": "sleep", "label": "Sleep 7h+"},
    ],
    "workspace_templates": [
        {
            "id": "weekly_review_pack",
            "name": "Weekly Review Pack",
            "desc": "Goals check-in + 5 review prompts + habit reset",
            "tasks": ["Review wins", "Review misses", "Plan next week top 3"],
            "notes": ["Weekly reflection"],
        },
        {
            "id": "project_kickoff",
            "name": "Project Kickoff",
            "desc": "Scope, milestones, first tasks for a new project",
            "tasks": ["Define scope", "List milestones", "Identify risks"],
            "notes": ["Project brief"],
        },
        {
            "id": "content_sprint",
            "name": "Content Sprint",
            "desc": "Idea → draft → publish checklist",
            "tasks": ["Collect 10 ideas", "Draft 3 pieces", "Schedule publish"],
            "notes": ["Content angle notes"],
        },
        {
            "id": "deep_work_day",
            "name": "Deep Work Day",
            "desc": "Focus blocks and distraction log",
            "tasks": ["Block 2h deep work", "Clear inbox", "End-of-day review"],
            "notes": ["Distraction log"],
        },
    ],
    "updated_at": "",
}


def sb_path(username):
    folder = MODULES_DIR / SB_MODULE_ID
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{username}.json"


def load_second_brain(username):
    path = sb_path(username)
    base = json.loads(json.dumps(DEFAULT_SECOND_BRAIN))
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                base.update(data)
        except Exception:
            pass
    # merge settings defaults without wiping user keys
    if not isinstance(base.get("settings"), dict):
        base["settings"] = dict(DEFAULT_SECOND_BRAIN["settings"])
    else:
        for sk, sv in DEFAULT_SECOND_BRAIN["settings"].items():
            base["settings"].setdefault(sk, sv)
    # migrate old v1 keys
    if base.get("inbox") and not base.get("captures"):
        for item in base.get("inbox") or []:
            base["captures"].append({
                "id": item.get("id") or _sb_id(),
                "title": item.get("text") or "",
                "type": "Thought",
                "processed": False,
                "captured": item.get("created_at") or datetime.now().isoformat(),
            })
    for k in ("captures", "tasks", "projects", "goals", "notes", "content_ideas", "resources", "weekly_reviews"):
        if not isinstance(base.get(k), list):
            base[k] = []
    if not isinstance(base.get("habits"), dict):
        base["habits"] = {}
    if not isinstance(base.get("planners"), dict):
        base["planners"] = {}
    if not base.get("habit_defs"):
        base["habit_defs"] = list(DEFAULT_SECOND_BRAIN["habit_defs"])
    if not base.get("workspace_templates"):
        base["workspace_templates"] = list(DEFAULT_SECOND_BRAIN.get("workspace_templates") or [])
    return base


def save_second_brain(username, data):
    data = data or {}
    data["updated_at"] = datetime.now().isoformat()
    path = sb_path(username)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _sb_id():
    return datetime.now().strftime("%Y%m%d%H%M%S%f")


def _sb_today():
    return datetime.now().strftime("%Y-%m-%d")


def _sb_guard():
    user = get_user(session.get("user"))
    if not user or not user_has_module(user, SB_MODULE_ID):
        return None
    return user



def _sb_norm_project_status(raw):
    """Normalize project status to a known canonical value."""
    s = (raw or "Not Started").strip()
    allowed = {"Not Started", "In Progress", "On Hold", "Completed"}
    if s in allowed:
        return s
    low = s.lower().replace("_", " ").strip()
    mapping = {
        "not started": "Not Started",
        "notstarted": "Not Started",
        "in progress": "In Progress",
        "inprogress": "In Progress",
        "on hold": "On Hold",
        "onhold": "On Hold",
        "completed": "Completed",
        "complete": "Completed",
        "done": "Completed",
    }
    return mapping.get(low, "Not Started")


def sb_counts(data):
    open_tasks = [t for t in data.get("tasks") or [] if (t.get("status") or "") != "Done" and not t.get("done")]
    active_projects = [p for p in data.get("projects") or [] if (p.get("status") or "").strip().lower() not in ("completed", "done", "complete")]
    unprocessed = [c for c in data.get("captures") or [] if not c.get("processed")]
    return {
        "inbox": len(unprocessed),
        "open_tasks": len(open_tasks),
        "notes": len(data.get("notes") or []),
        "active_projects": len(active_projects),
        "goals": len(data.get("goals") or []),
        "captures": len(data.get("captures") or []),
        "content": len(data.get("content_ideas") or []),
        "resources": len(data.get("resources") or []),
        "reviews": len(data.get("weekly_reviews") or []),
    }


def _sb_resolve_default_page(data):
    """Map saved default_view preference to a valid second_brain page slug."""
    st = data.get("settings") if isinstance(data, dict) else {}
    if not isinstance(st, dict):
        st = {}
    dv = (st.get("default_view") or "home").strip().lower()
    mapping = {
        "home": "home",
        "dashboard": "home",
        "overview": "home",
        "planner": "planner",
        "daily": "planner",
        "daily-planner": "planner",
        "daily_planner": "planner",
        "tasks": "tasks",
        "task": "tasks",
        "captures": "capture",
        "capture": "capture",
        "quick-capture": "capture",
        "goals": "goals",
        "goal": "goals",
        "notes": "notes",
        "note": "notes",
    }
    page = mapping.get(dv, "home")
    allowed = {
        "home", "start-here", "capture", "tasks", "projects", "goals", "habits",
        "planner", "weekly-review", "notes", "content", "resources",
        "databases", "guide", "settings", "areas", "search", "templates", "focus",
    }
    return page if page in allowed else "home"


@app.route("/module/<module_id>")
@login_required
def open_module(module_id):
    user = get_user(session["user"])
    site = load_site_settings()
    modules = {m["id"]: m for m in get_modules(site)}
    mod = modules.get(module_id)
    if not mod or not mod.get("enabled", True):
        flash("Module not found", "danger")
        return redirect(url_for("dashboard"))
    if not user_has_module(user, module_id):
        flash("This module is not unlocked on your account. Purchase it to unlock.", "warning")
        return redirect(url_for("subscription_page"))
    if module_id == SB_MODULE_ID:
        # Honor user's Default View preference
        data = load_second_brain(session["user"])
        target = _sb_resolve_default_page(data)
        return redirect(url_for("second_brain", page=target))
    if module_id == CC_MODULE_ID:
        return redirect(url_for("content_creator", page="home"))
    if module_id == FA_MODULE_ID:
        return redirect(url_for("freelance_agency", page="home"))
    if module_id == SP_MODULE_ID:
        return redirect(url_for("student_productivity", page="home"))
    if module_id == DPS_MODULE_ID:
        return redirect(url_for("digital_product_seller", page="home"))
    return render_template("module_placeholder.html", module=mod)


@app.route("/os/second-brain")
@login_required
def second_brain_entry():
    """Entry point from dashboard/sidebar — applies saved default_view."""
    user = _sb_guard()
    if not user:
        flash("Ultimate Second Brain is not unlocked on your account.", "warning")
        return redirect(url_for("subscription_page"))
    data = load_second_brain(session["user"])
    target = _sb_resolve_default_page(data)
    return redirect(url_for("second_brain", page=target))


@app.route("/os/second-brain/<page>")
@login_required
def second_brain(page="home"):
    user = _sb_guard()
    if not user:
        flash("Ultimate Second Brain is not unlocked on your account.", "warning")
        return redirect(url_for("subscription_page"))
    site = load_site_settings()
    modules = {m["id"]: m for m in get_modules(site)}
    mod = modules.get(SB_MODULE_ID) or {"id": SB_MODULE_ID, "name": "Ultimate Second Brain", "icon": "🧠"}
    data = load_second_brain(session["user"])
    page = (page or "home").strip().lower().replace(" ", "-")
    # Aliases from settings labels
    aliases = {"daily": "planner", "daily-planner": "planner", "captures": "capture", "dashboard": "home", "overview": "home"}
    page = aliases.get(page, page)
    allowed = {
        "home", "start-here", "capture", "tasks", "projects", "goals", "habits",
        "planner", "weekly-review", "notes", "content", "resources",
        "databases", "guide", "settings", "areas", "search", "templates", "focus",
    }
    if page not in allowed:
        page = "home"
    counts = sb_counts(data)
    today = _sb_today()
    habit_date = (request.args.get("date") or today).strip() or today
    habit_today = data.get("habits", {}).get(habit_date) or {}
    planner_today = data.get("planners", {}).get(today) or {}
    # filters from query
    q = (request.args.get("q") or "").strip().lower()
    status_f = (request.args.get("status") or "").strip()
    area_f = (request.args.get("area") or "").strip()
    view = (request.args.get("view") or "list").strip()
    search_results = []
    if page == "search" and q:
        def hit(kind, title, snippet, href, rid=""):
            search_results.append({
                "kind": kind, "title": title, "snippet": snippet, "href": href, "id": rid,
            })
        for c in data.get("captures") or []:
            blob = (c.get("title") or "").lower()
            if q in blob:
                hit("Capture", c.get("title"), c.get("type"), url_for("second_brain", page="capture"), c.get("id"))
        for t in data.get("tasks") or []:
            blob = " ".join([t.get("title") or "", t.get("status") or "", t.get("context") or ""]).lower()
            if q in blob:
                hit("Task", t.get("title"), t.get("status"), url_for("second_brain", page="tasks"), t.get("id"))
        for p in data.get("projects") or []:
            blob = " ".join([p.get("name") or "", p.get("notes") or "", p.get("area") or ""]).lower()
            if q in blob:
                hit("Project", p.get("name"), p.get("area"), url_for("second_brain", page="projects"), p.get("id"))
        for g in data.get("goals") or []:
            blob = " ".join([g.get("title") or "", g.get("why") or "", g.get("category") or ""]).lower()
            if q in blob:
                hit("Goal", g.get("title"), g.get("category"), url_for("second_brain", page="goals"), g.get("id"))
        for n in data.get("notes") or []:
            blob = " ".join([n.get("title") or "", n.get("body") or "", n.get("type") or ""]).lower()
            if q in blob:
                hit("Note", n.get("title"), (n.get("body") or "")[:120], url_for("second_brain", page="notes"), n.get("id"))
        for c in data.get("content_ideas") or []:
            blob = " ".join([c.get("idea") or "", c.get("hook") or "", c.get("status") or ""]).lower()
            if q in blob:
                hit("Content", c.get("idea"), c.get("status"), url_for("second_brain", page="content"), c.get("id"))
        for r in data.get("resources") or []:
            blob = " ".join([r.get("name") or "", r.get("link") or "", r.get("category") or ""]).lower()
            if q in blob:
                hit("Resource", r.get("name"), r.get("link"), url_for("second_brain", page="resources"), r.get("id"))

    # Habit streaks (consecutive days ending today or yesterday)
    from datetime import timedelta as _td
    habit_streaks = []
    habits_map = data.get("habits") or {}
    defs = data.get("habit_defs") or []
    for h in defs:
        hid = h.get("id")
        label = h.get("label") or hid
        streak = 0
        d = datetime.now().date()
        # if today not checked, still allow streak ending yesterday
        checked_today = bool((habits_map.get(d.strftime("%Y-%m-%d")) or {}).get(hid))
        if not checked_today:
            d = d - _td(days=1)
        while True:
            key = d.strftime("%Y-%m-%d")
            day = habits_map.get(key) or {}
            if day.get(hid):
                streak += 1
                d = d - _td(days=1)
            else:
                break
            if streak > 365:
                break
        habit_streaks.append({"id": hid, "label": label, "streak": streak})

    # Filter archived tasks for list unless show_archived
    show_archived = (request.args.get("archived") or "") == "1"
    recent_captures = [c for c in (data.get("captures") or []) if not c.get("processed")][:8]
    for t in data.get("tasks") or []:
        t["_archived"] = bool(t.get("archived"))
    proj_map = {p.get("id"): (p.get("name") or "Project") for p in (data.get("projects") or [])}
    for t in data.get("tasks") or []:
        t["_project_name"] = proj_map.get(t.get("project_id") or "", "")
    for n in data.get("notes") or []:
        n["_project_name"] = proj_map.get(n.get("project_id") or "", "")
    recent_captures = [c for c in (data.get("captures") or []) if not c.get("processed")][:8]


    return render_template(
        "second_brain.html",
        module=mod,
        data=data,
        page=page,
        counts=counts,
        today=today,
        habit_today=habit_today,
        habit_date=habit_date,
        planner_today=planner_today,
        user=user,
        q=q,
        status_f=status_f,
        area_f=area_f,
        view=view,
        search_results=search_results,
        habit_streaks=habit_streaks,
        show_archived=show_archived,
        recent_captures=recent_captures,
        site_name=site.get("site_name") or "Portfolio SaaS",
        openai_configured=bool(resolve_ai_api_key(((data.get("settings") or {}).get("openai_user_key") or "").strip())[0]),
    )



@app.route("/os/second-brain/api/search")
@login_required
def second_brain_search_api():
    user = _sb_guard()
    if not user:
        return jsonify({"ok": False, "results": []}), 403
    data = load_second_brain(session["user"])
    q = (request.args.get("q") or "").strip().lower()
    results = []
    if not q or len(q) < 1:
        return jsonify({"ok": True, "results": []})

    def hit(kind, title, snippet, page, rid=""):
        results.append({
            "kind": kind,
            "title": title or "",
            "snippet": (snippet or "")[:160],
            "href": url_for("second_brain", page=page),
            "id": rid or "",
        })

    for c in data.get("captures") or []:
        if q in (c.get("title") or "").lower():
            hit("Capture", c.get("title"), c.get("type"), "capture", c.get("id"))
    for t in data.get("tasks") or []:
        blob = " ".join([t.get("title") or "", t.get("status") or "", t.get("context") or ""]).lower()
        if q in blob:
            hit("Task", t.get("title"), t.get("status"), "tasks", t.get("id"))
    for p in data.get("projects") or []:
        blob = " ".join([p.get("name") or "", p.get("notes") or "", p.get("area") or ""]).lower()
        if q in blob:
            hit("Project", p.get("name"), p.get("area"), "projects", p.get("id"))
    for g in data.get("goals") or []:
        blob = " ".join([g.get("title") or "", g.get("why") or "", g.get("category") or ""]).lower()
        if q in blob:
            hit("Goal", g.get("title"), g.get("category"), "goals", g.get("id"))
    for n in data.get("notes") or []:
        blob = " ".join([n.get("title") or "", n.get("body") or "", n.get("type") or ""]).lower()
        if q in blob:
            hit("Note", n.get("title"), (n.get("body") or "")[:120], "notes", n.get("id"))
    for c in data.get("content_ideas") or []:
        blob = " ".join([c.get("idea") or "", c.get("hook") or "", c.get("status") or ""]).lower()
        if q in blob:
            hit("Content", c.get("idea"), c.get("status"), "content", c.get("id"))
    for r in data.get("resources") or []:
        blob = " ".join([r.get("name") or "", r.get("link") or "", r.get("category") or ""]).lower()
        if q in blob:
            hit("Resource", r.get("name"), r.get("link"), "resources", r.get("id"))
    # group by kind for command-palette UI
    order = ["Task", "Note", "Project", "Goal", "Capture", "Content", "Resource"]
    grouped = []
    by_kind = {}
    for r in results:
        by_kind.setdefault(r["kind"], []).append(r)
    for k in order:
        for r in by_kind.get(k, []):
            grouped.append(r)
    for k, rows in by_kind.items():
        if k not in order:
            grouped.extend(rows)
    return jsonify({"ok": True, "results": grouped[:50]})


@app.route("/os/second-brain/action", methods=["POST"])
@login_required
def second_brain_action():
    user = _sb_guard()
    if not user:
        flash("Module locked", "warning")
        return redirect(url_for("subscription_page"))
    username = session["user"]
    data = load_second_brain(username)
    action = (request.form.get("action") or "").strip()
    page = (request.form.get("page") or "home").strip()

    def back(extra=None):
        save_second_brain(username, data)
        want_json = (
            request.form.get("xhr") == "1"
            or request.headers.get("X-Requested-With") == "XMLHttpRequest"
            or (request.accept_mimetypes.best == "application/json")
        )
        if want_json:
            payload = {"ok": True, "page": page, "counts": sb_counts(data)}
            if extra and isinstance(extra, dict):
                payload.update(extra)
            return jsonify(payload)
        return redirect(url_for("second_brain", page=page))

    if action == "set_focus":
        data["daily_focus"] = (request.form.get("daily_focus") or "").strip()[:500]
        return back()

    if action == "add_capture":
        title = (request.form.get("title") or "").strip()
        ctype = (request.form.get("type") or "Thought").strip()
        item = None
        if title:
            item = {
                "id": _sb_id(),
                "title": title[:2000],
                "type": ctype if ctype in ("Thought", "Task", "Idea", "Link", "Question") else "Thought",
                "processed": False,
                "captured": datetime.now().isoformat(),
            }
            data.setdefault("captures", []).insert(0, item)
        save_second_brain(username, data)
        # JSON only for real AJAX (header) — never for normal form post (avoids raw JSON page)
        is_ajax = (
            request.headers.get("X-Requested-With") == "XMLHttpRequest"
            or "application/json" in (request.headers.get("Accept") or "")
        )
        if is_ajax:
            unprocessed = sum(1 for c in (data.get("captures") or []) if not c.get("processed"))
            return jsonify({
                "ok": True,
                "item": item,
                "inbox": unprocessed,
                "counts": {"inbox": unprocessed},
                "recent": [
                    {"id": c.get("id"), "title": c.get("title"), "type": c.get("type"), "captured": c.get("captured")}
                    for c in (data.get("captures") or [])[:8]
                    if not c.get("processed")
                ],
            })
        flash("Captured", "success")
        return redirect(url_for("second_brain", page=page or "home"))

    if action == "mark_capture_done":
        iid = request.form.get("item_id")
        for c in data.get("captures") or []:
            if c.get("id") == iid:
                c["processed"] = True
                break
        return back()

    if action == "toggle_capture_processed":
        iid = request.form.get("item_id")
        for c in data.get("captures") or []:
            if c.get("id") == iid:
                c["processed"] = not bool(c.get("processed"))
                break
        return back()

    if action == "delete_capture":
        iid = request.form.get("item_id")
        data["captures"] = [x for x in data.get("captures") or [] if x.get("id") != iid]
        return back()

    if action == "capture_to_task":
        iid = request.form.get("item_id")
        item = next((x for x in data.get("captures") or [] if x.get("id") == iid), None)
        if item:
            data.setdefault("tasks", []).insert(0, {
                "id": _sb_id(),
                "title": item.get("title") or "",
                "status": "Not started",
                "priority": "Medium",
                "due": "",
                "project_id": "",
                "context": "Quick Win",
                "created_at": datetime.now().isoformat(),
            })
            item["processed"] = True
        return back()

    if action == "capture_to_note":
        iid = request.form.get("item_id")
        item = next((x for x in data.get("captures") or [] if x.get("id") == iid), None)
        if item:
            data.setdefault("notes", []).insert(0, {
                "id": _sb_id(),
                "title": (item.get("title") or "")[:80],
                "body": item.get("title") or "",
                "type": "Idea",
                "tags": [],
                "project_id": "",
                "favorite": False,
                "created": datetime.now().isoformat(),
            })
            item["processed"] = True
        return back()

    if action == "add_task":
        title = (request.form.get("title") or "").strip()
        if title:
            data.setdefault("tasks", []).insert(0, {
                "id": _sb_id(),
                "title": title[:300],
                "status": (request.form.get("status") or "Not started").strip(),
                "priority": (request.form.get("priority") or "Medium").strip(),
                "due": (request.form.get("due") or "").strip(),
                "project_id": (request.form.get("project_id") or "").strip(),
                "context": (request.form.get("context") or "Quick Win").strip(),
                "tags": [x.strip() for x in (request.form.get("tags") or "").split(",") if x.strip()][:12],
                "recur": (request.form.get("recur") or "none").strip().lower(),  # none|daily|weekly|monthly
                "archived": False,
                "created_at": datetime.now().isoformat(),
            })
        return back()

    if action == "update_task":
        tid = request.form.get("item_id")
        for t in data.get("tasks") or []:
            if t.get("id") == tid:
                if request.form.get("title") is not None:
                    t["title"] = (request.form.get("title") or t.get("title") or "")[:300]
                if request.form.get("status"):
                    t["status"] = request.form.get("status")
                if request.form.get("priority"):
                    t["priority"] = request.form.get("priority")
                if "due" in request.form:
                    t["due"] = request.form.get("due") or ""
                if "project_id" in request.form:
                    t["project_id"] = request.form.get("project_id") or ""
                if request.form.get("context"):
                    t["context"] = request.form.get("context")
                break
        return back()

    if action == "toggle_task_done":
        tid = request.form.get("item_id")
        for t in data.get("tasks") or []:
            if t.get("id") == tid:
                if (t.get("status") or "") == "Done":
                    t["status"] = "Not started"
                else:
                    t["status"] = "Done"
                break
        return back()

    if action == "archive_task":
        tid = request.form.get("item_id")
        for t in data.get("tasks") or []:
            if t.get("id") == tid:
                t["archived"] = True
                t["status"] = t.get("status") or "Done"
                break
        return back()

    if action == "unarchive_task":
        tid = request.form.get("item_id")
        for t in data.get("tasks") or []:
            if t.get("id") == tid:
                t["archived"] = False
                break
        return back()

    if action == "duplicate_task":
        tid = request.form.get("item_id")
        for t in data.get("tasks") or []:
            if t.get("id") == tid:
                clone = dict(t)
                clone["id"] = _sb_id()
                clone["title"] = (t.get("title") or "") + " (copy)"
                clone["status"] = "Not started"
                clone["archived"] = False
                clone["created_at"] = datetime.now().isoformat()
                data.setdefault("tasks", []).insert(0, clone)
                break
        return back()

    if action == "delete_task":
        tid = request.form.get("item_id")
        data["tasks"] = [x for x in data.get("tasks") or [] if x.get("id") != tid]
        return back()

    if action == "bulk_tasks":
        ids = request.form.getlist("task_ids") or []
        op = (request.form.get("bulk_op") or "").strip()
        tasks = data.get("tasks") or []
        if op == "complete":
            for t in tasks:
                if t.get("id") in ids:
                    t["status"] = "Done"
        elif op == "archive":
            for t in tasks:
                if t.get("id") in ids:
                    t["archived"] = True
        elif op == "delete":
            data["tasks"] = [t for t in tasks if t.get("id") not in ids]
        elif op == "todo":
            for t in tasks:
                if t.get("id") in ids:
                    t["status"] = "Not started"
                    t["archived"] = False
        flash(f"Bulk {op or 'update'}: {len(ids)} task(s)", "success")
        return back()

    if action == "process_recurring_tasks":
        from datetime import timedelta as _td
        today = datetime.now().date()
        created = 0
        for t in list(data.get("tasks") or []):
            recur = (t.get("recur") or "none").lower()
            if recur == "none" or t.get("archived"):
                continue
            if (t.get("status") or "") != "Done":
                continue
            last = (t.get("last_recurred") or t.get("due") or "")[:10]
            try:
                base_d = datetime.strptime(last, "%Y-%m-%d").date() if last else today
            except Exception:
                base_d = today
            if recur == "daily":
                nxt = base_d + _td(days=1)
            elif recur == "weekly":
                nxt = base_d + _td(days=7)
            elif recur == "monthly":
                nxt = base_d + _td(days=30)
            else:
                continue
            if nxt > today + _td(days=1):
                continue
            # spawn next occurrence
            clone = dict(t)
            clone["id"] = _sb_id()
            clone["status"] = "Not started"
            clone["due"] = nxt.strftime("%Y-%m-%d")
            clone["archived"] = False
            clone["created_at"] = datetime.now().isoformat()
            clone.pop("last_recurred", None)
            data.setdefault("tasks", []).insert(0, clone)
            t["last_recurred"] = today.strftime("%Y-%m-%d")
            created += 1
        flash(f"Recurring tasks processed: {created} new", "success")
        return back()

    if action == "apply_workspace_template":
        tid = (request.form.get("template_id") or "").strip()
        tpls = data.get("workspace_templates") or DEFAULT_SECOND_BRAIN.get("workspace_templates") or []
        tpl = next((x for x in tpls if x.get("id") == tid), None)
        if not tpl:
            flash("Template not found", "warning")
            return back("templates")
        for title in (tpl.get("tasks") or []):
            data.setdefault("tasks", []).insert(0, {
                "id": _sb_id(),
                "title": title[:300],
                "status": "Not started",
                "priority": "Medium",
                "due": "",
                "project_id": "",
                "context": "Template",
                "tags": ["template"],
                "recur": "none",
                "archived": False,
                "created_at": datetime.now().isoformat(),
            })
        for title in (tpl.get("notes") or []):
            data.setdefault("notes", []).insert(0, {
                "id": _sb_id(),
                "title": title[:300],
                "body": "",
                "tags": ["template"],
                "project_id": "",
                "favorite": False,
                "created": datetime.now().isoformat(),
            })
        flash(f"Applied template: {tpl.get('name')}", "success")
        return back("templates")

    if action == "add_project":
        name = (request.form.get("name") or "").strip()
        if name:
            data.setdefault("projects", []).insert(0, {
                "id": _sb_id(),
                "name": name[:200],
                "area": (request.form.get("area") or "Work").strip(),
                "status": _sb_norm_project_status(request.form.get("status")),
                "priority": (request.form.get("priority") or "Medium").strip(),
                "timeline": (request.form.get("timeline") or "").strip(),
                "notes": (request.form.get("notes") or "").strip()[:5000],
                "goal_ids": [],
                "created_at": datetime.now().isoformat(),
            })
        return back()

    if action == "update_project":
        pid = request.form.get("item_id")
        for p in data.get("projects") or []:
            if p.get("id") == pid:
                for field in ("name", "area", "priority", "timeline", "notes"):
                    if field in request.form:
                        p[field] = (request.form.get(field) or "").strip()
                if "status" in request.form:
                    p["status"] = _sb_norm_project_status(request.form.get("status"))
                break
        return back()

    if action == "delete_project":
        pid = request.form.get("item_id")
        data["projects"] = [x for x in data.get("projects") or [] if x.get("id") != pid]
        return back()

    if action == "add_goal":
        title = (request.form.get("title") or "").strip()
        if title:
            try:
                prog = int(request.form.get("progress") or 0)
            except ValueError:
                prog = 0
            data.setdefault("goals", []).insert(0, {
                "id": _sb_id(),
                "title": title[:200],
                "category": (request.form.get("category") or "Personal").strip(),
                "progress": max(0, min(100, prog)),
                "status": (request.form.get("status") or "Not Started").strip(),
                "target_date": (request.form.get("target_date") or "").strip(),
                "why": (request.form.get("why") or "").strip()[:2000],
                "project_ids": [],
                "created_at": datetime.now().isoformat(),
            })
        return back()

    if action == "update_goal":
        gid = request.form.get("item_id")
        for g in data.get("goals") or []:
            if g.get("id") == gid:
                if "title" in request.form:
                    g["title"] = (request.form.get("title") or g["title"])[:200]
                if "category" in request.form:
                    g["category"] = request.form.get("category") or g.get("category")
                if "status" in request.form:
                    g["status"] = request.form.get("status") or g.get("status")
                if "target_date" in request.form:
                    g["target_date"] = request.form.get("target_date") or ""
                if "why" in request.form:
                    g["why"] = (request.form.get("why") or "")[:2000]
                if "progress" in request.form:
                    try:
                        g["progress"] = max(0, min(100, int(request.form.get("progress") or 0)))
                    except ValueError:
                        pass
                break
        return back()

    if action == "delete_goal":
        gid = request.form.get("item_id")
        data["goals"] = [x for x in data.get("goals") or [] if x.get("id") != gid]
        return back()


    if action == "toggle_habit":
        day = (request.form.get("date") or _sb_today()).strip()
        hid = (request.form.get("habit_id") or "").strip()
        entry = dict(data.get("habits", {}).get(day) or {})
        # preserve non-habit keys carefully
        defs = {h["id"] for h in (data.get("habit_defs") or [])}
        current = bool(entry.get(hid))
        entry[hid] = not current
        score = sum(1 for d in defs if entry.get(d))
        entry["score"] = score
        try:
            entry["day"] = datetime.strptime(day, "%Y-%m-%d").strftime("%A")
        except Exception:
            entry["day"] = ""
        data.setdefault("habits", {})[day] = entry
        return back({"habit_id": hid, "on": entry[hid], "score": score, "day": day})

    if action == "save_habits":
        day = (request.form.get("date") or _sb_today()).strip()
        entry = {}
        score = 0
        for h in data.get("habit_defs") or []:
            hid = h["id"]
            on = request.form.get(f"habit_{hid}") == "1"
            entry[hid] = on
            if on:
                score += 1
        entry["score"] = score
        entry["day"] = datetime.strptime(day, "%Y-%m-%d").strftime("%A") if day else ""
        data.setdefault("habits", {})[day] = entry
        return back()

    if action == "delete_habit_day":
        day = (request.form.get("date") or "").strip()
        if day and day in (data.get("habits") or {}):
            del data["habits"][day]
        return back()

    if action == "save_planner":
        day = (request.form.get("date") or _sb_today()).strip()
        data.setdefault("planners", {})[day] = {
            "date": day,
            "day": datetime.strptime(day, "%Y-%m-%d").strftime("%A") if day else "",
            "energy": (request.form.get("energy") or "Medium").strip(),
            "gratitude": (request.form.get("gratitude") or "").strip()[:2000],
            "schedule": (request.form.get("schedule") or "").strip()[:5000],
            "top3": (request.form.get("top3") or "").strip()[:2000],
            "wins": (request.form.get("wins") or "").strip()[:2000],
        }
        return back()

    if action == "add_weekly_review":
        data.setdefault("weekly_reviews", []).insert(0, {
            "id": _sb_id(),
            "week": (request.form.get("week") or "").strip()[:80],
            "week_of": (request.form.get("week_of") or "").strip(),
            "focus": (request.form.get("focus") or "").strip()[:2000],
            "wins": (request.form.get("wins") or "").strip()[:5000],
            "lessons": (request.form.get("lessons") or "").strip()[:5000],
            "next_plan": (request.form.get("next_plan") or "").strip()[:5000],
            "rating": (request.form.get("rating") or "Good").strip(),
            "created_at": datetime.now().isoformat(),
        })
        return back()

    if action == "delete_weekly_review":
        rid = request.form.get("item_id")
        data["weekly_reviews"] = [x for x in data.get("weekly_reviews") or [] if x.get("id") != rid]
        return back()

    if action == "update_weekly_review":
        rid = request.form.get("item_id")
        for r in data.get("weekly_reviews") or []:
            if r.get("id") == rid:
                for field in ("week", "week_of", "rating", "focus", "wins", "lessons", "next_plan"):
                    if field in request.form:
                        r[field] = (request.form.get(field) or "").strip()
                break
        return back()

    if action == "add_note":
        title = (request.form.get("title") or "").strip()
        body = (request.form.get("body") or "").strip()
        if title or body:
            tags_raw = (request.form.get("tags") or "").strip()
            tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
            data.setdefault("notes", []).insert(0, {
                "id": _sb_id(),
                "title": title[:200] or "Untitled",
                "body": body[:20000],
                "type": (request.form.get("type") or "Idea").strip(),
                "tags": tags,
                "project_id": (request.form.get("project_id") or "").strip(),
                "favorite": request.form.get("favorite") in ("1", "on", "true", "True"),
                "created": datetime.now().isoformat(),
            })
        return back()

    if action == "delete_note":
        nid = request.form.get("item_id")
        data["notes"] = [x for x in data.get("notes") or [] if x.get("id") != nid]
        return back()

    if action == "toggle_note_fav":
        nid = request.form.get("item_id")
        for n in data.get("notes") or []:
            if n.get("id") == nid:
                n["favorite"] = not bool(n.get("favorite"))
                break
        return back()

    if action == "add_content":
        idea = (request.form.get("idea") or "").strip()
        if idea:
            platforms = request.form.getlist("platform") or []
            data.setdefault("content_ideas", []).insert(0, {
                "id": _sb_id(),
                "idea": idea[:500],
                "format": (request.form.get("format") or "Post").strip(),
                "platforms": platforms,
                "hook": (request.form.get("hook") or "").strip()[:1000],
                "priority": (request.form.get("priority") or "Medium").strip(),
                "publish_date": (request.form.get("publish_date") or "").strip(),
                "status": (request.form.get("status") or "Inbox").strip(),
                "created_at": datetime.now().isoformat(),
            })
        return back()

    if action == "move_content":
        cid = request.form.get("item_id")
        status = (request.form.get("status") or "Inbox").strip()
        for c in data.get("content_ideas") or []:
            if c.get("id") == cid:
                c["status"] = status
                break
        return back()

    if action == "delete_content":
        cid = request.form.get("item_id")
        data["content_ideas"] = [x for x in data.get("content_ideas") or [] if x.get("id") != cid]
        return back()

    if action == "add_resource":
        name = (request.form.get("name") or "").strip()
        link = (request.form.get("link") or "").strip()
        if name:
            tags_raw = (request.form.get("tags") or "").strip()
            data.setdefault("resources", []).insert(0, {
                "id": _sb_id(),
                "name": name[:200],
                "link": link[:500],
                "category": (request.form.get("category") or "Article").strip(),
                "rating": (request.form.get("rating") or "3-Useful").strip(),
                "status": (request.form.get("status") or "To Review").strip(),
                "tags": [t.strip() for t in tags_raw.split(",") if t.strip()],
                "created_at": datetime.now().isoformat(),
            })
        return back()

    if action == "delete_resource":
        rid = request.form.get("item_id")
        data["resources"] = [x for x in data.get("resources") or [] if x.get("id") != rid]
        return back()


    if action == "update_note":
        nid = request.form.get("item_id")
        for n in data.get("notes") or []:
            if n.get("id") == nid:
                if "title" in request.form:
                    n["title"] = (request.form.get("title") or n.get("title") or "")[:200]
                if "body" in request.form:
                    n["body"] = (request.form.get("body") or "")[:20000]
                if "type" in request.form:
                    n["type"] = (request.form.get("type") or n.get("type") or "Idea").strip()
                if "tags" in request.form:
                    tags_raw = (request.form.get("tags") or "").strip()
                    n["tags"] = [t.strip() for t in tags_raw.split(",") if t.strip()]
                if "project_id" in request.form:
                    n["project_id"] = (request.form.get("project_id") or "").strip()
                n["updated"] = datetime.now().isoformat()
                break
        return back()

    if action == "link_goal_project":
        gid = request.form.get("goal_id")
        pid = request.form.get("project_id")
        for g in data.get("goals") or []:
            if g.get("id") == gid:
                ids = list(g.get("project_ids") or [])
                if pid and pid not in ids:
                    ids.append(pid)
                g["project_ids"] = ids
                break
        for p in data.get("projects") or []:
            if p.get("id") == pid:
                ids = list(p.get("goal_ids") or [])
                if gid and gid not in ids:
                    ids.append(gid)
                p["goal_ids"] = ids
                break
        return back()

    if action == "unlink_goal_project":
        gid = request.form.get("goal_id")
        pid = request.form.get("project_id")
        for g in data.get("goals") or []:
            if g.get("id") == gid:
                g["project_ids"] = [x for x in (g.get("project_ids") or []) if x != pid]
                break
        for p in data.get("projects") or []:
            if p.get("id") == pid:
                p["goal_ids"] = [x for x in (p.get("goal_ids") or []) if x != gid]
                break
        return back()

    if action == "update_resource":
        rid = request.form.get("item_id")
        for r in data.get("resources") or []:
            if r.get("id") == rid:
                for field in ("name", "link", "category", "rating", "status"):
                    if field in request.form:
                        r[field] = (request.form.get(field) or "").strip()
                if "tags" in request.form:
                    tags_raw = (request.form.get("tags") or "").strip()
                    r["tags"] = [t.strip() for t in tags_raw.split(",") if t.strip()]
                break
        return back()

    if action == "update_content":
        cid = request.form.get("item_id")
        for c in data.get("content_ideas") or []:
            if c.get("id") == cid:
                for field in ("idea", "format", "hook", "priority", "publish_date", "status"):
                    if field in request.form:
                        c[field] = (request.form.get(field) or "").strip()
                if "platform" in request.form:
                    c["platforms"] = request.form.getlist("platform")
                break
        return back()

    if action == "save_sb_preferences":
        s = data.get("settings")
        if not isinstance(s, dict):
            s = {}
        s["timezone"] = (request.form.get("timezone") or "Asia/Dhaka").strip()[:60]
        try:
            s["week_starts_on"] = int(request.form.get("week_starts_on") or 6)
        except Exception:
            s["week_starts_on"] = 6
        if s["week_starts_on"] not in (0, 1, 6):
            s["week_starts_on"] = 6
        dv = (request.form.get("default_view") or "home").strip().lower()
        # accept UI values + aliases
        allowed_dv = {
            "home", "dashboard", "planner", "daily", "daily-planner",
            "tasks", "captures", "capture", "goals", "notes",
        }
        if dv not in allowed_dv:
            dv = "home"
        # normalize to canonical keys used by _sb_resolve_default_page
        if dv in ("dashboard", "overview"):
            dv = "home"
        if dv in ("daily", "daily-planner"):
            dv = "planner"
        if dv == "capture":
            dv = "captures"
        s["default_view"] = dv
        data["settings"] = s
        save_second_brain(username, data)
        flash("Preferences saved — next time you open Second Brain you will land on: " + (
            {"home": "Dashboard", "planner": "Daily Planner", "tasks": "Tasks",
             "captures": "Quick Capture", "goals": "Goals", "notes": "Notes"}.get(dv, dv)
        ), "success")
        return redirect(url_for("second_brain", page="settings"))

    if action == "save_sb_openai_key":
        key = (request.form.get("openai_user_key") or "").strip()
        s = data.setdefault("settings", {})
        if key.lower() in ("clear", "remove", "-"):
            s.pop("openai_user_key", None)
            flash("Your OpenAI API key was removed", "success")
        elif key:
            s["openai_user_key"] = key[:200]
            flash("Your OpenAI API key was saved (only in your workspace)", "success")
        else:
            flash("No change to API key", "success")
        return back()

    if action == "export_json":
        save_second_brain(username, data)
        from flask import Response
        payload = json.dumps(data, indent=2, ensure_ascii=False)
        return Response(
            payload,
            mimetype="application/json",
            headers={"Content-Disposition": f"attachment; filename=second-brain-{username}.json"},
        )

    if action == "import_json":
        f = request.files.get("file")
        if f and f.filename:
            try:
                incoming = json.loads(f.read().decode("utf-8"))
                if not isinstance(incoming, dict):
                    flash("Invalid JSON structure", "danger")
                else:
                    # merge lists by id, prefer incoming
                    for key in ("captures", "tasks", "projects", "goals", "notes", "content_ideas", "resources", "weekly_reviews"):
                        if isinstance(incoming.get(key), list):
                            existing = {x.get("id"): x for x in data.get(key) or [] if x.get("id")}
                            for row in incoming[key]:
                                if isinstance(row, dict) and row.get("id"):
                                    existing[row["id"]] = row
                            data[key] = list(existing.values())
                    if isinstance(incoming.get("habits"), dict):
                        data.setdefault("habits", {}).update(incoming["habits"])
                    if isinstance(incoming.get("planners"), dict):
                        data.setdefault("planners", {}).update(incoming["planners"])
                    if "daily_focus" in incoming:
                        data["daily_focus"] = incoming.get("daily_focus") or data.get("daily_focus")
                    flash("Import merged successfully", "success")
            except Exception as e:
                flash(f"Import failed: {e}", "danger")
        return back()

    save_second_brain(username, data)
    return redirect(url_for("second_brain", page=page))


# ==================== CV / RESUME BUILDER ====================
DEFAULT_CV_DOC = {
    "template_id": "",
    "doc_type": "resume",
    "language": "en",
    "format": "us_standard",
    "full_name": "",
    "phone": "",
    "email": "",
    "address": "",
    "web": "",
    "photo": "",
    "education_raw": "",
    "personal_raw": "",
    "magic_box": "",
    "ai_generated_headline": "",
    "ai_about": "",
    "ai_experience": [],
    "ai_skills": [],
    "ai_languages": [],
    "ai_education": [],
    "ai_status": "idle",
    "updated_at": "",
}

CV_TEMPLATES = []  # filled from cv_pack/runtime_templates.json at startup


def load_cv_templates():
    """Load pack manifest templates (20 designs). Fallback to empty list."""
    global CV_TEMPLATES
    path = Path(__file__).resolve().parent / "cv_pack" / "runtime_templates.json"
    if not path.exists():
        path = Path(__file__).resolve().parent / "cv_pack" / "template_manifest.json"
    try:
        raw = json.loads(path.read_text())
        out = []
        for t in raw:
            kind = t.get("doc_type") or t.get("kind") or "resume"
            tid = t.get("id") or ""
            out.append({
                "id": tid,
                "name": t.get("name") or tid,
                "doc_type": kind,
                "desc": t.get("desc") or t.get("description") or "",
                "preview_color": t.get("preview_color") or "#16223a",
                "layout": t.get("layout") or kind,
                "preview": t.get("preview") or f"previews/{tid}.html",
                "template": t.get("template") or f"templates/{kind}/{tid}.html",
                "pagePolicy": t.get("pagePolicy") or (
                    "one_page_compact" if kind == "resume" else "multi_page_content_flow"
                ),
            })
        CV_TEMPLATES = out
    except Exception as e:
        print("CV template load error:", e)
        CV_TEMPLATES = []
    return CV_TEMPLATES


load_cv_templates()



def build_profile_from_doc(doc):
    """Map saved CV doc + AI slots to pack profile. Prefer AI; fall back to form fields."""
    exp = []
    for e in (doc.get("ai_experience") or []):
        if isinstance(e, dict):
            bullets = e.get("bullets") or []
            if isinstance(bullets, str):
                bullets = [bullets]
            if not bullets and e.get("raw_description"):
                bullets = [e["raw_description"]]
            start = (e.get("start") or "").strip()
            end = (e.get("end") or "").strip()
            if e.get("present"):
                dates = (start + " – Present").strip(" –")
            elif start or end:
                dates = (start + " – " + end).strip(" –")
            else:
                dates = (e.get("dates") or "").strip()
            exp.append({
                "title": (e.get("title") or "").strip(),
                "employer": (e.get("company") or e.get("employer") or "").strip(),
                "dates": dates,
                "bullets": [str(b).strip() for b in bullets if str(b).strip()],
            })
        elif isinstance(e, (list, tuple)) and len(e) >= 3:
            exp.append({
                "title": str(e[0]), "employer": str(e[1]), "dates": str(e[2]),
                "bullets": list(e[3]) if len(e) > 3 and isinstance(e[3], list) else ([str(e[3])] if len(e) > 3 else []),
            })

    edu = []
    for e in (doc.get("ai_education") or []):
        if isinstance(e, dict):
            edu.append({
                "title": (e.get("degree") or e.get("title") or "").strip(),
                "institution": (e.get("school") or e.get("institution") or "").strip(),
                "dates": (e.get("year") or e.get("dates") or "").strip(),
            })
        elif isinstance(e, (list, tuple)) and len(e) >= 2:
            edu.append({"title": str(e[0]), "institution": str(e[1]), "dates": str(e[2]) if len(e) > 2 else ""})
    if not edu and doc.get("education_raw"):
        # Parse lines like "HSC 2021, School, Science"
        for line in str(doc["education_raw"]).splitlines():
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 2:
                # try extract year from first token
                title = parts[0]
                inst = parts[1] if len(parts) > 1 else ""
                extra = ", ".join(parts[2:]) if len(parts) > 2 else ""
                if extra:
                    title = title + " · " + extra
                edu.append({"title": title, "institution": inst, "dates": ""})
            else:
                edu.append({"title": line, "institution": "", "dates": ""})

    skills = []
    for s in (doc.get("ai_skills") or []):
        if isinstance(s, dict):
            skills.append((s.get("name") or "").strip())
        else:
            skills.append(str(s).strip())
    skills = [x for x in skills if x]

    langs = []
    for L in (doc.get("ai_languages") or []):
        if isinstance(L, dict):
            nm = (L.get("name") or "").strip()
            lv = (L.get("level") or "").strip()
            langs.append(f"{nm} · {lv}".strip(" ·") if nm else "")
        else:
            langs.append(str(L).strip())
    langs = [x for x in langs if x]

    awards = []
    for a in (doc.get("ai_awards") or []):
        if isinstance(a, dict):
            awards.append((a.get("title") or a.get("name") or str(a)).strip())
        else:
            awards.append(str(a).strip())
    awards = [x for x in awards if x]

    name = (doc.get("full_name") or "").strip() or "Your Name"
    return {
        "name": name,
        "role": (doc.get("ai_generated_headline") or "").strip() or "Professional",
        "email": (doc.get("email") or "").strip(),
        "phone": (doc.get("phone") or "").strip(),
        "location": (doc.get("address") or "").strip(),
        "website": (doc.get("web") or "").strip(),
        "about": (doc.get("ai_about") or "").strip(),
        "photo": (doc.get("photo") or "").strip(),
        "skills": skills,
        "languages": langs,
        "education": edu,
        "experience": exp,
        "awards": awards,
        "personal": (doc.get("personal_raw") or "").strip(),
    }


def _esc(s):
    return (
        str(s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _name_parts(name):
    parts = [p for p in str(name or "").strip().split() if p]
    if not parts:
        return ["YOUR", "NAME"]
    if len(parts) == 1:
        return [parts[0].upper(), ""]
    # first token + rest
    return [parts[0].upper(), " ".join(parts[1:]).upper()]


def _initials(name):
    parts = [p for p in str(name or "").split() if p]
    if not parts:
        return "YN"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()



def fill_pack_template_html(html, profile):
    """
    Replace ALL demo sample_profile content with user/AI profile.
    Handles stacked names, experience (title + date spacing), education, skills, languages.
    Injects print CSS so toolbar is hidden and pages break cleanly.
    """
    name = profile.get("name") or "Your Name"
    role = profile.get("role") or "Professional"
    first, last = _name_parts(name)
    initials = _initials(name)

    # --- Name ---
    for demo in ("ALEX MORGAN", "Alex Morgan", "ALEX ROBERT", "Alex Robert"):
        html = html.replace(demo, _esc(name.upper() if demo.isupper() else name))
    html = html.replace(">ALEX<", ">" + _esc(first) + "<")
    html = html.replace(">MORGAN<", ">" + _esc(last or first) + "<")
    html = html.replace(">Alex<", ">" + _esc(first.title()) + "<")
    html = html.replace(">Morgan<", ">" + _esc((last or first).title()) + "<")
    html = html.replace(">AM<", ">" + _esc(initials) + "<")
    html = html.replace(">AR<", ">" + _esc(initials) + "<")

    # Role
    for demo_role in (
        "PRODUCT DESIGNER", "Product Designer",
        "CONTRACTOR & COMPUTER OPERATOR", "Contractor & Computer Operator",
        "SENIOR PRODUCT DESIGNER", "Senior Product Designer",
    ):
        html = html.replace(demo_role, _esc(role.upper() if demo_role.isupper() else role))

    # Contact
    if profile.get("email"):
        html = html.replace("alex.morgan@example.com", _esc(profile["email"]))
        html = html.replace("alex.robert@example.com", _esc(profile["email"]))
    if profile.get("phone"):
        html = html.replace("+1 555 014 2086", _esc(profile["phone"]))
        html = html.replace("+1 555 0100", _esc(profile["phone"]))
    if profile.get("location"):
        html = html.replace("Brooklyn, NY", _esc(profile["location"]))
        html = html.replace("New York, NY", _esc(profile["location"]))
    if profile.get("website"):
        html = html.replace("alexmorgan.design", _esc(profile["website"]))
        html = html.replace("alexrobert.design", _esc(profile["website"]))

    # About — short only
    about = (profile.get("about") or "").strip()
    sample_abouts = [
        "Product designer with 7 years of experience turning complex workflows into clear, accessible digital products. Partners with research, engineering, and business teams to ship measurable improvements.",
        "Product designer with 7 years of experience turning complex workflows into clear, accessible digital products.",
    ]
    if about:
        for sa in sample_abouts:
            if sa in html:
                html = html.replace(sa, _esc(about))
                break
        else:
            html = re.sub(
                r'(About Me|About|Profile|Summary)(</[^>]+>)([\s\S]{0,80}?)<p([^>]*)>[\s\S]*?</p>',
                lambda m: m.group(1) + m.group(2) + m.group(3) + "<p" + m.group(4) + ">" + _esc(about) + "</p>",
                html,
                count=1,
                flags=re.I,
            )

    # Photo
    if profile.get("photo"):
        ph = _esc(profile["photo"])
        html = re.sub(
            r'class="([^"]*\bphoto\b[^"]*)"',
            lambda m: f'class="{m.group(1)}" style="background-image:url(\'{ph}\');background-size:cover;background-position:center;"',
            html,
            count=1,
        )
        html = re.sub(
            r'(<img[^>]*class="[^"]*photo[^"]*"[^>]*src=")[^"]*"',
            r'\1' + ph + '"',
            html,
            count=1,
        )
        html = re.sub(r'(class="[^"]*initials[^"]*"[^>]*>)[^<]*', r'\1', html, count=2)

    # Skills
    demo_skills = [
        "Product strategy", "UX research", "Interaction design", "Figma",
        "Prototyping", "Design systems", "Accessibility", "Workshop facilitation",
        "UI Design", "Wireframing", "User Research",
    ]
    user_skills = profile.get("skills") or []
    if user_skills:
        for i, demo in enumerate(demo_skills):
            if demo in html:
                rep = user_skills[i] if i < len(user_skills) else ""
                html = html.replace(demo, _esc(rep) if rep else "", 1)
        skills_html = "".join(f'<span class="skill-chip">{_esc(s)}</span> ' for s in user_skills)
        html = re.sub(
            r'(<div[^>]*class="[^"]*skills[^"]*"[^>]*>)([\s\S]*?)(</div>)',
            lambda m: m.group(1) + skills_html + m.group(3),
            html, count=1, flags=re.I,
        )

    # Languages
    demo_langs = [
        "English · Native", "Spanish · Professional",
        "English - Native", "Spanish - Professional",
    ]
    user_langs = profile.get("languages") or []
    if user_langs:
        for i, demo in enumerate(demo_langs):
            if demo in html and i < len(user_langs):
                html = html.replace(demo, _esc(user_langs[i]), 1)
        lang_html = "".join(f"<li>{_esc(L)}</li>" for L in user_langs)
        html = re.sub(
            r'(Languages</[^>]+>[\s\S]{0,60}?<ul[^>]*>)([\s\S]*?)(</ul>)',
            lambda m: m.group(1) + lang_html + m.group(3),
            html, count=1, flags=re.I,
        )

    # Education
    demo_edu_bits = [
        "BFA, Communication Design", "Northbridge University", "2012 – 2016", "2012 - 2016",
        "Certificate, Human-Centered Design", "City Design Lab", "2020",
    ]
    user_edu = profile.get("education") or []
    if user_edu:
        edu_html_parts = []
        for e in user_edu:
            title = e.get("title") or ""
            inst = e.get("institution") or ""
            dates = e.get("dates") or ""
            edu_html_parts.append(
                f'<div class="edu-item" style="margin-bottom:10px;page-break-inside:avoid;">'
                f'<strong>{_esc(title)}</strong>'
                + (f'<div>{_esc(inst)}</div>' if inst else "")
                + (f'<div class="dates" style="opacity:.75;font-size:.9em;">{_esc(dates)}</div>' if dates else "")
                + "</div>"
            )
        edu_block = "".join(edu_html_parts)
        html2, n = re.subn(
            r'(Education</[^>]+>)([\s\S]*?)(?=(Work Experience|Experience|Skills|Languages|Awards|Selected Awards|</aside>|</section>|</main>))',
            lambda m: m.group(1) + edu_block,
            html, count=1, flags=re.I,
        )
        if n:
            html = html2
        else:
            for bit in demo_edu_bits:
                if bit in html and user_edu:
                    html = html.replace(bit, _esc(user_edu[0].get("title") or ""), 1)

    # Experience — title, employer/location, dates RIGHT-aligned with proper spacing
    user_exp = profile.get("experience") or []
    if user_exp:
        exp_parts = []
        for e in user_exp:
            title = (e.get("title") or "").strip()
            employer = (e.get("employer") or "").strip()
            dates = (e.get("dates") or "").strip()
            # ensure space before dates if someone concatenated
            dates = dates.replace("–", "–").strip()
            bullets = e.get("bullets") or []
            bullets_html = "".join(f"<li>{_esc(b)}</li>" for b in bullets)
            exp_parts.append(
                f'<div class="job" style="margin-bottom:16px;page-break-inside:avoid;">'
                f'<div class="job-head" style="display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap;">'
                f'<strong style="flex:1 1 auto;">{_esc(title)}</strong>'
                f'<span class="dates" style="flex:0 0 auto;white-space:nowrap;opacity:.8;font-size:.92em;text-align:right;">{_esc(dates)}</span>'
                f'</div>'
                + (f'<div class="employer" style="opacity:.85;margin:2px 0 6px;">{_esc(employer)}</div>' if employer else "")
                + (f"<ul style=\"margin:4px 0 0 18px;padding:0;\">{bullets_html}</ul>" if bullets_html else "")
                + "</div>"
            )
        exp_block = "".join(exp_parts)
        html2, n = re.subn(
            r'((?:Work Experience|Experience|Employment)</[^>]+>)([\s\S]*?)(?=(Education|Skills|Languages|Awards|Selected Awards|Projects|</main>|</section>|</body>))',
            lambda m: m.group(1) + exp_block,
            html, count=1, flags=re.I,
        )
        if n:
            html = html2
        else:
            demo_jobs = [
                "Senior Product Designer", "Northstar Labs",
                "Product Designer", "Fieldwork Studio",
                "UX Designer", "Brightline Digital",
                "Design Intern", "Studio North",
                "Senior Contractor & Computer Operator",
                "Contractor & Computer Operator",
            ]
            for dj in demo_jobs:
                if dj in html and user_exp:
                    html = html.replace(dj, _esc(user_exp[0].get("title") or user_exp[0].get("employer") or ""), 1)

    # Awards — remove demo; hide section if empty
    demo_awards = ["Accessibility Champion · 2023", "Service Design shortlist · 2021"]
    user_awards = profile.get("awards") or []
    if user_awards:
        for i, da in enumerate(demo_awards):
            if da in html and i < len(user_awards):
                html = html.replace(da, _esc(user_awards[i]), 1)
    else:
        for da in demo_awards:
            html = html.replace(da, "")
        # hide empty awards block
        html = re.sub(
            r'((?:Selected\s+)?Awards</[^>]+>)([\s\S]*?)(?=(Education|Skills|Languages|Work Experience|Experience|Projects|</main>|</section>|</aside>|</body>))',
            r'',
            html, count=1, flags=re.I,
        )
        html = re.sub(r'<li>\s*[·\.\-–—]?\s*</li>', '', html)

    # Strip leftover demo intern block if still present
    for leftover in (
        "Design Intern", "Studio North",
        "Prepared prototypes and visual specifications for client reviews.",
        "Led redesign of account setup, raising completion by 24%.",
        "Built a shared component library adopted by four product teams.",
        "Improved accessibility through audit and remediation work.",
        "education and finance clients.",
        "education and finance clients",
        "Translated customer interviews into tested service flows.",
        "Partnered with engineering to ship responsive product features.",
        "Designed web experiences for education and finance clients.",
        "Improved accessibility through audit and remediation work",
    ):
        html = html.replace(leftover, "")
    # Remove orphan list items that only contain leftover fragments
    html = re.sub(r'<li>\s*(?:education and finance clients\.?|Improved accessibility[^<]*)\s*</li>', '', html, flags=re.I)

    # Fix concatenated title+year like "Contractor2016" -> "Contractor 2016"
    html = re.sub(r'([A-Za-z\)])((?:19|20)\d{2}\s*[–\-])', r'\1 \2', html)

    # Inject global print + layout CSS
    print_css = """
<style id="mfh-cv-print-css">
@media print {
  .mfh-cv-toolbar, .mfh-cv-toolbar * { display: none !important; }
  body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
}
.mfh-cv-toolbar { position: sticky; top: 0; z-index: 50; }
.job { page-break-inside: avoid; break-inside: avoid; }
.edu-item { page-break-inside: avoid; break-inside: avoid; }
.job-head { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.job-head .dates { white-space: nowrap; text-align: right; margin-left: auto; }
</style>
"""
    if "</head>" in html:
        html = html.replace("</head>", print_css + "</head>", 1)
    else:
        html = print_css + html

    return html


def pack_template_path(tpl_meta, use_preview=False):
    base = Path(__file__).resolve().parent / "cv_pack"
    rel = tpl_meta.get("preview") if use_preview else tpl_meta.get("template")
    if not rel:
        return None
    path = base / rel
    return path if path.exists() else None





def cv_path(username):
    return CVS_DIR / f"{username}.json"


def load_cv(username):
    path = cv_path(username)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for key, val in DEFAULT_CV_DOC.items():
                if key not in data:
                    data[key] = json.loads(json.dumps(val))
            return data
        except Exception:
            pass
    return json.loads(json.dumps(DEFAULT_CV_DOC))


def save_cv(username, data):
    CVS_DIR.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = datetime.now().isoformat()
    cv_path(username).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data



CL_TEMPLATES = []


def load_cl_templates():
    global CL_TEMPLATES
    path = Path(__file__).resolve().parent / "cl_pack" / "runtime_templates.json"
    if not path.exists():
        path = Path(__file__).resolve().parent / "cl_pack" / "template_manifest.json"
    try:
        raw = json.loads(path.read_text())
        out = []
        for t in raw:
            out.append({
                "id": t.get("id") or "",
                "name": t.get("name") or t.get("id") or "",
                "kind": "cover_letter",
                "desc": t.get("desc") or t.get("description") or "",
                "template": t.get("template") or "",
                "preview": t.get("preview") or "",
                "pagePolicy": t.get("pagePolicy") or "one_A4_page",
                "preview_color": t.get("preview_color") or "#0f172a",
            })
        CL_TEMPLATES = out
    except Exception as e:
        print("CL template load error:", e)
        CL_TEMPLATES = []
    return CL_TEMPLATES


load_cl_templates()

def call_openai_cover_letter(cv_doc, letter, api_key=None, provider=None, model=None):
    """Draft cover letter via Platform AI Brain (Gemini / OpenAI / Claude)."""
    profile = build_profile_from_doc(cv_doc)
    system = (
        'Write a professional cover letter as JSON only: {"paragraphs": ["p1", "p2", "p3"]}. '
        "STRICT RULES: "
        "1) Use ONLY skills, jobs, and facts from the applicant object. "
        "2) NEVER mention product strategy, UX research, interaction design, prototyping, accessibility audits, design systems, or any design-agency language unless the applicant's profile explicitly lists those skills. "
        "3) Match the applicant's real work (e.g. electrical, plumbing, computer operator, hospitality, web basics). "
        "4) 3 short paragraphs only: (1) why applying + fit, (2) relevant experience summary, (3) polite close. "
        "5) Do not invent employers, degrees, metrics, or skills. "
        "6) Greeting and signature are handled by the template — body paragraphs only."
    )
    payload = {
        "applicant": profile,
        "company": letter.get("company_name"),
        "employer": letter.get("employer_name"),
        "job_title": letter.get("job_title"),
        "job_description": letter.get("job_description"),
        "notes": letter.get("extra_notes"),
    }
    if not api_key:
        api_key, provider, model, _src = resolve_ai_api_key("")
    text = platform_ai_chat(
        system,
        json.dumps(payload, ensure_ascii=False),
        json_mode=True,
        api_key=api_key,
        provider=provider,
        model=model,
    )
    parsed = _parse_json_loose(text) or {}
    paras = parsed.get("paragraphs") or []
    return [str(p).strip() for p in paras if str(p).strip()]



def cl_pack_path(tpl_meta, use_preview=False):
    base = Path(__file__).resolve().parent / "cl_pack"
    rel = tpl_meta.get("preview") if use_preview else tpl_meta.get("template")
    if not rel:
        return None
    path = base / rel
    return path if path.exists() else None



def fill_cover_letter_html(html, letter, profile):
    """Fill pack cover template with real user data. Strip all demo designer language."""
    name = (profile.get("name") or letter.get("applicant_name") or "").strip() or "Your Name"
    role = (profile.get("role") or "").strip()
    email = (profile.get("email") or "").strip()
    phone = (profile.get("phone") or "").strip()
    location = (profile.get("location") or "").strip()
    website = (profile.get("website") or "").strip()
    photo = (profile.get("photo") or "").strip()
    company = (letter.get("company_name") or "").strip()
    employer = (letter.get("employer_name") or "").strip()
    job = (letter.get("job_title") or "").strip()
    date = (letter.get("date") or "").strip()
    body_paras = letter.get("paragraphs") or []
    if isinstance(body_paras, str):
        body_paras = [p.strip() for p in body_paras.split("\n") if p.strip()]
    # Drop any leftover demo designer phrases from AI body
    ban = (
        "product strategy", "interaction design", "ux research", "design systems",
        "prototyping", "accessibility audit", "northstar labs", "fieldwork studio",
        "senior product designer", "cross-functional partners",
    )
    cleaned = []
    for p in body_paras:
        low = p.lower()
        if any(b in low for b in ban):
            continue
        cleaned.append(p)
    if cleaned:
        body_paras = cleaned

    first, last = _name_parts(name)
    initials = _initials(name)

    # Identity
    for demo in ("ALEX MORGAN", "Alex Morgan", "ALEX ROBERT", "Alex Robert"):
        html = html.replace(demo, _esc(name.upper() if demo.isupper() else name))
    html = html.replace(">ALEX<", ">" + _esc(first) + "<")
    html = html.replace(">MORGAN<", ">" + _esc(last or first) + "<")
    html = html.replace(">AM<", ">" + _esc(initials) + "<")
    html = html.replace(">AR<", ">" + _esc(initials) + "<")
    # Circle initials text nodes
    html = re.sub(
        r'(<(?:div|span)[^>]*class="[^"]*(?:avatar|photo|initials|circle)[^"]*"[^>]*>)\s*[A-Z]{1,3}\s*(</)',
        lambda m: m.group(1) + _esc(initials) + m.group(2),
        html,
        count=2,
    )

    if role:
        html = html.replace("PRODUCT DESIGNER", _esc(role.upper()))
        html = html.replace("Product Designer", _esc(role))
        html = html.replace("Senior Product Designer", _esc(job or role))

    if email:
        html = html.replace("alex.morgan@example.com", _esc(email))
        html = html.replace("alex.robert@example.com", _esc(email))
    if phone:
        html = html.replace("+1 555 014 2086", _esc(phone))
        html = html.replace("+1 555 0100", _esc(phone))
    if location:
        html = html.replace("Brooklyn, NY", _esc(location))
        html = html.replace("New York, NY", _esc(location))
    if website:
        html = html.replace("alexmorgan.design", _esc(website))

    # Photo — replace circle/avatar with real image when available
    if photo:
        ph = _esc(photo)
        # background on avatar circle
        html = re.sub(
            r'class="([^"]*(?:avatar|photo|circle)[^"]*)"',
            lambda m: f'class="{m.group(1)}" style="background-image:url(\'{ph}\');background-size:cover;background-position:center;color:transparent;"',
            html,
            count=1,
        )
        html = re.sub(
            r'(<img[^>]*class="[^"]*(?:avatar|photo)[^"]*"[^>]*src=")[^"]*"',
            r'\1' + ph + '"',
            html,
            count=1,
        )
        # hide initials text inside photo circle
        html = re.sub(
            r'(style="[^"]*background-image:url\([^)]+\)[^"]*"[^>]*>)\s*[A-Z]{1,3}\s*',
            r'\1',
            html,
            count=2,
        )

    # Company / employer / job
    if company:
        html = html.replace("Northstar Labs", _esc(company))
    if employer:
        html = html.replace("Jordan Lee", _esc(employer))
        first_name = employer.split()[0] if employer else "Hiring Manager"
        html = html.replace("Dear Jordan,", "Dear " + _esc(first_name) + ",")
        html = html.replace("Dear Jordan", "Dear " + _esc(first_name))
    else:
        html = html.replace("Dear Jordan,", "Dear Hiring Manager,")
        html = html.replace("Dear Jordan", "Dear Hiring Manager")
    if job:
        html = html.replace("Senior Product Designer role", _esc(job) + " role")
        html = html.replace("Senior Product Designer", _esc(job))

    # Date — flexible formats
    if date:
        for demo_d in ("October 12, 2026", "Oct 12, 2026", "12 October 2026", "October 12 2026"):
            html = html.replace(demo_d, _esc(date))
        # also fix broken split dates if template had partials
        html = re.sub(
            r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s*\d{4}\b',
            _esc(date),
            html,
            count=2,
            flags=re.I,
        )

    # Body paragraphs — rebuild a body block when possible; else sequential replace
    sample_paras = [
        "I am applying for the Senior Product Designer role at Northstar Labs. My experience shaping clear, accessible digital products aligns with your team’s focus on useful, thoughtful product experiences.",
        "I am applying for the Senior Product Designer role at Northstar Labs. My experience shaping clear, accessible digital products aligns with your team's focus on useful, thoughtful product experiences.",
        "At Fieldwork Studio, I partnered with research and engineering teams to turn customer insights into responsive product flows. I also helped establish shared design patterns that made delivery more consistent across teams. These experiences strengthened my ability to balance customer needs with practical product goals.",
        "My background includes product strategy, UX research, interaction design, prototyping, and accessibility. I enjoy working closely with cross-functional partners, explaining design decisions clearly, and using feedback to improve the result. I am especially interested in teams that value thoughtful collaboration and measurable outcomes.",
        "I would welcome the opportunity to bring my product strategy, interaction design, and collaborative approach to Northstar Labs. Thank you for considering my application. I look forward to discussing how I can contribute to your team.",
    ]
    if body_paras:
        for i, sp in enumerate(sample_paras):
            if i < len(body_paras) and body_paras[i]:
                html = html.replace(sp, _esc(body_paras[i]))
        # If samples remain (encoding diffs), strip remaining designer demo sentences
        for sp in sample_paras:
            if sp in html:
                html = html.replace(sp, "")
        # Inject body as consecutive <p> after "Dear ..." if still mostly empty
        body_html = "".join(f"<p style=\"margin:0 0 12px;line-height:1.55;\">{_esc(p)}</p>" for p in body_paras)
        html2, n = re.subn(
            r'(Dear\s+[^,<]+,?)\s*(</[^>]+>)?([\s\S]{0,40}?)((?:<p[\s\S]*?</p>\s*){1,6})',
            lambda m: m.group(1) + (m.group(2) or "") + m.group(3) + body_html,
            html,
            count=1,
            flags=re.I,
        )
        # only use if we actually removed designer leftover
        if n and ("product strategy" in html.lower() or "interaction design" in html.lower()):
            html = html2
        # Final ban-word scrub on leftover text
        for phrase in (
            "product strategy", "interaction design", "UX research", "ux research",
            "prototyping", "design systems", "Fieldwork Studio", "Northstar Labs",
        ):
            if phrase.lower() in html.lower():
                # remove whole sentences containing the phrase
                html = re.sub(
                    r'[^.]*' + re.escape(phrase) + r'[^.]*\.',
                    '',
                    html,
                    flags=re.I,
                )

    # Print CSS — hide toolbar
    print_css = """
<style id="mfh-cl-print-css">
@media print {
  .mfh-cv-toolbar, .mfh-cv-toolbar * { display: none !important; }
  body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
}
</style>
"""
    if "</head>" in html:
        html = html.replace("</head>", print_css + "</head>", 1)
    else:
        html = print_css + html

    return html


def cover_path(username):
    return COVER_DIR / f"{username}.json"


def load_covers(username):
    path = cover_path(username)
    if path.exists():
        try:
            data = json.loads(path.read_text())
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "letters" in data:
                return data["letters"]
        except Exception:
            pass
    return []


def save_covers(username, letters):
    COVER_DIR.mkdir(parents=True, exist_ok=True)
    cover_path(username).write_text(json.dumps(letters, indent=2, ensure_ascii=False), encoding="utf-8")



@app.route("/cover-letter/thumb/<tid>")
@login_required
def cover_letter_thumb(tid):
    load_cl_templates()
    tpl = next((t for t in CL_TEMPLATES if t["id"] == tid), None)
    if tpl:
        path = cl_pack_path(tpl, use_preview=True)
        if path:
            return path.read_text(encoding="utf-8", errors="ignore"), 200, {"Content-Type": "text/html; charset=utf-8"}
    return "<p>Preview not found</p>", 404


@app.route("/cover-letter/preview/<letter_id>")
@login_required
def cover_letter_preview(letter_id):
    username = session["user"]
    letters = load_covers(username)
    letter = next((x for x in letters if x.get("id") == letter_id), None)
    if not letter:
        flash("Cover letter not found", "warning")
        return redirect(url_for("cover_letter_edit_list"))
    load_cl_templates()
    tpl = next((t for t in CL_TEMPLATES if t["id"] == letter.get("template_id")), None)
    cv = load_cv(username)
    profile = build_profile_from_doc(cv) if "build_profile_from_doc" in globals() or True else {}
    try:
        profile = build_profile_from_doc(cv)
    except Exception:
        profile = {
            "name": cv.get("full_name") or "",
            "role": cv.get("ai_generated_headline") or "",
            "email": cv.get("email") or "",
            "phone": cv.get("phone") or "",
            "location": cv.get("address") or "",
            "website": cv.get("web") or "",
            "photo": cv.get("photo") or "",
        }
    html = None
    if tpl:
        path = cl_pack_path(tpl, use_preview=False) or cl_pack_path(tpl, use_preview=True)
        if path:
            html = path.read_text(encoding="utf-8", errors="ignore")
            html = fill_cover_letter_html(html, letter, profile)
    if not html:
        return render_template("ai_coming_soon.html", title="Preview", message="Template file missing.", back_url=url_for("cover_letter_edit_list"), back_label="Back")
    bar = (
        '<div class="mfh-cv-toolbar" style="position:sticky;top:0;z-index:50;background:#0f172a;color:#fff;'
        'padding:10px 16px;display:flex;gap:10px;flex-wrap:wrap;font-family:system-ui,sans-serif;">'
        f'<a href="{url_for("cover_letter_edit_list")}" style="color:#fff;text-decoration:none;'
        'background:#334155;padding:6px 12px;border-radius:8px;">← My letters</a>'
        '<a href="javascript:window.print()" style="color:#fff;text-decoration:none;'
        'background:#4f46e5;padding:6px 12px;border-radius:8px;">Print / PDF</a>'
        f'<span style="opacity:.85;font-size:13px;align-self:center;">{_esc(letter.get("company_name") or "")} · {_esc(letter.get("job_title") or "")}</span>'
        '</div>'
    )
    if "<body>" in html:
        html = html.replace("<body>", "<body>" + bar, 1)
    else:
        html = bar + html
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}



@app.route("/cover-letter/build")
@login_required
def cover_letter_build():
    """Template gallery for new cover letter."""
    username = session["user"]
    return render_template(
        "cover_letter.html",
        mode="build",
        letters=load_covers(username),
        templates=CL_TEMPLATES,
        cv_doc=load_cv(username),
    )


@app.route("/cover-letter/select-template", methods=["POST"])
@login_required
def cover_select_template():
    tid = (request.form.get("template_id") or "").strip()
    tpl = next((t for t in CL_TEMPLATES if t["id"] == tid), None)
    if not tpl:
        flash("Select a template", "warning")
        return redirect(url_for("cover_letter_build"))
    session["cl_template_id"] = tid
    return redirect(url_for("cover_letter_generate_page"))


@app.route("/cover-letter/generate", methods=["GET", "POST"])
@login_required
def cover_letter_generate_page():
    """Generate from CV data (Coming Soon). Optional company fields on edit."""
    username = session["user"]
    tid = session.get("cl_template_id") or request.form.get("template_id") or ""
    tpl = next((t for t in CL_TEMPLATES if t["id"] == tid), None)
    if request.method == "POST" or request.args.get("go") == "1":
        # Save stub letter entry
        letters = load_covers(username)
        entry = {
            "id": datetime.now().strftime("%Y%m%d%H%M%S"),
            "template_id": tid,
            "template_name": (tpl or {}).get("name") or tid,
            "company_name": (request.form.get("company_name") or "").strip(),
            "employer_name": (request.form.get("employer_name") or "").strip(),
            "job_title": (request.form.get("job_title") or "").strip(),
            "job_description": (request.form.get("job_description") or "").strip(),
            "extra_notes": (request.form.get("extra_notes") or "").strip(),
            "date": (request.form.get("letter_date") or "").strip(),
            "created_at": datetime.now().isoformat(),
            "ai_status": "coming_soon",
            "body": "",
            "paragraphs": [],
        }
        # Optional OpenAI body from CV facts only
        api_key, _prov, _model, _src = resolve_ai_api_key("")
        api_key = (api_key or "").strip()
        cv = load_cv(username)
        if api_key:
            try:
                paras = call_openai_cover_letter(cv, entry, api_key)
                if paras:
                    entry["paragraphs"] = paras
                    entry["ai_status"] = "ready"
            except Exception as e:
                print("CL AI error:", e)
                entry["ai_status"] = "error"
        letters.insert(0, entry)
        save_covers(username, letters)
        if entry.get("ai_status") == "ready":
            return redirect(url_for("cover_letter_preview", letter_id=entry["id"]))
        return render_template(
            "ai_coming_soon.html",
            title="Cover Letter AI Generation",
            message="Set a platform AI key (Gemini free tier works) in Site Settings → Platform AI Brain. Your application details are saved under My Cover Letters — you can still open the template preview.",
            back_url=url_for("cover_letter_preview", letter_id=entry["id"]),
            back_label="Open template preview",
        )
    return render_template(
        "cover_letter.html",
        mode="generate",
        templates=CL_TEMPLATES,
        selected=tpl,
        letters=load_covers(username),
        cv_doc=load_cv(username),
        edit_letter=None,
    )


@app.route("/cover-letter/edit")
@login_required
def cover_letter_edit_list():
    username = session["user"]
    return render_template(
        "cover_letter.html",
        mode="edit",
        letters=load_covers(username),
        templates=CL_TEMPLATES,
        cv_doc=load_cv(username),
    )


@app.route("/cover-letter/edit/<letter_id>", methods=["GET", "POST"])
@login_required
def cover_letter_edit_one(letter_id):
    username = session["user"]
    letters = load_covers(username)
    letter = next((x for x in letters if x.get("id") == letter_id), None)
    if not letter:
        flash("Cover letter not found", "warning")
        return redirect(url_for("cover_letter_edit_list"))
    if request.method == "POST":
        letter["company_name"] = (request.form.get("company_name") or "").strip()
        letter["employer_name"] = (request.form.get("employer_name") or "").strip()
        letter["job_title"] = (request.form.get("job_title") or "").strip()
        letter["job_description"] = (request.form.get("job_description") or "").strip()
        letter["extra_notes"] = (request.form.get("extra_notes") or "").strip()
        letter["updated_at"] = datetime.now().isoformat()
        api_key, _prov, _model, _src = resolve_ai_api_key("")
        api_key = (api_key or "").strip()
        letter["ai_status"] = "coming_soon"
        if api_key:
            try:
                paras = call_openai_cover_letter(load_cv(username), letter, api_key=api_key, provider=_prov, model=_model)
                if paras:
                    letter["paragraphs"] = paras
                    letter["ai_status"] = "ready"
            except Exception as e:
                print("CL regen error:", e)
                letter["ai_status"] = "error"
        save_covers(username, letters)
        if letter.get("ai_status") == "ready":
            return redirect(url_for("cover_letter_preview", letter_id=letter_id))
        return render_template(
            "ai_coming_soon.html",
            title="Cover Letter Update",
            message="Details saved. Set a platform AI key (Gemini/OpenAI/Claude) in Site Settings to regenerate. Preview still works.",
            back_url=url_for("cover_letter_preview", letter_id=letter_id),
            back_label="Open preview",
        )
    tpl = next((t for t in CL_TEMPLATES if t["id"] == letter.get("template_id")), None)
    return render_template(
        "cover_letter.html",
        mode="edit_form",
        letters=letters,
        templates=CL_TEMPLATES,
        selected=tpl,
        edit_letter=letter,
        cv_doc=load_cv(username),
    )




# ==================== CONTENT CREATOR OS ====================
CC_MODULE_ID = "content-creator-os"

DEFAULT_CONTENT_CREATOR = {
    "ideas": [],
    "pipeline": [],  # content pieces with status
    "campaigns": [],
    "platforms": [],
    "library": [],
    "assets": [],
    "repurpose_log": [],
    "brand_voice": {
        "name": "",
        "tone": "Professional, friendly",
        "audience": "",
        "dos": "",
        "donts": "",
        "sample": "",
    },
    "settings": {
        "timezone": "UTC",
        "week_starts_on": 1,
        "default_platform": "",
        "openai_user_key": "",
    },
    "notifications": [],
    "updated_at": "",
}

CC_STATUSES = ["Idea", "Scripting", "Creating", "Review", "Approved", "Scheduled", "Published", "Archived"]
CC_PRIORITIES = ["Low", "Medium", "High"]
CC_FORMATS = ["Video", "Reel-Short", "Carousel", "Post", "Article", "Thread", "Newsletter", "Podcast"]
CC_PLATFORMS = ["YouTube", "Instagram", "TikTok", "LinkedIn", "X", "Blog", "Newsletter", "Other"]


def cc_path(username):
    folder = MODULES_DIR / CC_MODULE_ID
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{username}.json"


def _cc_norm_status(s):
    """Normalize pipeline status for comparisons (case-insensitive, trim)."""
    raw = (s or "").strip()
    if not raw:
        return "Idea"
    low = raw.lower().replace("_", " ")
    mapping = {
        "idea": "Idea",
        "scripting": "Scripting",
        "creating": "Creating",
        "review": "Review",
        "approved": "Approved",
        "scheduled": "Scheduled",
        "published": "Published",
        "archived": "Archived",
    }
    return mapping.get(low, raw)


def load_content_creator(username):
    path = cc_path(username)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    else:
        data = {}
    base = json.loads(json.dumps(DEFAULT_CONTENT_CREATOR))
    for k, v in base.items():
        if k not in data:
            data[k] = v
    if not isinstance(data.get("brand_voice"), dict):
        data["brand_voice"] = dict(DEFAULT_CONTENT_CREATOR["brand_voice"])
    if not isinstance(data.get("settings"), dict):
        data["settings"] = dict(DEFAULT_CONTENT_CREATOR["settings"])
    # normalize pipeline statuses so counts/columns stay consistent
    for p in (data.get("pipeline") or []):
        if isinstance(p, dict):
            p["status"] = _cc_norm_status(p.get("status"))
    return data


def save_content_creator(username, data):
    data["updated_at"] = datetime.now().isoformat()
    path = cc_path(username)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _cc_norm_url(url):
    url = (url or "").strip()
    if not url:
        return ""
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url.lstrip("/")
    return url[:300]

def _cc_campaign_progress(starts, ends):
    """Return 0-100 progress of date range, or None if incomplete."""
    try:
        from datetime import date as _date
        if not starts or not ends:
            return None
        s = _date.fromisoformat(starts[:10])
        e = _date.fromisoformat(ends[:10])
        if e < s:
            return None
        today = _date.today()
        total = (e - s).days
        if total <= 0:
            return 100 if today >= e else 0
        done = (today - s).days
        if done <= 0:
            return 0
        if done >= total:
            return 100
        return int(round(100.0 * done / total))
    except Exception:
        return None

def _cc_id():
    return datetime.now().strftime("%Y%m%d%H%M%S%f")


def _cc_guard():
    user = get_user(session.get("user"))
    if not user or not user_has_module(user, CC_MODULE_ID):
        return None
    return user


def cc_counts(data):
    ideas = data.get("ideas") or []
    pipe = data.get("pipeline") or []
    open_ideas = [i for i in ideas if not i.get("archived")]
    def st(p):
        return _cc_norm_status(p.get("status"))
    active_pipe = [p for p in pipe if st(p) != "Archived"]
    in_progress = [p for p in pipe if st(p) in ("Scripting", "Creating", "Review", "Approved", "Idea")]
    scheduled = [p for p in pipe if st(p) == "Scheduled"]
    # Also treat future publish_date + not published/archived as scheduled for metrics if status missed
    published = [p for p in pipe if st(p) == "Published"]
    return {
        "ideas": len(open_ideas),
        "in_progress": len(in_progress),
        "scheduled": len(scheduled),
        "published": len(published),
        "campaigns": len([c for c in (data.get("campaigns") or []) if (c.get("status") or "").strip().lower() != "archived"]),
        "platforms": len(data.get("platforms") or []),
        "library": len(data.get("library") or []),
        "assets": len(data.get("assets") or []),
        "pipeline_total": len(active_pipe),
        "pipeline_all": len(pipe),
    }


@app.route("/os/content-creator")
@app.route("/os/content-creator/<page>")
@login_required
def content_creator(page="home"):
    user = _cc_guard()
    if not user:
        flash("Content Creator OS is not unlocked on your account.", "warning")
        return redirect(url_for("subscription_page"))
    site = load_site_settings()
    modules = {m["id"]: m for m in get_modules(site)}
    mod = modules.get(CC_MODULE_ID) or {"id": CC_MODULE_ID, "name": "Content Creator OS", "icon": "🎬"}
    data = load_content_creator(session["user"])
    counts = cc_counts(data)
    today = datetime.now().strftime("%Y-%m-%d")
    q = (request.args.get("q") or "").strip()
    status_f = (request.args.get("status") or "").strip()
    month = (request.args.get("month") or today[:7]).strip()

    # Calendar days for month
    cal_days = []
    try:
        y, m = int(month.split("-")[0]), int(month.split("-")[1])
        import calendar as _cal
        weeks = _cal.Calendar(firstweekday=0).monthdatescalendar(y, m)
        scheduled_by = {}
        for p in data.get("pipeline") or []:
            d = (p.get("publish_date") or p.get("scheduled_for") or "")[:10]
            if d:
                scheduled_by.setdefault(d, []).append(p)
        for week in weeks:
            row = []
            for d in week:
                key = d.isoformat()
                row.append({
                    "date": key,
                    "day": d.day,
                    "in_month": d.month == m,
                    "is_today": key == today,
                    "events": scheduled_by.get(key, []),
                })
            cal_days.append(row)
    except Exception:
        cal_days = []

    # prev / next month strings
    prev_month = next_month = month
    try:
        y, m = int(month.split("-")[0]), int(month.split("-")[1])
        pm, py = (12, y - 1) if m == 1 else (m - 1, y)
        nm, ny = (1, y + 1) if m == 12 else (m + 1, y)
        prev_month = f"{py:04d}-{pm:02d}"
        next_month = f"{ny:04d}-{nm:02d}"
    except Exception:
        pass

    
    for _c in (data.get("campaigns") or []):
        _c["progress_pct"] = _cc_campaign_progress(_c.get("starts_on"), _c.get("ends_on"))

    # Analytics (computed — ready for live platform APIs later)
    by_status = {}
    by_platform = {}
    by_format = {}
    for p in data.get("pipeline") or []:
        st = _cc_norm_status(p.get("status"))
        by_status[st] = by_status.get(st, 0) + 1
        pl = (p.get("platform") or "Unassigned").strip() or "Unassigned"
        by_platform[pl] = by_platform.get(pl, 0) + 1
        fmt = (p.get("format") or "Other").strip() or "Other"
        by_format[fmt] = by_format.get(fmt, 0) + 1
    analytics = {
        "by_status": sorted([{"label": k, "count": v} for k, v in by_status.items()], key=lambda x: -x["count"]),
        "by_platform": sorted([{"label": k, "count": v} for k, v in by_platform.items()], key=lambda x: -x["count"]),
        "by_format": sorted([{"label": k, "count": v} for k, v in by_format.items()], key=lambda x: -x["count"]),
        "published": counts.get("published") or 0,
        "scheduled": counts.get("scheduled") or 0,
        "in_progress": counts.get("in_progress") or 0,
        "ideas": counts.get("ideas") or 0,
        "platforms_linked": counts.get("platforms") or 0,
    }

    return render_template(
        "content_creator.html",
        module=mod,
        data=data,
        page=page,
        counts=counts,
        today=today,
        user=user,
        q=q,
        status_f=status_f,
        month=month,
        prev_month=prev_month,
        next_month=next_month,
        cal_days=cal_days,
        statuses=CC_STATUSES,
        priorities=CC_PRIORITIES,
        formats=CC_FORMATS,
        platform_options=CC_PLATFORMS,
        analytics=analytics,
        site_name=site.get("site_name") or "Portfolio SaaS",
        openai_configured=bool(resolve_ai_api_key(((data.get("settings") or {}).get("openai_user_key") or "").strip())[0]),
    )


def _cc_search_results(data, q):
    """Global search across Content Creator modules. Returns ranked list of hits.
    Any substring match (even 1 character) counts. Pipeline preferred over Ideas.
    """
    q = (q or "").strip().lower()
    results = []
    if not q:
        return results

    def hit(kind, title, snippet, page, rid="", extra="", boost=0):
        title_l = (title or "").lower()
        extra_l = (extra or "").lower()
        blob = (title_l + " " + extra_l).strip()
        # any character sequence match in title or extra fields
        if q not in blob:
            return
        if q == title_l:
            score = 100
        elif title_l.startswith(q):
            score = 90
        elif q in title_l:
            score = 75
        else:
            score = 45
        score += boost
        href = url_for("content_creator", page=page)
        if page == "pipeline" and rid:
            href = href + "#pipe-" + str(rid)
        results.append({
            "kind": kind,
            "title": title or "(untitled)",
            "snippet": (snippet or "")[:160],
            "href": href,
            "id": rid or "",
            "score": score,
            "page": page,
        })

    # Pipeline first (higher boost) — current location after promote
    for p in data.get("pipeline") or []:
        if _cc_norm_status(p.get("status")) == "Archived":
            continue
        extra = " ".join([
            p.get("title") or "", p.get("hook") or "", p.get("body") or "",
            p.get("status") or "", p.get("platform") or "", p.get("format") or "",
        ])
        hit("Pipeline", p.get("title"), f"{p.get('status') or ''} · {p.get('format') or ''}",
            "pipeline", p.get("id"), extra, boost=40)

    # Ideas — skip archived (already promoted)
    for i in data.get("ideas") or []:
        if i.get("archived"):
            continue
        extra = " ".join([
            i.get("title") or "", i.get("hook") or "", i.get("notes") or "",
            i.get("tags") or "", i.get("format") or "",
        ])
        hit("Idea", i.get("title"), i.get("format") or "Idea", "ideas", i.get("id"), extra, boost=0)

    for l in data.get("library") or []:
        extra = " ".join([l.get("title") or "", l.get("body") or "", l.get("tags") or "", l.get("type") or ""])
        hit("Library", l.get("title"), l.get("type") or "Draft", "library", l.get("id"), extra, boost=5)

    for c in data.get("campaigns") or []:
        if (c.get("status") or "").strip().lower() == "archived":
            continue
        extra = " ".join([c.get("name") or "", c.get("objective") or "", c.get("kpi") or "", c.get("status") or ""])
        hit("Campaign", c.get("name"), c.get("status") or "", "campaigns", c.get("id"), extra, boost=5)

    for a in data.get("assets") or []:
        extra = " ".join([a.get("name") or "", a.get("url") or "", a.get("kind") or "", a.get("notes") or ""])
        hit("Asset", a.get("name"), a.get("kind") or "Link", "assets", a.get("id"), extra, boost=0)

    for pl in data.get("platforms") or []:
        extra = " ".join([pl.get("name") or "", pl.get("provider") or "", pl.get("handle") or "", pl.get("url") or ""])
        hit("Platform", pl.get("name"), pl.get("provider") or "", "platforms", pl.get("id"), extra, boost=0)

    results.sort(key=lambda r: (-r.get("score", 0), r.get("kind") or "", r.get("title") or ""))
    return results[:40]


@app.route("/os/content-creator/api/search")
@login_required
def content_creator_search_api():
    user = _cc_guard()
    if not user:
        return jsonify({"ok": False, "results": []}), 403
    data = load_content_creator(session["user"])
    q = (request.args.get("q") or "").strip()
    results = _cc_search_results(data, q)
    for r in results:
        r.pop("score", None)
        r.pop("page", None)
    return jsonify({"ok": True, "results": results, "q": q})


@app.route("/os/content-creator/go-search")
@login_required
def content_creator_go_search():
    """Server-side global search — always works (no JS required).
    Finds best match across Pipeline / Ideas / Library / Campaigns / Assets / Platforms.
    Pipeline ranks highest so promoted content opens on Pipeline, not Ideas.
    """
    user = _cc_guard()
    if not user:
        flash("Not authorized", "danger")
        return redirect(url_for("dashboard"))
    q = (request.args.get("q") or "").strip()
    if not q:
        flash("Type something to search.", "warning")
        return redirect(url_for("content_creator", page="home"))
    data = load_content_creator(session["user"])
    results = _cc_search_results(data, q)
    if not results:
        flash(f'No results found for "{q}"', "warning")
        return redirect(url_for("content_creator", page="home", q=q, found="0"))
    top = results[0]
    # Use path only (fragment # may be dropped by some clients — page is enough)
    target = top.get("href") or url_for("content_creator", page=top.get("page") or "home")
    # strip hash for redirect reliability, page still correct
    if "#" in target:
        target = target.split("#", 1)[0]
    flash(f'Found in {top.get("kind")}: {top.get("title")}', "success")
    return redirect(target)



@app.route("/os/content-creator/action", methods=["POST"])
@login_required
def content_creator_action():
    user = _cc_guard()
    if not user:
        flash("Not authorized", "danger")
        return redirect(url_for("dashboard"))
    username = session["user"]
    data = load_content_creator(username)
    action = (request.form.get("action") or "").strip()
    page = (request.form.get("page") or "home").strip()

    def back(extra=""):
        save_content_creator(username, data)
        return redirect(url_for("content_creator", page=page) + extra)

    # —— Ideas ——
    if action == "add_idea":
        title = (request.form.get("title") or "").strip()
        if not title:
            flash("Title is required", "danger")
            return redirect(url_for("content_creator", page="ideas"))
        data.setdefault("ideas", []).insert(0, {
            "id": _cc_id(),
            "title": title[:300],
            "format": (request.form.get("format") or "Video").strip(),
            "priority": (request.form.get("priority") or "Medium").strip(),
            "hook": (request.form.get("hook") or "").strip()[:500],
            "notes": (request.form.get("notes") or "").strip()[:2000],
            "platform": (request.form.get("platform") or "").strip(),
            "campaign_id": (request.form.get("campaign_id") or "").strip(),
            "tags": (request.form.get("tags") or "").strip()[:300],
            "publish_date": (request.form.get("publish_date") or "").strip()[:10],
            "archived": False,
            "created_at": datetime.now().isoformat(),
        })
        flash("Idea added", "success")
        return back()

    if action == "update_idea":
        iid = request.form.get("item_id")
        for i in data.get("ideas") or []:
            if i.get("id") == iid:
                i["title"] = (request.form.get("title") or i.get("title") or "").strip()[:300]
                i["format"] = (request.form.get("format") or i.get("format") or "Video").strip()
                i["priority"] = (request.form.get("priority") or i.get("priority") or "Medium").strip()
                i["hook"] = (request.form.get("hook") or "").strip()[:500]
                i["notes"] = (request.form.get("notes") or "").strip()[:2000]
                i["platform"] = (request.form.get("platform") or "").strip()
                break
        flash("Idea updated", "success")
        return back()

    if action == "delete_idea":
        iid = request.form.get("item_id")
        data["ideas"] = [i for i in (data.get("ideas") or []) if i.get("id") != iid]
        flash("Idea deleted", "success")
        return back()

    if action == "promote_idea":
        iid = request.form.get("item_id")
        moved = False
        for i in list(data.get("ideas") or []):
            if i.get("id") == iid:
                data.setdefault("pipeline", []).insert(0, {
                    "id": _cc_id(),
                    "title": (i.get("title") or "Untitled")[:300],
                    "format": i.get("format") or "Video",
                    "priority": i.get("priority") or "Medium",
                    "hook": i.get("hook") or "",
                    "body": i.get("notes") or i.get("body") or "",
                    "status": "Idea",
                    "platform": i.get("platform") or "",
                    "campaign_id": i.get("campaign_id") or "",
                    "publish_date": (i.get("publish_date") or "")[:10],
                    "created_at": datetime.now().isoformat(),
                    "from_idea_id": iid,
                })
                data["ideas"] = [x for x in (data.get("ideas") or []) if x.get("id") != iid]
                moved = True
                flash("Moved to pipeline", "success")
                break
        if not moved:
            flash("Idea not found", "warning")
        save_content_creator(username, data)
        return redirect(url_for("content_creator", page="pipeline"))

    if action == "library_to_pipeline":
        iid = request.form.get("item_id")
        lib = next((x for x in (data.get("library") or []) if x.get("id") == iid), None)
        if lib:
            data.setdefault("pipeline", []).insert(0, {
                "id": _cc_id(),
                "title": lib.get("title") or "From library",
                "format": lib.get("type") or "Other",
                "status": "Idea",
                "body": lib.get("body") or "",
                "platform": "",
                "created_at": datetime.now().isoformat(),
            })
            flash("Pushed to Pipeline", "success")
            page = "pipeline"
        return back()

    # —— Pipeline ——
    if action == "add_pipeline":
        title = (request.form.get("title") or "").strip()
        if not title:
            flash("Title is required", "danger")
            return redirect(url_for("content_creator", page="pipeline"))
        data.setdefault("pipeline", []).insert(0, {
            "id": _cc_id(),
            "title": title[:300],
            "format": (request.form.get("format") or "Video").strip(),
            "priority": (request.form.get("priority") or "Medium").strip(),
            "hook": (request.form.get("hook") or "").strip()[:500],
            "body": (request.form.get("body") or "").strip()[:8000],
            "status": _cc_norm_status(request.form.get("status") or "Idea"),
            "platform": (request.form.get("platform") or "").strip(),
            "campaign_id": (request.form.get("campaign_id") or "").strip(),
            "publish_date": (request.form.get("publish_date") or "").strip()[:10],
            "created_at": datetime.now().isoformat(),
        })
        flash("Content added to pipeline", "success")
        return back()

    if action == "update_pipeline":
        iid = request.form.get("item_id")
        for p in data.get("pipeline") or []:
            if p.get("id") == iid:
                p["title"] = (request.form.get("title") or p.get("title") or "").strip()[:300]
                p["format"] = (request.form.get("format") or p.get("format") or "Video").strip()
                p["priority"] = (request.form.get("priority") or p.get("priority") or "Medium").strip()
                p["hook"] = (request.form.get("hook") or "").strip()[:500]
                p["body"] = (request.form.get("body") or "").strip()[:8000]
                p["status"] = _cc_norm_status(request.form.get("status") or p.get("status") or "Idea")
                p["platform"] = (request.form.get("platform") or "").strip()
                p["publish_date"] = (request.form.get("publish_date") or "").strip()[:10]
                p["campaign_id"] = (request.form.get("campaign_id") or "").strip()
                break
        flash("Pipeline item updated", "success")
        return back()

    if action == "move_pipeline":
        iid = request.form.get("item_id")
        st = _cc_norm_status(request.form.get("status") or "")
        for p in data.get("pipeline") or []:
            if p.get("id") == iid and st in CC_STATUSES:
                p["status"] = st
                break
        return back()

    if action == "schedule_pipeline":
        iid = request.form.get("item_id")
        date = (request.form.get("publish_date") or "").strip()[:10]
        for p in data.get("pipeline") or []:
            if p.get("id") == iid:
                p["publish_date"] = date
                if date and _cc_norm_status(p.get("status")) in ("Idea", "Scripting", "Creating", "Review", "Approved"):
                    p["status"] = "Scheduled"
                break
        flash("Schedule updated", "success")
        return back("calendar")

    if action == "delete_pipeline":
        iid = request.form.get("item_id")
        data["pipeline"] = [p for p in (data.get("pipeline") or []) if p.get("id") != iid]
        flash("Item deleted", "success")
        return back()

    # —— Campaigns ——
    if action == "add_campaign":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("Campaign name is required", "danger")
            return redirect(url_for("content_creator", page="campaigns"))
        starts = (request.form.get("starts_on") or "").strip()[:10]
        ends = (request.form.get("ends_on") or "").strip()[:10]
        if starts and ends and ends < starts:
            flash("Ends date cannot be before Starts date.", "danger")
            return redirect(url_for("content_creator", page="campaigns"))
        linked = request.form.getlist("linked_pipeline") or []
        linked = [x.strip() for x in linked if x and x.strip()][:50]
        data.setdefault("campaigns", []).insert(0, {
            "id": _cc_id(),
            "name": name[:200],
            "objective": (request.form.get("objective") or "").strip()[:1000],
            "audience": (request.form.get("audience") or "").strip()[:500],
            "kpi": (request.form.get("kpi") or "").strip()[:200],
            "budget": (request.form.get("budget") or "").strip()[:120],
            "status": (request.form.get("status") or "Planning").strip(),
            "starts_on": starts,
            "ends_on": ends,
            "linked_pipeline": linked,
            "created_at": datetime.now().isoformat(),
        })
        flash("Campaign created", "success")
        return back()

    if action == "update_campaign":
        iid = request.form.get("item_id")
        for c in data.get("campaigns") or []:
            if c.get("id") == iid:
                c["name"] = (request.form.get("name") or c.get("name") or "").strip()[:200]
                c["objective"] = (request.form.get("objective") or "").strip()[:1000]
                c["audience"] = (request.form.get("audience") or "").strip()[:500]
                c["status"] = (request.form.get("status") or c.get("status") or "Planning").strip()
                starts = (request.form.get("starts_on") or "").strip()[:10]
                ends = (request.form.get("ends_on") or "").strip()[:10]
                if starts and ends and ends < starts:
                    flash("Ends date cannot be before Starts date.", "danger")
                    return redirect(url_for("content_creator", page="campaigns"))
                c["starts_on"] = starts
                c["ends_on"] = ends
                c["kpi"] = (request.form.get("kpi") or "").strip()[:200]
                c["budget"] = (request.form.get("budget") or "").strip()[:120]
                linked = request.form.getlist("linked_pipeline") or []
                if linked:
                    c["linked_pipeline"] = [x.strip() for x in linked if x and x.strip()][:50]
                break
        flash("Campaign updated", "success")
        return back()

    if action == "delete_campaign":
        iid = request.form.get("item_id")
        data["campaigns"] = [c for c in (data.get("campaigns") or []) if c.get("id") != iid]
        flash("Campaign deleted", "success")
        return back()

    # —— Platforms ——
    if action == "add_platform":
        name = (request.form.get("name") or "").strip()
        provider = (request.form.get("provider") or "Other").strip()
        if not name:
            flash("Account name is required", "danger")
            return redirect(url_for("content_creator", page="platforms"))
        data.setdefault("platforms", []).append({
            "id": _cc_id(),
            "name": name[:120],
            "provider": provider,
            "handle": (request.form.get("handle") or "").strip()[:120],
            "url": _cc_norm_url(request.form.get("url")),
            "connection": "Manual",
            "status": (request.form.get("status") or "Active").strip() or "Active",
            "notes": (request.form.get("notes") or "").strip()[:500],
            "created_at": datetime.now().isoformat(),
        })
        flash("Platform saved (manual). OAuth publishing is Coming Soon.", "success")
        return back()

    if action == "update_platform":
        iid = request.form.get("item_id")
        for pl in data.get("platforms") or []:
            if pl.get("id") == iid:
                pl["name"] = (request.form.get("name") or pl.get("name") or "").strip()[:120]
                pl["provider"] = (request.form.get("provider") or pl.get("provider") or "Other").strip()
                pl["handle"] = (request.form.get("handle") or "").strip()[:120]
                pl["url"] = _cc_norm_url(request.form.get("url"))
                pl["status"] = (request.form.get("status") or pl.get("status") or "Active").strip() or "Active"
                pl["notes"] = (request.form.get("notes") or "").strip()[:500]
                break
        flash("Platform updated", "success")
        return back()

    if action == "delete_platform":
        iid = request.form.get("item_id")
        data["platforms"] = [p for p in (data.get("platforms") or []) if p.get("id") != iid]
        flash("Platform removed", "success")
        return back()

    # —— Library ——
    if action == "add_library":
        title = (request.form.get("title") or "").strip()
        if not title:
            flash("Title is required", "danger")
            return redirect(url_for("content_creator", page="library"))
        data.setdefault("library", []).insert(0, {
            "id": _cc_id(),
            "title": title[:300],
            "type": (request.form.get("type") or "Draft").strip()[:80],
            "platform": (request.form.get("platform") or "").strip()[:80],
            "body": (request.form.get("body") or "").strip()[:15000],
            "tags": (request.form.get("tags") or "").strip()[:200],
            "created_at": datetime.now().isoformat(),
        })
        flash("Saved to library", "success")
        return back()

    if action == "update_library":
        iid = request.form.get("item_id")
        for l in data.get("library") or []:
            if l.get("id") == iid:
                l["title"] = (request.form.get("title") or l.get("title") or "").strip()[:300]
                l["type"] = (request.form.get("type") or l.get("type") or "Draft").strip()[:80]
                l["platform"] = (request.form.get("platform") or l.get("platform") or "").strip()[:80]
                l["body"] = (request.form.get("body") or "").strip()[:15000]
                l["tags"] = (request.form.get("tags") or "").strip()[:200]
                break
        flash("Library item updated", "success")
        return back()

    if action == "delete_library":
        iid = request.form.get("item_id")
        data["library"] = [l for l in (data.get("library") or []) if l.get("id") != iid]
        flash("Deleted", "success")
        return back()

    # —— Assets ——
    if action == "add_asset":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("Name is required", "danger")
            return redirect(url_for("content_creator", page="assets"))
        url = _cc_norm_url(request.form.get("url"))
        # optional local file upload
        f = request.files.get("file")
        if f and f.filename:
            safe = "".join(c for c in f.filename if c.isalnum() or c in "._-")[:80]
            if not safe:
                safe = "upload.bin"
            up_dir = Path(app.root_path) / "static" / "cc_uploads" / username
            up_dir.mkdir(parents=True, exist_ok=True)
            dest = up_dir / f"{_cc_id()}_{safe}"
            f.save(str(dest))
            url = url_for("static", filename=f"cc_uploads/{username}/{dest.name}")
        if not url:
            flash("Provide a URL or upload a file", "danger")
            return redirect(url_for("content_creator", page="assets"))
        data.setdefault("assets", []).insert(0, {
            "id": _cc_id(),
            "name": name[:200],
            "kind": (request.form.get("kind") or "Link").strip()[:80],
            "url": url,
            "notes": (request.form.get("notes") or "").strip()[:500],
            "created_at": datetime.now().isoformat(),
        })
        flash("Asset saved", "success")
        return back()

    if action == "update_asset":
        iid = request.form.get("item_id")
        for a in data.get("assets") or []:
            if a.get("id") == iid:
                a["name"] = (request.form.get("name") or a.get("name") or "").strip()[:200]
                a["kind"] = (request.form.get("kind") or a.get("kind") or "Link").strip()[:80]
                a["url"] = _cc_norm_url(request.form.get("url") or a.get("url"))
                a["notes"] = (request.form.get("notes") or a.get("notes") or "").strip()[:500]
                break
        flash("Asset updated", "success")
        return back()

    if action == "delete_asset":
        iid = request.form.get("item_id")
        data["assets"] = [a for a in (data.get("assets") or []) if a.get("id") != iid]
        flash("Asset deleted", "success")
        return back()

    # —— Brand voice ——
    if action == "save_brand_voice":
        bv = data.setdefault("brand_voice", {})
        # full overwrite of editable fields (no append)
        bv["name"] = (request.form.get("name") or "").strip()[:200]
        bv["tone"] = (request.form.get("tone") or "").strip()[:500]
        bv["audience"] = (request.form.get("audience") or "").strip()[:500]
        bv["dos"] = (request.form.get("dos") or "").strip()[:2000]
        bv["donts"] = (request.form.get("donts") or "").strip()[:2000]
        bv["sample"] = (request.form.get("sample") or "").strip()[:4000]
        flash("Brand voice saved", "success")
        return back()

    if action == "save_cc_settings":
        s = data.setdefault("settings", {})
        s["timezone"] = (request.form.get("timezone") or "UTC").strip()[:60]
        try:
            s["week_starts_on"] = int(request.form.get("week_starts_on") or 1)
        except Exception:
            s["week_starts_on"] = 1
        s["default_platform"] = (request.form.get("default_platform") or "").strip()
        # Customer may store their own OpenAI key (never logged; only in their JSON)
        key = (request.form.get("openai_user_key") or "").strip()
        if key == "":
            pass  # leave existing
        elif key.lower() in ("clear", "remove", "-"):
            s.pop("openai_user_key", None)
        else:
            s["openai_user_key"] = key[:200]
        flash("Settings saved", "success")
        return back()

    # —— Export ——
    if action == "export_json":
        save_content_creator(username, data)
        from flask import Response
        payload = json.dumps(data, indent=2, ensure_ascii=False)
        return Response(
            payload,
            mimetype="application/json",
            headers={"Content-Disposition": f"attachment; filename=content-creator-os-{username}.json"},
        )

    # —— Import ——
    if action == "import_json":
        f = request.files.get("file")
        if not f or not f.filename:
            flash("Choose a JSON file", "danger")
            return redirect(url_for("content_creator", page="settings"))
        try:
            incoming = json.loads(f.read().decode("utf-8"))
            if not isinstance(incoming, dict):
                raise ValueError("Root must be an object")
            for key in ("ideas", "pipeline", "campaigns", "platforms", "library", "assets"):
                if key in incoming and isinstance(incoming[key], list):
                    # merge by id
                    existing = {x.get("id"): x for x in (data.get(key) or []) if x.get("id")}
                    for item in incoming[key]:
                        if isinstance(item, dict) and item.get("id"):
                            existing[item["id"]] = item
                        elif isinstance(item, dict):
                            item["id"] = _cc_id()
                            existing[item["id"]] = item
                    data[key] = list(existing.values())
            if isinstance(incoming.get("brand_voice"), dict):
                data["brand_voice"] = {**(data.get("brand_voice") or {}), **incoming["brand_voice"]}
            if isinstance(incoming.get("settings"), dict):
                data["settings"] = {**(data.get("settings") or {}), **incoming["settings"]}
            flash("Import merged successfully", "success")
        except Exception as e:
            flash(f"Import failed: {e}", "danger")
        return back()

    # —— AI generate draft (server-side; Coming Soon without key) ——
    if action == "ai_generate_draft":
        prompt = (request.form.get("prompt") or "").strip()
        # Prefer customer key (settings), else platform env key
        api_key, _prov, _model, _src = resolve_ai_api_key(((data.get("settings") or {}).get("openai_user_key") or "").strip())
        if not api_key:
            flash("Add your OpenAI API key in Settings, or ask admin to set OPENAI_API_KEY on the server.", "warning")
            return redirect(url_for("content_creator", page="ai-studio"))
        if not prompt:
            flash("Describe what you want to create", "danger")
            return redirect(url_for("content_creator", page="ai-studio"))
        bv = data.get("brand_voice") or {}
        system = (
            "You are a content strategist. Write a draft for the creator. "
            f"Brand name: {bv.get('name') or 'Creator'}. Tone: {bv.get('tone') or 'clear'}. "
            f"Audience: {bv.get('audience') or 'general'}. "
            f"Do: {bv.get('dos') or 'be helpful'}. Don't: {bv.get('donts') or 'be salesy'}. "
            "Return plain text draft only."
        )
        try:
            import urllib.request
            body = json.dumps({
                "model": os.environ.get("OPENAI_MODEL") or "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt[:4000]},
                ],
                "temperature": 0.7,
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                out = json.loads(resp.read().decode("utf-8"))
            text = out["choices"][0]["message"]["content"]
            data.setdefault("library", []).insert(0, {
                "id": _cc_id(),
                "title": (request.form.get("title") or "AI Draft")[:300],
                "type": "AI Draft",
                "body": text[:15000],
                "tags": "ai",
                "created_at": datetime.now().isoformat(),
            })
            flash("Draft generated and saved to Library for your review. Nothing was published.", "success")
            return redirect(url_for("content_creator", page="library"))
        except Exception as e:
            flash(f"AI error: {e}", "danger")
            return redirect(url_for("content_creator", page="ai-studio"))

    if action == "repurpose_save":
        title = (request.form.get("title") or "").strip() or "Repurposed piece"
        source_id = (request.form.get("source_item_id") or "").strip()
        source_notes = (request.form.get("source") or "").strip()[:4000]
        notes = (request.form.get("notes") or "").strip()[:2000]
        body = (request.form.get("body") or source_notes or notes).strip()[:8000]
        fmt = (request.form.get("format") or "Post").strip()
        plat = (request.form.get("platform") or "").strip()
        new_id = _cc_id()
        src_title = ""
        if source_id:
            for coll in (data.get("pipeline") or [], data.get("library") or []):
                for it in coll:
                    if str(it.get("id")) == str(source_id):
                        src_title = it.get("title") or ""
                        if not body and it.get("body"):
                            body = (it.get("body") or "")[:8000]
                        break
                if src_title:
                    break
        if not isinstance(data.get("repurpose_log"), list):
            data["repurpose_log"] = []
        if not isinstance(data.get("pipeline"), list):
            data["pipeline"] = []
        data["pipeline"].insert(0, {
            "id": new_id,
            "title": title[:300],
            "format": fmt,
            "priority": "Medium",
            "hook": (request.form.get("hook") or "").strip()[:500],
            "body": body,
            "status": "Scripting",
            "platform": plat,
            "campaign_id": "",
            "publish_date": "",
            "source_item_id": source_id,
            "repurposed": True,
            "created_at": datetime.now().isoformat(),
        })
        data["repurpose_log"].insert(0, {
            "id": _cc_id(),
            "pipeline_id": new_id,
            "title": title[:300],
            "format": fmt,
            "platform": plat,
            "source_item_id": source_id,
            "source_title": src_title or (source_notes[:80] if source_notes else ""),
            "notes": notes,
            "created_at": datetime.now().isoformat(),
        })
        # keep log reasonable size
        data["repurpose_log"] = data["repurpose_log"][:100]
        save_content_creator(username, data)
        flash("Repurposed draft added to pipeline — history updated", "success")
        return redirect(url_for("content_creator", page="repurpose"))


    if action == "test_openai_key":
        key = (request.form.get("openai_user_key") or "").strip()
        if not key:
            key, _prov, _model, _src = resolve_ai_api_key((data.get("settings") or {}).get("openai_user_key") or "")
        if not key:
            flash("No API key to test. Enter a key or set OPENAI_API_KEY on the server.", "danger")
            return redirect(url_for("content_creator", page="settings"))
        if not key.startswith("sk-"):
            flash("Key format looks unusual (OpenAI keys usually start with sk-). Saved keys still work if valid.", "danger")
            return redirect(url_for("content_creator", page="settings"))
        try:
            import urllib.request
            req = urllib.request.Request(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {key}"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status == 200:
                    flash("Connection OK — OpenAI accepted this key.", "success")
                else:
                    flash(f"Unexpected status: {resp.status}", "danger")
        except Exception as e:
            flash(f"Test failed: {e}", "danger")
        return redirect(url_for("content_creator", page="settings"))

    flash("Unknown action", "danger")
    return redirect(url_for("content_creator", page=page or "home"))



# ==================== CREATE DEFAULT ADMIN ====================
def any_admin_exists():
    for f in USERS_DIR.glob("*.json"):
        try:
            u = json.loads(f.read_text())
            if u.get("role") == "admin":
                return True
        except Exception:
            continue
    return False


# ==================== FREELANCE & AGENCY OS ====================
FA_MODULE_ID = "freelance-agency-os"

DEFAULT_FREELANCE_AGENCY = {
    "clients": [],
    "projects": [],
    "retainers": [],
    "tasks": [],
    "deliveries": [],
    "invoices": [],
    "messages": [],
    "time_entries": [],
    "contracts": [],
    "expenses": [],
    "reminders": [],
    "portal_tokens": {},
    "weekly_focus": {},
    "ai_log": [],
    "settings": {
        "timezone": "Asia/Dhaka",
        "currency": "USD",
        "week_starts_on": 1,
        "default_view": "home",
        "hourly_rate": "",
        "openai_user_key": "",
        "business_name": "",
        "business_email": "",
        "business_address": "",
        "smtp_host": "",
        "smtp_port": "587",
        "smtp_user": "",
        "smtp_pass": "",
        "smtp_from": "",
        "email_enabled": False,
    },
    "updated_at": "",
}

FA_PROJECT_STATUSES = ["Lead", "Proposal", "Active", "On Hold", "Completed", "Cancelled"]
FA_TASK_STATUSES = ["Todo", "In Progress", "Review", "Done"]
FA_INVOICE_STATUSES = ["Draft", "Sent", "Paid", "Overdue", "Cancelled"]
FA_CLIENT_STATUSES = ["Lead", "Active", "Paused", "Archived"]
FA_PRIORITIES = ["Low", "Medium", "High", "Urgent"]


def fa_path(username):
    folder = MODULES_DIR / FA_MODULE_ID
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{username}.json"


def load_freelance_agency(username):
    path = fa_path(username)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    else:
        data = {}
    base = json.loads(json.dumps(DEFAULT_FREELANCE_AGENCY))
    for k, v in base.items():
        if k not in data:
            data[k] = v
    if not isinstance(data.get("settings"), dict):
        data["settings"] = dict(DEFAULT_FREELANCE_AGENCY["settings"])
    if not isinstance(data.get("weekly_focus"), dict):
        data["weekly_focus"] = {}
    for key in ("clients", "projects", "retainers", "tasks", "deliveries", "invoices",
                "messages", "time_entries", "contracts", "expenses", "reminders", "ai_log"):
        if not isinstance(data.get(key), list):
            data[key] = []
    if not isinstance(data.get("portal_tokens"), dict):
        data["portal_tokens"] = {}
    return data


def save_freelance_agency(username, data):
    data["updated_at"] = datetime.now().isoformat()
    path = fa_path(username)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _fa_id():
    return uuid.uuid4().hex[:12]


def _fa_today():
    return datetime.now().strftime("%Y-%m-%d")


def _fa_week_key(d=None):
    if not d:
        d = datetime.now()
    elif isinstance(d, str):
        try:
            d = datetime.strptime(d[:10], "%Y-%m-%d")
        except Exception:
            d = datetime.now()
    return d.strftime("%G-W%V")



def _fa_search_results(data, q):
    """Global search across Freelance & Agency modules. Returns list of hits."""
    q = (q or "").strip().lower()
    hits = []
    if not q:
        return hits
    for c in data.get("clients") or []:
        blob = " ".join([str(c.get(k) or "") for k in ("name", "company", "email", "notes", "tags")]).lower()
        if q in blob:
            hits.append({"kind": "Client", "title": c.get("name") or c.get("company") or "Client", "page": "clients", "id": c.get("id")})
    for p in data.get("projects") or []:
        blob = " ".join([str(p.get(k) or "") for k in ("title", "notes", "status")]).lower()
        if q in blob:
            hits.append({"kind": "Project", "title": p.get("title") or "Project", "page": "projects", "id": p.get("id")})
    for t in data.get("tasks") or []:
        blob = " ".join([str(t.get(k) or "") for k in ("title", "notes", "status")]).lower()
        if q in blob:
            hits.append({"kind": "Task", "title": t.get("title") or "Task", "page": "tasks", "id": t.get("id")})
    for inv in data.get("invoices") or []:
        blob = " ".join([str(inv.get(k) or "") for k in ("number", "notes", "status", "amount")]).lower()
        if q in blob:
            hits.append({"kind": "Invoice", "title": inv.get("number") or inv.get("id") or "Invoice", "page": "invoices", "id": inv.get("id")})
    for r in data.get("retainers") or []:
        blob = " ".join([str(r.get(k) or "") for k in ("title", "notes", "status")]).lower()
        if q in blob:
            hits.append({"kind": "Retainer", "title": r.get("title") or "Retainer", "page": "retainers", "id": r.get("id")})
    for d in data.get("deliveries") or []:
        blob = " ".join([str(d.get(k) or "") for k in ("title", "notes", "status")]).lower()
        if q in blob:
            hits.append({"kind": "Delivery", "title": d.get("title") or "Delivery", "page": "deliveries", "id": d.get("id")})
    for c in data.get("contracts") or []:
        blob = " ".join([str(c.get(k) or "") for k in ("title", "body", "status", "value")]).lower()
        if q in blob:
            hits.append({"kind": "Contract", "title": c.get("title") or "Contract", "page": "contracts", "id": c.get("id")})
    for e in data.get("expenses") or []:
        blob = " ".join([str(e.get(k) or "") for k in ("title", "category", "notes", "amount")]).lower()
        if q in blob:
            hits.append({"kind": "Expense", "title": e.get("title") or "Expense", "page": "expenses", "id": e.get("id")})
    for m in data.get("messages") or []:
        blob = " ".join([str(m.get(k) or "") for k in ("subject", "body", "status")]).lower()
        if q in blob:
            hits.append({"kind": "Message", "title": m.get("subject") or "Message", "page": "messages", "id": m.get("id")})
    return hits[:40]


def fa_counts(data):
    clients = data.get("clients") or []
    projects = data.get("projects") or []
    retainers = data.get("retainers") or []
    tasks = data.get("tasks") or []
    invoices = data.get("invoices") or []
    deliveries = data.get("deliveries") or []
    messages = data.get("messages") or []
    time_entries = data.get("time_entries") or []
    contracts = data.get("contracts") or []
    expenses = data.get("expenses") or []
    active_clients = sum(1 for c in clients if (c.get("status") or "").lower() in ("active", "lead"))
    active_projects = sum(1 for p in projects if (p.get("status") or "").lower() in ("active", "proposal", "lead"))
    open_tasks = sum(1 for t in tasks if (t.get("status") or "").lower() not in ("done", "cancelled"))
    unpaid = sum(1 for i in invoices if (i.get("status") or "").lower() in ("sent", "overdue", "draft"))
    active_retainers = sum(1 for r in retainers if (r.get("status") or "").lower() == "active")
    open_contracts = sum(1 for c in contracts if (c.get("status") or "").lower() in ("draft", "sent", "active"))
    hours = 0.0
    for te in time_entries:
        try:
            hours += float(te.get("hours") or 0)
        except Exception:
            pass
    due_reminders = 0
    today = _fa_today()
    for inv in invoices:
        due = (inv.get("due_date") or "")[:10]
        if due and (inv.get("status") or "").lower() in ("sent", "overdue", "draft") and due <= today:
            due_reminders += 1
    for t in tasks:
        due = (t.get("due") or "")[:10]
        if due and (t.get("status") or "").lower() not in ("done", "cancelled") and due <= today:
            due_reminders += 1
    for c in contracts:
        due = (c.get("end_date") or c.get("expires_on") or "")[:10]
        if due and (c.get("status") or "").lower() in ("sent", "active", "draft") and due <= today:
            due_reminders += 1
    for r in (data.get("reminders") or []):
        due = (r.get("due") or r.get("date") or "")[:10]
        if due and due <= today and not r.get("done"):
            due_reminders += 1
    return {
        "clients": len(clients),
        "active_clients": active_clients,
        "projects": len(projects),
        "active_projects": active_projects,
        "retainers": len(retainers),
        "active_retainers": active_retainers,
        "tasks": len(tasks),
        "open_tasks": open_tasks,
        "deliveries": len(deliveries),
        "invoices": len(invoices),
        "unpaid_invoices": unpaid,
        "messages": len(messages),
        "time_entries": len(time_entries),
        "hours_logged": round(hours, 2),
        "contracts": len(contracts),
        "open_contracts": open_contracts,
        "expenses": len(expenses),
        "due_reminders": due_reminders,
    }


def _fa_guard():
    user = get_user(session.get("user"))
    if not user or not user_has_module(user, FA_MODULE_ID):
        return None
    return user


def _fa_client_name(data, client_id):
    for c in data.get("clients") or []:
        if c.get("id") == client_id:
            return c.get("name") or c.get("company") or "Client"
    return "—"


def _fa_project_title(data, project_id):
    for p in data.get("projects") or []:
        if p.get("id") == project_id:
            return p.get("title") or "Project"
    return "—"


@app.route("/os/freelance-agency")
@app.route("/os/freelance-agency/<page>")
@login_required
def freelance_agency(page="home"):
    user = _fa_guard()
    if not user:
        flash("Freelance & Agency OS is not unlocked on your account.", "warning")
        return redirect(url_for("subscription_page"))
    site = load_site_settings()
    modules = {m["id"]: m for m in get_modules(site)}
    mod = modules.get(FA_MODULE_ID) or {
        "id": FA_MODULE_ID,
        "name": "Freelance & Agency OS",
        "icon": "💼",
        "desc": "Clients, projects, retainers, delivery & weekly focus",
    }
    data = load_freelance_agency(session["user"])
    page = (page or "home").strip().lower().replace(" ", "-")
    allowed = {
        "home", "start-here", "clients", "projects", "retainers",
        "tasks", "deliveries", "invoices", "messages", "time", "contracts",
        "expenses", "reminders", "ai", "focus", "settings", "search", "portal",
    }
    if page not in allowed:
        page = "home"
    counts = fa_counts(data)
    today = _fa_today()
    week = _fa_week_key()
    focus = data.get("weekly_focus", {}).get(week) or {
        "goals": "", "priorities": "", "wins": "", "notes": "", "week": week
    }
    q = (request.args.get("q") or "").strip().lower()
    status_f = (request.args.get("status") or "").strip()
    client_f = (request.args.get("client") or "").strip()

    for p in data.get("projects") or []:
        p["_client_name"] = _fa_client_name(data, p.get("client_id"))
    for t in data.get("tasks") or []:
        t["_project_title"] = _fa_project_title(data, t.get("project_id"))
        t["_client_name"] = _fa_client_name(data, t.get("client_id"))
    for d in data.get("deliveries") or []:
        d["_project_title"] = _fa_project_title(data, d.get("project_id"))
    for r in data.get("retainers") or []:
        r["_client_name"] = _fa_client_name(data, r.get("client_id"))
    for inv in data.get("invoices") or []:
        inv["_client_name"] = _fa_client_name(data, inv.get("client_id"))
    for msg in data.get("messages") or []:
        msg["_client_name"] = _fa_client_name(data, msg.get("client_id"))
    for te in data.get("time_entries") or []:
        te["_project_title"] = _fa_project_title(data, te.get("project_id"))
        te["_client_name"] = _fa_client_name(data, te.get("client_id"))
    for c in data.get("contracts") or []:
        c["_client_name"] = _fa_client_name(data, c.get("client_id"))
    for e in data.get("expenses") or []:
        e["_project_title"] = _fa_project_title(data, e.get("project_id"))
        e["_client_name"] = _fa_client_name(data, e.get("client_id"))

    # Build live reminders list
    today = _fa_today()
    live_reminders = []
    for inv in data.get("invoices") or []:
        due = (inv.get("due_date") or "")[:10]
        st = (inv.get("status") or "").lower()
        if due and st in ("sent", "overdue", "draft") and due <= today:
            live_reminders.append({"kind": "Invoice", "title": inv.get("number") or inv.get("id"), "due": due, "page": "invoices", "urgency": "high"})
    for t in data.get("tasks") or []:
        due = (t.get("due") or "")[:10]
        if due and (t.get("status") or "").lower() not in ("done",) and due <= today:
            live_reminders.append({"kind": "Task", "title": t.get("title"), "due": due, "page": "tasks", "urgency": "medium"})
    for c in data.get("contracts") or []:
        due = (c.get("end_date") or c.get("expires_on") or "")[:10]
        if due and (c.get("status") or "").lower() in ("sent", "active", "draft") and due <= today:
            live_reminders.append({"kind": "Contract", "title": c.get("title"), "due": due, "page": "contracts", "urgency": "medium"})
    for r in data.get("reminders") or []:
        due = (r.get("due") or r.get("date") or "")[:10]
        if due and due <= today and not r.get("done"):
            live_reminders.append({
                "kind": "Custom",
                "title": r.get("title") or r.get("note") or "Reminder",
                "due": due,
                "page": "reminders",
                "urgency": "medium",
                "id": r.get("id"),
            })

    search_hits = _fa_search_results(data, q) if (q and page == "search") else []

    # Resolve portal client names live (old tokens may only have client_id)
    for token, meta in list((data.get("portal_tokens") or {}).items()):
        if not isinstance(meta, dict):
            continue
        cid = meta.get("client_id")
        name = _fa_client_name(data, cid)
        if name and name != "—":
            meta["client_name"] = name
        elif not meta.get("client_name"):
            meta["client_name"] = "Client"

    # Reports: time by client, expenses by category
    client_names = {c.get("id"): (c.get("name") or "Client") for c in (data.get("clients") or [])}
    time_by_client = {}
    for t in data.get("time_entries") or []:
        cid = t.get("client_id") or ""
        name = client_names.get(cid) or (t.get("client_name") or "Unassigned")
        try:
            hrs = float(t.get("hours") or t.get("minutes") or 0)
            if t.get("minutes") and not t.get("hours"):
                hrs = float(t.get("minutes") or 0) / 60.0
        except Exception:
            hrs = 0.0
        time_by_client[name] = time_by_client.get(name, 0) + hrs
    time_by_client_list = sorted([{"name": k, "hours": round(v, 2)} for k, v in time_by_client.items()], key=lambda x: -x["hours"])
    exp_by_cat = {}
    for e in data.get("expenses") or []:
        cat = (e.get("category") or "General").strip() or "General"
        try:
            amt = float(e.get("amount") or 0)
        except Exception:
            amt = 0.0
        exp_by_cat[cat] = exp_by_cat.get(cat, 0) + amt
    expense_by_category = sorted([{"category": k, "amount": round(v, 2)} for k, v in exp_by_cat.items()], key=lambda x: -x["amount"])

    return render_template(
        "freelance_agency.html",
        module=mod,
        data=data,
        page=page,
        counts=counts,
        today=today,
        week=week,
        focus=focus,
        user=user,
        q=q,
        status_f=status_f,
        client_f=client_f,
        search_hits=search_hits,
        live_reminders=live_reminders,
        time_by_client_list=time_by_client_list,
        expense_by_category=expense_by_category,
        project_statuses=FA_PROJECT_STATUSES,
        task_statuses=FA_TASK_STATUSES,
        invoice_statuses=FA_INVOICE_STATUSES,
        client_statuses=FA_CLIENT_STATUSES,
        priorities=FA_PRIORITIES,
        site_name=site.get("site_name") or "Portfolio SaaS",
    )




@app.route("/os/freelance-agency/api/search")
@login_required
def freelance_agency_search_api():
    user = _fa_guard()
    if not user:
        return jsonify({"results": [], "error": "unauthorized"}), 403
    q = (request.args.get("q") or "").strip()
    data = load_freelance_agency(session["user"])
    results = _fa_search_results(data, q)
    # absolute-ish paths for frontend
    for r in results:
        r["url"] = url_for("freelance_agency", page=r["page"])
    return jsonify({"results": results, "q": q})


@app.route("/os/freelance-agency/action", methods=["POST"])
@login_required
def freelance_agency_action():
    user = _fa_guard()
    if not user:
        flash("Module locked", "warning")
        return redirect(url_for("subscription_page"))
    username = session["user"]
    data = load_freelance_agency(username)
    action = (request.form.get("action") or "").strip()
    page = (request.form.get("page") or "home").strip()

    def back(extra_page=None):
        save_freelance_agency(username, data)
        return redirect(url_for("freelance_agency", page=extra_page or page))

    if action == "add_client":
        name = (request.form.get("name") or "").strip()
        if name:
            data.setdefault("clients", []).insert(0, {
                "id": _fa_id(),
                "name": name[:200],
                "company": (request.form.get("company") or "").strip()[:200],
                "email": (request.form.get("email") or "").strip()[:200],
                "phone": (request.form.get("phone") or "").strip()[:40],
                "status": (request.form.get("status") or "Lead").strip(),
                "tags": (request.form.get("tags") or "").strip()[:200],
                "notes": (request.form.get("notes") or "").strip()[:2000],
                "created_at": datetime.now().isoformat(),
            })
            flash("Client added", "success")
        return back("clients")

    if action == "update_client":
        cid = request.form.get("item_id")
        for c in data.get("clients") or []:
            if c.get("id") == cid:
                for f in ("name", "company", "email", "phone", "status", "tags", "notes"):
                    if f in request.form:
                        c[f] = (request.form.get(f) or "").strip()
                break
        flash("Client updated", "success")
        return back("clients")

    if action == "delete_client":
        cid = request.form.get("item_id")
        data["clients"] = [c for c in (data.get("clients") or []) if c.get("id") != cid]
        flash("Client deleted", "success")
        return back("clients")

    if action == "add_project":
        title = (request.form.get("title") or "").strip()
        if title:
            data.setdefault("projects", []).insert(0, {
                "id": _fa_id(),
                "title": title[:300],
                "client_id": (request.form.get("client_id") or "").strip(),
                "status": (request.form.get("status") or "Lead").strip(),
                "deadline": (request.form.get("deadline") or "").strip()[:10],
                "budget": (request.form.get("budget") or "").strip()[:40],
                "priority": (request.form.get("priority") or "Medium").strip(),
                "notes": (request.form.get("notes") or "").strip()[:3000],
                "created_at": datetime.now().isoformat(),
            })
            flash("Project created", "success")
        return back("projects")

    if action == "update_project":
        pid = request.form.get("item_id")
        for p in data.get("projects") or []:
            if p.get("id") == pid:
                for f in ("title", "client_id", "status", "deadline", "budget", "priority", "notes"):
                    if f in request.form:
                        p[f] = (request.form.get(f) or "").strip()
                break
        flash("Project updated", "success")
        return back("projects")

    if action == "delete_project":
        pid = request.form.get("item_id")
        data["projects"] = [p for p in (data.get("projects") or []) if p.get("id") != pid]
        flash("Project deleted", "success")
        return back("projects")

    if action == "add_retainer":
        name = (request.form.get("name") or "").strip()
        if name:
            data.setdefault("retainers", []).insert(0, {
                "id": _fa_id(),
                "name": name[:200],
                "client_id": (request.form.get("client_id") or "").strip(),
                "monthly_fee": (request.form.get("monthly_fee") or "").strip()[:40],
                "hours": (request.form.get("hours") or "").strip()[:20],
                "status": (request.form.get("status") or "Active").strip(),
                "next_billing": (request.form.get("next_billing") or "").strip()[:10],
                "notes": (request.form.get("notes") or "").strip()[:2000],
                "created_at": datetime.now().isoformat(),
            })
            flash("Retainer added", "success")
        return back("retainers")

    if action == "update_retainer":
        rid = request.form.get("item_id")
        for r in data.get("retainers") or []:
            if r.get("id") == rid:
                for f in ("name", "client_id", "monthly_fee", "hours", "status", "next_billing", "notes"):
                    if f in request.form:
                        r[f] = (request.form.get(f) or "").strip()
                break
        flash("Retainer updated", "success")
        return back("retainers")

    if action == "delete_retainer":
        rid = request.form.get("item_id")
        data["retainers"] = [r for r in (data.get("retainers") or []) if r.get("id") != rid]
        flash("Retainer deleted", "success")
        return back("retainers")

    if action == "add_task":
        title = (request.form.get("title") or "").strip()
        if title:
            data.setdefault("tasks", []).insert(0, {
                "id": _fa_id(),
                "title": title[:300],
                "project_id": (request.form.get("project_id") or "").strip(),
                "client_id": (request.form.get("client_id") or "").strip(),
                "status": (request.form.get("status") or "Todo").strip(),
                "priority": (request.form.get("priority") or "Medium").strip(),
                "due": (request.form.get("due") or "").strip()[:10],
                "notes": (request.form.get("notes") or "").strip()[:2000],
                "created_at": datetime.now().isoformat(),
            })
            flash("Task added", "success")
        return back("tasks")

    if action == "update_task":
        tid = request.form.get("item_id")
        for t in data.get("tasks") or []:
            if t.get("id") == tid:
                for f in ("title", "project_id", "client_id", "status", "priority", "due", "notes"):
                    if f in request.form:
                        t[f] = (request.form.get(f) or "").strip()
                break
        flash("Task updated", "success")
        return back("tasks")

    if action == "delete_task":
        tid = request.form.get("item_id")
        data["tasks"] = [t for t in (data.get("tasks") or []) if t.get("id") != tid]
        flash("Task deleted", "success")
        return back("tasks")

    if action == "add_delivery":
        title = (request.form.get("title") or "").strip()
        if title:
            data.setdefault("deliveries", []).insert(0, {
                "id": _fa_id(),
                "title": title[:300],
                "project_id": (request.form.get("project_id") or "").strip(),
                "status": (request.form.get("status") or "Pending").strip(),
                "due_date": (request.form.get("due_date") or "").strip()[:10],
                "link": (request.form.get("link") or "").strip()[:500],
                "notes": (request.form.get("notes") or "").strip()[:2000],
                "created_at": datetime.now().isoformat(),
            })
            flash("Delivery logged", "success")
        return back("deliveries")

    if action == "update_delivery":
        did = request.form.get("item_id")
        for d in data.get("deliveries") or []:
            if d.get("id") == did:
                for f in ("title", "project_id", "status", "due_date", "link", "notes"):
                    if f in request.form:
                        d[f] = (request.form.get(f) or "").strip()
                break
        flash("Delivery updated", "success")
        return back("deliveries")

    if action == "delete_delivery":
        did = request.form.get("item_id")
        data["deliveries"] = [d for d in (data.get("deliveries") or []) if d.get("id") != did]
        flash("Delivery deleted", "success")
        return back("deliveries")

    if action == "add_invoice":
        amount = (request.form.get("amount") or "").strip()
        number = (request.form.get("number") or "").strip() or ("INV-" + _fa_id()[:6].upper())
        data.setdefault("invoices", []).insert(0, {
            "id": _fa_id(),
            "number": number[:40],
            "client_id": (request.form.get("client_id") or "").strip(),
            "amount": amount[:40],
            "status": (request.form.get("status") or "Draft").strip(),
            "due_date": (request.form.get("due_date") or "").strip()[:10],
            "issued_on": (request.form.get("issued_on") or _fa_today()).strip()[:10],
            "notes": (request.form.get("notes") or "").strip()[:2000],
            "recurring": (request.form.get("recurring") or "none").strip().lower(),  # none|monthly|weekly
            "next_issue": (request.form.get("next_issue") or "").strip()[:10],
            "created_at": datetime.now().isoformat(),
        })
        flash("Invoice created", "success")
        return back("invoices")

    if action == "update_invoice":
        iid = request.form.get("item_id")
        for inv in data.get("invoices") or []:
            if inv.get("id") == iid:
                for f in ("number", "client_id", "amount", "status", "due_date", "issued_on", "notes"):
                    if f in request.form:
                        inv[f] = (request.form.get(f) or "").strip()
                break
        flash("Invoice updated", "success")
        return back("invoices")

    if action == "delete_invoice":
        iid = request.form.get("item_id")
        data["invoices"] = [i for i in (data.get("invoices") or []) if i.get("id") != iid]
        flash("Invoice deleted", "success")
        return back("invoices")

    if action == "save_focus":
        week = (request.form.get("week") or _fa_week_key()).strip()
        data.setdefault("weekly_focus", {})[week] = {
            "week": week,
            "goals": (request.form.get("goals") or "").strip()[:3000],
            "priorities": (request.form.get("priorities") or "").strip()[:3000],
            "wins": (request.form.get("wins") or "").strip()[:3000],
            "notes": (request.form.get("notes") or "").strip()[:3000],
        }
        flash("Weekly focus saved", "success")
        return back("focus")

    if action == "save_fa_settings":
        s = data.get("settings") if isinstance(data.get("settings"), dict) else {}
        s["timezone"] = (request.form.get("timezone") or "Asia/Dhaka").strip()[:60]
        s["currency"] = (request.form.get("currency") or "USD").strip()[:10]
        s["hourly_rate"] = (request.form.get("hourly_rate") or "").strip()[:20]
        s["default_view"] = (request.form.get("default_view") or "home").strip()[:40]
        s["business_name"] = (request.form.get("business_name") or "").strip()[:200]
        s["business_email"] = (request.form.get("business_email") or "").strip()[:200]
        s["business_address"] = (request.form.get("business_address") or "").strip()[:500]
        s["smtp_host"] = (request.form.get("smtp_host") or "").strip()[:200]
        s["smtp_port"] = (request.form.get("smtp_port") or "587").strip()[:10]
        s["smtp_user"] = (request.form.get("smtp_user") or "").strip()[:200]
        if request.form.get("smtp_pass"):
            s["smtp_pass"] = (request.form.get("smtp_pass") or "").strip()[:200]
        s["smtp_from"] = (request.form.get("smtp_from") or "").strip()[:200]
        s["email_enabled"] = request.form.get("email_enabled") == "1"
        try:
            s["week_starts_on"] = int(request.form.get("week_starts_on") or 1)
        except Exception:
            s["week_starts_on"] = 1
        data["settings"] = s
        flash("Settings saved", "success")
        return back("settings")

    if action == "save_fa_openai_key":
        key = (request.form.get("openai_user_key") or "").strip()
        s = data.setdefault("settings", {})
        if key.lower() in ("clear", "remove", "-"):
            s.pop("openai_user_key", None)
            flash("API key removed", "success")
        elif key:
            s["openai_user_key"] = key[:200]
            flash("API key saved", "success")
        return back("settings")


    # ---- Messages ----
    if action == "add_message":
        subject = (request.form.get("subject") or "").strip()
        body = (request.form.get("body") or "").strip()
        client_id = (request.form.get("client_id") or "").strip()
        if subject and body:
            msg = {
                "id": _fa_id(),
                "client_id": client_id,
                "subject": subject[:300],
                "body": body[:5000],
                "channel": (request.form.get("channel") or "Email").strip(),
                "status": "Draft",
                "created_at": datetime.now().isoformat(),
            }
            data.setdefault("messages", []).insert(0, msg)
            flash("Message saved as draft", "success")
        return back("messages")

    if action == "send_message":
        mid = request.form.get("item_id")
        for msg in data.get("messages") or []:
            if msg.get("id") == mid:
                client = None
                for c in data.get("clients") or []:
                    if c.get("id") == msg.get("client_id"):
                        client = c
                        break
                to_email = (client or {}).get("email") or ""
                ok, info = _fa_send_email(data, to_email, msg.get("subject") or "", msg.get("body") or "")
                msg["status"] = "Sent" if ok else "Failed"
                msg["sent_at"] = datetime.now().isoformat()
                msg["send_info"] = info
                flash("Message sent" if ok else f"Send failed: {info}", "success" if ok else "danger")
                break
        return back("messages")

    if action == "delete_message":
        mid = request.form.get("item_id")
        data["messages"] = [m for m in (data.get("messages") or []) if m.get("id") != mid]
        flash("Message deleted", "success")
        return back("messages")

    if action == "update_message":
        mid = request.form.get("item_id")
        for msg in data.get("messages") or []:
            if msg.get("id") == mid:
                if msg.get("status") == "Sent":
                    flash("Sent messages cannot be edited. Use Resend.", "warning")
                    return back("messages")
                for f in ("subject", "body", "client_id", "channel"):
                    if f in request.form:
                        msg[f] = (request.form.get(f) or "").strip()
                msg["status"] = "Draft"
                break
        flash("Message updated", "success")
        return back("messages")

    if action == "resend_message":
        mid = request.form.get("item_id")
        for msg in data.get("messages") or []:
            if msg.get("id") == mid:
                client = None
                for c in data.get("clients") or []:
                    if c.get("id") == msg.get("client_id"):
                        client = c
                        break
                to_email = (client or {}).get("email") or ""
                ok, info = _fa_send_email(data, to_email, msg.get("subject") or "", msg.get("body") or "")
                msg["status"] = "Sent" if ok else "Failed"
                msg["sent_at"] = datetime.now().isoformat()
                msg["send_info"] = info
                flash("Message resent" if ok else f"Resend failed: {info}", "success" if ok else "danger")
                break
        return back("messages")

    # ---- Time entries ----
    if action == "add_time":
        hours = (request.form.get("hours") or "").strip()
        if hours:
            data.setdefault("time_entries", []).insert(0, {
                "id": _fa_id(),
                "date": (request.form.get("date") or _fa_today()).strip()[:10],
                "hours": hours[:20],
                "project_id": (request.form.get("project_id") or "").strip(),
                "client_id": (request.form.get("client_id") or "").strip(),
                "description": (request.form.get("description") or "").strip()[:1000],
                "billable": request.form.get("billable") == "1",
                "created_at": datetime.now().isoformat(),
            })
            flash("Time entry added", "success")
        return back("time")

    if action == "delete_time":
        tid = request.form.get("item_id")
        data["time_entries"] = [t for t in (data.get("time_entries") or []) if t.get("id") != tid]
        flash("Time entry deleted", "success")
        return back("time")

    if action == "update_time":
        tid = request.form.get("item_id")
        for te in data.get("time_entries") or []:
            if te.get("id") == tid:
                for f in ("date", "hours", "project_id", "client_id", "description"):
                    if f in request.form:
                        te[f] = (request.form.get(f) or "").strip()
                te["billable"] = request.form.get("billable") == "1"
                break
        flash("Time entry updated", "success")
        return back("time")

    # ---- Contracts ----
    if action == "add_contract":
        title = (request.form.get("title") or "").strip()
        if title:
            data.setdefault("contracts", []).insert(0, {
                "id": _fa_id(),
                "title": title[:300],
                "client_id": (request.form.get("client_id") or "").strip(),
                "status": (request.form.get("status") or "Draft").strip(),
                "value": (request.form.get("value") or "").strip()[:40],
                "start_date": (request.form.get("start_date") or "").strip()[:10],
                "end_date": (request.form.get("end_date") or "").strip()[:10],
                "body": (request.form.get("body") or "").strip()[:8000],
                "created_at": datetime.now().isoformat(),
            })
            flash("Contract / proposal saved", "success")
        return back("contracts")

    if action == "update_contract":
        cid = request.form.get("item_id")
        for c in data.get("contracts") or []:
            if c.get("id") == cid:
                for f in ("title", "client_id", "status", "value", "start_date", "end_date", "body"):
                    if f in request.form:
                        c[f] = (request.form.get(f) or "").strip()
                break
        flash("Contract updated", "success")
        return back("contracts")

    if action == "delete_contract":
        cid = request.form.get("item_id")
        data["contracts"] = [c for c in (data.get("contracts") or []) if c.get("id") != cid]
        flash("Contract deleted", "success")
        return back("contracts")

    # ---- Expenses ----
    if action == "add_expense":
        title = (request.form.get("title") or "").strip()
        amount = (request.form.get("amount") or "").strip()
        if title and amount:
            data.setdefault("expenses", []).insert(0, {
                "id": _fa_id(),
                "title": title[:300],
                "amount": amount[:40],
                "date": (request.form.get("date") or _fa_today()).strip()[:10],
                "category": (request.form.get("category") or "General").strip()[:80],
                "project_id": (request.form.get("project_id") or "").strip(),
                "client_id": (request.form.get("client_id") or "").strip(),
                "notes": (request.form.get("notes") or "").strip()[:1000],
                "created_at": datetime.now().isoformat(),
            })
            flash("Expense logged", "success")
        return back("expenses")

    if action == "delete_expense":
        eid = request.form.get("item_id")
        data["expenses"] = [e for e in (data.get("expenses") or []) if e.get("id") != eid]
        flash("Expense deleted", "success")
        return back("expenses")

    if action == "update_expense":
        eid = request.form.get("item_id")
        for e in data.get("expenses") or []:
            if e.get("id") == eid:
                for f in ("title", "amount", "date", "category", "project_id", "client_id", "notes"):
                    if f in request.form:
                        e[f] = (request.form.get(f) or "").strip()
                break
        flash("Expense updated", "success")
        return back("expenses")

    # ---- Custom reminders ----
    if action == "add_reminder":
        title = (request.form.get("title") or "").strip()
        due = (request.form.get("due") or "").strip()[:10]
        if title and due:
            data.setdefault("reminders", []).insert(0, {
                "id": _fa_id(),
                "title": title[:300],
                "due": due,
                "note": (request.form.get("note") or "").strip()[:1000],
                "done": False,
                "created_at": datetime.now().isoformat(),
            })
            flash("Reminder added", "success")
        else:
            flash("Title and due date required", "warning")
        return back("reminders")

    if action == "delete_reminder":
        rid = request.form.get("item_id")
        data["reminders"] = [r for r in (data.get("reminders") or []) if r.get("id") != rid]
        flash("Reminder deleted", "success")
        return back("reminders")

    if action == "toggle_reminder":
        rid = request.form.get("item_id")
        for r in data.get("reminders") or []:
            if r.get("id") == rid:
                r["done"] = not r.get("done")
                break
        flash("Reminder updated", "success")
        return back("reminders")

    # ---- Portal token ----
    if action == "create_portal_link":
        client_id = (request.form.get("client_id") or "").strip()
        if client_id:
            token = uuid.uuid4().hex
            cname = _fa_client_name(data, client_id)
            data.setdefault("portal_tokens", {})[token] = {
                "client_id": client_id,
                "client_name": cname,
                "created_at": datetime.now().isoformat(),
            }
            save_freelance_agency(username, data)
            full = request.url_root.rstrip("/") + f"/portal/fa/{username}/{token}"
            flash(f"Portal link created: {full}", "success")
        return back("portal")

    if action == "revoke_portal":
        token = request.form.get("token")
        data.get("portal_tokens", {}).pop(token, None)
        flash("Portal link revoked", "success")
        return back("portal")

    # ---- AI assist ----
    if action == "fa_ai_generate":
        prompt = (request.form.get("prompt") or "").strip()
        kind = (request.form.get("kind") or "general").strip()
        key, _prov, _model, _src = resolve_ai_api_key((data.get("settings") or {}).get("openai_user_key") or "")
        result = ""
        if not prompt:
            flash("Enter a prompt", "warning")
            return back("ai")
        if key:
            try:
                import urllib.request
                body = json.dumps({
                    "model": os.environ.get("OPENAI_MODEL") or "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": "You help freelancers write professional proposals, follow-ups, and client emails. Be concise."},
                        {"role": "user", "content": f"[{kind}] {prompt}"},
                    ],
                    "max_tokens": 800,
                }).encode("utf-8")
                req = urllib.request.Request(
                    "https://api.openai.com/v1/chat/completions",
                    data=body,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=45) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                result = payload["choices"][0]["message"]["content"]
            except Exception as e:
                result = f"(AI error: {e})\n\nDraft based on your prompt:\n{prompt}"
        else:
            result = (
                f"[Demo mode — add OpenAI API key in Settings for live AI]\n\n"
                f"Kind: {kind}\n\nSuggested draft:\n\n"
                f"Subject: Follow-up regarding your project\n\n"
                f"Hi,\n\nThank you for the opportunity. Based on your notes:\n{prompt}\n\n"
                f"I propose we proceed with a clear scope, timeline, and milestone-based billing.\n\nBest regards"
            )
        data.setdefault("ai_log", []).insert(0, {
            "id": _fa_id(),
            "kind": kind,
            "prompt": prompt[:2000],
            "result": result[:8000],
            "created_at": datetime.now().isoformat(),
        })
        flash("AI draft generated", "success")
        return back("ai")

    # ---- Email invoice ----
    if action == "generate_recurring_invoices":
        from datetime import timedelta as _td
        today = _fa_today()
        made = 0
        for inv in list(data.get("invoices") or []):
            recur = (inv.get("recurring") or "none").lower()
            if recur not in ("monthly", "weekly"):
                continue
            next_issue = (inv.get("next_issue") or inv.get("due_date") or inv.get("issued_on") or "")[:10]
            if not next_issue or next_issue > today:
                continue
            # create next invoice
            clone = {k: v for k, v in inv.items() if k not in ("id", "created_at", "status")}
            clone["id"] = _fa_id()
            clone["status"] = "Draft"
            clone["issued_on"] = today
            try:
                base = datetime.strptime(next_issue, "%Y-%m-%d").date()
            except Exception:
                base = datetime.now().date()
            if recur == "weekly":
                nxt = (base + _td(days=7)).strftime("%Y-%m-%d")
            else:
                nxt = (base + _td(days=30)).strftime("%Y-%m-%d")
            clone["due_date"] = nxt
            clone["next_issue"] = nxt
            clone["recurring"] = recur
            clone["created_at"] = datetime.now().isoformat()
            clone["notes"] = ((inv.get("notes") or "") + f"\n(Recurring from {inv.get('id')})").strip()
            data.setdefault("invoices", []).insert(0, clone)
            inv["next_issue"] = nxt
            made += 1
        flash(f"Generated {made} recurring invoice(s)", "success")
        return back("invoices")

    if action == "email_invoice":
        iid = request.form.get("item_id")
        inv = next((i for i in (data.get("invoices") or []) if i.get("id") == iid), None)
        if not inv:
            flash("Invoice not found", "danger")
            return back("invoices")
        client = next((c for c in (data.get("clients") or []) if c.get("id") == inv.get("client_id")), None)
        to_email = (client or {}).get("email") or ""
        cur = (data.get("settings") or {}).get("currency") or "USD"
        subject = f"Invoice {inv.get('number') or iid}"
        body = (
            f"Hello {(client or {}).get('name') or 'there'},\n\n"
            f"Please find your invoice details:\n"
            f"Invoice: {inv.get('number')}\nAmount: {inv.get('amount')} {cur}\n"
            f"Due: {inv.get('due_date') or '—'}\nStatus: {inv.get('status')}\n\n"
            f"{inv.get('notes') or ''}\n\n"
            f"You can also view it in your client portal if a link was shared.\n\nThank you."
        )
        ok, info = _fa_send_email(data, to_email, subject, body)
        if ok:
            inv["status"] = "Sent" if (inv.get("status") or "").lower() == "draft" else inv.get("status")
            inv["emailed_at"] = datetime.now().isoformat()
        flash("Invoice emailed" if ok else f"Email failed: {info}", "success" if ok else "danger")
        return back("invoices")


    if action == "export_fa":
        save_freelance_agency(username, data)
        from flask import Response
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        return Response(
            payload,
            mimetype="application/json",
            headers={"Content-Disposition": f"attachment; filename=freelance-agency-{username}.json"},
        )

    if action == "import_fa":
        f = request.files.get("file")
        if f and f.filename:
            try:
                incoming = json.loads(f.read().decode("utf-8"))
                if isinstance(incoming, dict):
                    for k in DEFAULT_FREELANCE_AGENCY.keys():
                        if k in incoming:
                            data[k] = incoming[k]
                    flash("Import merged successfully", "success")
                else:
                    flash("Invalid JSON structure", "danger")
            except Exception as e:
                flash(f"Import failed: {e}", "danger")
        return back("settings")

    flash("Unknown action", "warning")
    return back()



def _fa_send_email(data, to_email, subject, body):
    """Send email via user SMTP settings. Returns (ok, message)."""
    to_email = (to_email or "").strip()
    if not to_email or "@" not in to_email:
        return False, "Client has no valid email"
    s = data.get("settings") or {}
    host = (s.get("smtp_host") or "").strip()
    if not host or not s.get("email_enabled"):
        # Log as simulated send when SMTP not configured
        return True, "Queued (SMTP not configured — mark as sent for demo). Add SMTP in Settings for real delivery."
    try:
        import smtplib
        from email.mime.text import MIMEText
        port = int(s.get("smtp_port") or 587)
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = (s.get("smtp_from") or s.get("smtp_user") or s.get("business_email") or "noreply@localhost")
        msg["To"] = to_email
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            smtp.starttls()
            user, pw = s.get("smtp_user") or "", s.get("smtp_pass") or ""
            if user:
                smtp.login(user, pw)
            smtp.sendmail(msg["From"], [to_email], msg.as_string())
        return True, "Delivered via SMTP"
    except Exception as e:
        return False, str(e)


@app.route("/os/freelance-agency/invoice/<invoice_id>/pdf")
@login_required
def fa_invoice_pdf(invoice_id):
    user = _fa_guard()
    if not user:
        flash("Module locked", "warning")
        return redirect(url_for("subscription_page"))
    data = load_freelance_agency(session["user"])
    inv = next((i for i in (data.get("invoices") or []) if i.get("id") == invoice_id), None)
    if not inv:
        flash("Invoice not found", "danger")
        return redirect(url_for("freelance_agency", page="invoices"))
    client = next((c for c in (data.get("clients") or []) if c.get("id") == inv.get("client_id")), None)
    s = data.get("settings") or {}
    # Printable HTML (browser Print → Save as PDF)
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Invoice {inv.get('number')}</title>
    <style>
    body{{font-family:system-ui,sans-serif;max-width:720px;margin:40px auto;color:#0f172a;padding:24px}}
    h1{{margin:0 0 4px}}.muted{{color:#64748b}}table{{width:100%;border-collapse:collapse;margin-top:24px}}
    th,td{{text-align:left;padding:10px;border-bottom:1px solid #e2e8f0}}
    .total{{font-size:1.4rem;font-weight:700;margin-top:16px}}
    @media print{{.no-print{{display:none}}}}
    </style></head><body>
    <div class="no-print" style="margin-bottom:16px"><button onclick="window.print()">Print / Save as PDF</button>
    <a href="javascript:history.back()">Back</a></div>
    <h1>INVOICE</h1>
    <p class="muted">{(s.get('business_name') or user.get('full_name') or session.get('user'))}</p>
    <p class="muted">{(s.get('business_email') or '')}<br>{(s.get('business_address') or '')}</p>
    <hr>
    <p><b>Bill to:</b> {(client or {}).get('name') or '—'}<br>
    {(client or {}).get('company') or ''}<br>{(client or {}).get('email') or ''}</p>
    <p><b>Invoice #</b> {inv.get('number') or invoice_id}<br>
    <b>Issued:</b> {inv.get('issued_on') or '—'} · <b>Due:</b> {inv.get('due_date') or '—'} · <b>Status:</b> {inv.get('status')}</p>
    <table><thead><tr><th>Description</th><th>Amount</th></tr></thead>
    <tbody><tr><td>{inv.get('notes') or 'Professional services'}</td><td>{inv.get('amount') or '—'} {s.get('currency') or 'USD'}</td></tr></tbody></table>
    <p class="total">Total: {inv.get('amount') or '—'} {s.get('currency') or 'USD'}</p>
    <p class="muted">Generated by Freelance & Agency OS</p>
    </body></html>"""
    return html


@app.route("/portal/fa/<owner>/<token>")
def fa_client_portal(owner, token):
    """Public client portal — view invoices for linked client (read-only)."""
    data = load_freelance_agency(owner)
    meta = (data.get("portal_tokens") or {}).get(token)
    if not meta:
        return "<h2>Invalid or revoked portal link</h2>", 404
    client_id = meta.get("client_id")
    client = next((c for c in (data.get("clients") or []) if c.get("id") == client_id), None)
    invoices = [i for i in (data.get("invoices") or []) if i.get("client_id") == client_id]
    contracts = [c for c in (data.get("contracts") or []) if c.get("client_id") == client_id]
    s = data.get("settings") or {}
    rows = "".join(
        f"<tr><td>{i.get('number')}</td><td>{i.get('amount')} {s.get('currency') or ''}</td>"
        f"<td>{i.get('status')}</td><td>{i.get('due_date') or '—'}</td></tr>"
        for i in invoices
    ) or "<tr><td colspan=4>No invoices</td></tr>"
    crow = "".join(
        f"<tr><td>{c.get('title')}</td><td>{c.get('status')}</td><td>{c.get('value') or '—'}</td></tr>"
        for c in contracts
    ) or "<tr><td colspan=3>No contracts</td></tr>"
    name = (client or {}).get("name") or "Client"
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Client Portal</title>
    <style>body{{font-family:system-ui;max-width:800px;margin:40px auto;padding:20px;background:#f8fafc}}
    .card{{background:#fff;border-radius:12px;padding:20px;margin-bottom:16px;border:1px solid #e2e8f0}}
    table{{width:100%;border-collapse:collapse}}td,th{{padding:8px;border-bottom:1px solid #e2e8f0;text-align:left}}</style></head>
    <body><div class="card"><h1>Client Portal</h1><p>Welcome, <b>{name}</b></p>
    <p class="muted">{s.get('business_name') or owner}</p></div>
    <div class="card"><h2>Invoices</h2><table><tr><th>Number</th><th>Amount</th><th>Status</th><th>Due</th></tr>{rows}</table></div>
    <div class="card"><h2>Contracts</h2><table><tr><th>Title</th><th>Status</th><th>Value</th></tr>{crow}</table></div>
    </body></html>"""




# ==================== STUDENT PRODUCTIVITY SYSTEM ====================
SP_MODULE_ID = "student-productivity"
SP_GRADE_POINTS = {
    "A+": 4.0, "A": 4.0, "A-": 3.7,
    "B+": 3.3, "B": 3.0, "B-": 2.7,
    "C+": 2.3, "C": 2.0, "C-": 1.7,
    "D+": 1.3, "D": 1.0, "F": 0.0,
}
DEFAULT_STUDENT_PRODUCTIVITY = {
    "classes": [],
    "assignments": [],
    "exams": [],
    "notes": [],
    "study_plan": [],
    "resources": [],
    "sessions": [],
    "flashcards": [],
    "attendance": [],
    "goals": [],
    "ai_log": [],
    "settings": {
        "semester": "",
        "target_gpa": "3.5",
        "timezone": "Asia/Dhaka",
        "week_starts_on": 1,
        "openai_user_key": "",
    },
}


def sp_path(username):
    d = MODULES_DIR / SP_MODULE_ID
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{username}.json"


def load_student_productivity(username):
    path = sp_path(username)
    base = json.loads(json.dumps(DEFAULT_STUDENT_PRODUCTIVITY))
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for k, v in base.items():
                    if k not in raw:
                        raw[k] = v
                    elif k == "settings" and isinstance(v, dict):
                        merged = dict(v)
                        merged.update(raw.get("settings") or {})
                        raw["settings"] = merged
                for key in ("classes", "assignments", "exams", "notes", "study_plan", "resources", "sessions", "flashcards", "attendance", "goals", "ai_log"):
                    if not isinstance(raw.get(key), list):
                        raw[key] = []
                return raw
        except Exception:
            pass
    return base


def save_student_productivity(username, data):
    path = sp_path(username)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _sp_id():
    return uuid.uuid4().hex[:12]


def _sp_today():
    return datetime.now().strftime("%Y-%m-%d")


def _sp_class_name(data, class_id):
    for c in data.get("classes") or []:
        if c.get("id") == class_id:
            return c.get("name") or c.get("code") or "Class"
    return "—"


def _sp_gpa(data):
    total_pts = 0.0
    total_cr = 0.0
    for c in data.get("classes") or []:
        g = (c.get("grade") or "").strip().upper()
        if g not in SP_GRADE_POINTS:
            continue
        try:
            cr = float(c.get("credits") or 0)
        except Exception:
            cr = 0
        if cr <= 0:
            continue
        total_pts += SP_GRADE_POINTS[g] * cr
        total_cr += cr
    if total_cr <= 0:
        return "—"
    return f"{(total_pts / total_cr):.2f}"


def sp_counts(data):
    classes = data.get("classes") or []
    assignments = data.get("assignments") or []
    exams = data.get("exams") or []
    notes = data.get("notes") or []
    sessions = data.get("sessions") or []
    today = _sp_today()
    active_classes = sum(1 for c in classes if (c.get("status") or "Active").lower() == "active")
    open_asg = sum(1 for a in assignments if (a.get("status") or "").lower() not in ("done", "completed"))
    upcoming = sum(1 for e in exams if (e.get("status") or "Upcoming").lower() == "upcoming")
    overdue = 0
    for a in assignments:
        due = (a.get("due") or "")[:10]
        st = (a.get("status") or "").lower()
        if due and due < today and st not in ("done", "completed"):
            overdue += 1
    hours = 0.0
    for s in sessions:
        try:
            hours += float(s.get("minutes") or 0) / 60.0
        except Exception:
            pass
    flashcards = data.get("flashcards") or []
    goals = data.get("goals") or []
    goals_open = sum(1 for g in goals if (g.get("status") or "Open").lower() not in ("done", "completed"))
    return {
        "classes": len(classes),
        "active_classes": active_classes,
        "assignments": len(assignments),
        "open_assignments": open_asg,
        "exams": len(exams),
        "upcoming_exams": upcoming,
        "notes": len(notes),
        "overdue": overdue,
        "study_hours": round(hours, 1),
        "gpa": _sp_gpa(data),
        "flashcards": len(flashcards),
        "goals_open": goals_open,
        "attendance": len(data.get("attendance") or []),
    }


def _sp_guard():
    user = get_user(session.get("user"))
    if not user or not user_has_module(user, SP_MODULE_ID):
        return None
    return user


def _sp_search_results(data, q):
    q = (q or "").strip().lower()
    hits = []
    if not q:
        return hits
    for c in data.get("classes") or []:
        blob = " ".join([str(c.get(k) or "") for k in ("name", "code", "instructor", "schedule")]).lower()
        if q in blob:
            hits.append({"kind": "Class", "title": c.get("name") or c.get("code"), "page": "classes", "id": c.get("id")})
    for a in data.get("assignments") or []:
        blob = " ".join([str(a.get(k) or "") for k in ("title", "notes", "status")]).lower()
        if q in blob:
            hits.append({"kind": "Assignment", "title": a.get("title"), "page": "assignments", "id": a.get("id")})
    for e in data.get("exams") or []:
        blob = " ".join([str(e.get(k) or "") for k in ("title", "location", "notes")]).lower()
        if q in blob:
            hits.append({"kind": "Exam", "title": e.get("title"), "page": "exams", "id": e.get("id")})
    for n in data.get("notes") or []:
        blob = " ".join([str(n.get(k) or "") for k in ("title", "body", "tags")]).lower()
        if q in blob:
            hits.append({"kind": "Note", "title": n.get("title"), "page": "notes", "id": n.get("id")})
    for r in data.get("resources") or []:
        blob = " ".join([str(r.get(k) or "") for k in ("title", "url", "notes")]).lower()
        if q in blob:
            hits.append({"kind": "Resource", "title": r.get("title"), "page": "resources", "id": r.get("id")})
    for f in data.get("flashcards") or []:
        blob = " ".join([str(f.get(k) or "") for k in ("front", "back")]).lower()
        if q in blob:
            hits.append({"kind": "Flashcard", "title": f.get("front"), "page": "flashcards", "id": f.get("id")})
    for g in data.get("goals") or []:
        blob = " ".join([str(g.get(k) or "") for k in ("title", "notes")]).lower()
        if q in blob:
            hits.append({"kind": "Goal", "title": g.get("title"), "page": "goals", "id": g.get("id")})
    return hits[:40]


@app.route("/os/student-productivity")
@app.route("/os/student-productivity/<page>")
@login_required
def student_productivity(page="home"):
    user = _sp_guard()
    if not user:
        flash("Student Productivity System is not unlocked on your account.", "warning")
        return redirect(url_for("subscription_page"))
    site = load_site_settings()
    modules = {m["id"]: m for m in get_modules(site)}
    mod = modules.get(SP_MODULE_ID) or {
        "id": SP_MODULE_ID,
        "name": "Student Productivity System",
        "icon": "🎓",
        "desc": "Classes, assignments, notes & exams",
    }
    data = load_student_productivity(session["user"])
    allowed = {
        "home", "start-here", "classes", "assignments", "exams", "notes",
        "schedule", "timetable", "gpa", "resources", "sessions", "flashcards", "review", "focus",
        "attendance", "goals", "ai", "settings", "search",
    }
    if page not in allowed:
        page = "home"
    q = (request.args.get("q") or "").strip()
    counts = sp_counts(data)
    today = _sp_today()

    for c in data.get("classes") or []:
        g = (c.get("grade") or "").strip().upper()
        c["_points"] = SP_GRADE_POINTS.get(g, "—")
    for a in data.get("assignments") or []:
        a["_class_name"] = _sp_class_name(data, a.get("class_id"))
    for e in data.get("exams") or []:
        e["_class_name"] = _sp_class_name(data, e.get("class_id"))
    for n in data.get("notes") or []:
        n["_class_name"] = _sp_class_name(data, n.get("class_id"))
    for p in data.get("study_plan") or []:
        p["_class_name"] = _sp_class_name(data, p.get("class_id"))
    for r in data.get("resources") or []:
        r["_class_name"] = _sp_class_name(data, r.get("class_id"))
    for s in data.get("sessions") or []:
        s["_class_name"] = _sp_class_name(data, s.get("class_id"))
    for f in data.get("flashcards") or []:
        f["_class_name"] = _sp_class_name(data, f.get("class_id"))
    for a in data.get("attendance") or []:
        a["_class_name"] = _sp_class_name(data, a.get("class_id"))

    # Attendance summary by class
    attendance_summary = []
    for c in data.get("classes") or []:
        rows = [x for x in (data.get("attendance") or []) if x.get("class_id") == c.get("id")]
        if not rows:
            continue
        present = sum(1 for x in rows if (x.get("status") or "").lower() == "present")
        absent = sum(1 for x in rows if (x.get("status") or "").lower() == "absent")
        late = sum(1 for x in rows if (x.get("status") or "").lower() == "late")
        total = present + absent + late
        rate = round(100.0 * (present + 0.5 * late) / total, 1) if total else 0
        attendance_summary.append({
            "name": c.get("name") or c.get("code") or "Class",
            "present": present, "absent": absent, "late": late, "rate": rate,
        })

    # Due soon (7 days)
    due_soon = []
    from datetime import timedelta
    try:
        end = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    except Exception:
        end = today
    for a in data.get("assignments") or []:
        due = (a.get("due") or "")[:10]
        st = (a.get("status") or "").lower()
        if due and today <= due <= end and st not in ("done", "completed"):
            due_soon.append({"kind": "Assignment", "title": a.get("title"), "due": due, "page": "assignments"})
    for e in data.get("exams") or []:
        due = (e.get("date") or "")[:10]
        if due and today <= due <= end and (e.get("status") or "Upcoming").lower() == "upcoming":
            due_soon.append({"kind": "Exam", "title": e.get("title"), "due": due, "page": "exams"})
    due_soon.sort(key=lambda x: x.get("due") or "")

    search_hits = _sp_search_results(data, q) if (q and page == "search") else []

    # Spaced-repetition due cards
    due_cards = []
    for f in data.get("flashcards") or []:
        nr = (f.get("next_review") or f.get("created_at") or today)[:10]
        f["_class_name"] = _sp_class_name(data, f.get("class_id"))
        f["_due"] = (not nr) or nr <= today
        if f["_due"]:
            due_cards.append(f)
    # exam countdown days
    exam_countdown = []
    for e in data.get("exams") or []:
        d = (e.get("date") or "")[:10]
        if not d:
            continue
        try:
            delta = (datetime.strptime(d, "%Y-%m-%d").date() - datetime.now().date()).days
        except Exception:
            continue
        if (e.get("status") or "Upcoming").lower() == "upcoming" and delta >= 0:
            exam_countdown.append({
                "title": e.get("title"),
                "date": d,
                "days": delta,
                "class_name": _sp_class_name(data, e.get("class_id")),
                "id": e.get("id"),
            })
    exam_countdown.sort(key=lambda x: x["days"])

    # attach class names on flashcards always
    for f in data.get("flashcards") or []:
        f["_class_name"] = _sp_class_name(data, f.get("class_id"))

    counts["due_cards"] = len(due_cards)

    return render_template(
        "student_productivity.html",
        module=mod,
        data=data,
        page=page,
        counts=counts,
        today=today,
        q=q,
        search_hits=search_hits,
        due_soon=due_soon[:10],
        due_cards=due_cards,
        exam_countdown=exam_countdown[:8],
        attendance_summary=attendance_summary,
        user=user,
        grade_options=list(SP_GRADE_POINTS.keys()),
        site_name=site.get("site_name") or "Portfolio SaaS",
    )


@app.route("/os/student-productivity/api/search")
@login_required
def student_productivity_search_api():
    user = _sp_guard()
    if not user:
        return jsonify({"results": [], "error": "unauthorized"}), 403
    q = (request.args.get("q") or "").strip()
    data = load_student_productivity(session["user"])
    results = _sp_search_results(data, q)
    for r in results:
        r["url"] = url_for("student_productivity", page=r["page"])
    return jsonify({"results": results, "q": q})


@app.route("/os/student-productivity/action", methods=["POST"])
@login_required
def student_productivity_action():
    user = _sp_guard()
    if not user:
        flash("Module locked", "warning")
        return redirect(url_for("subscription_page"))
    username = session["user"]
    data = load_student_productivity(username)
    action = (request.form.get("action") or "").strip()
    page = (request.form.get("page") or "home").strip()

    def back(extra_page=None):
        save_student_productivity(username, data)
        return redirect(url_for("student_productivity", page=extra_page or page))

    # ---- Classes ----
    if action == "add_class":
        name = (request.form.get("name") or "").strip()
        if name:
            data.setdefault("classes", []).insert(0, {
                "id": _sp_id(),
                "name": name[:200],
                "code": (request.form.get("code") or "").strip()[:40],
                "credits": (request.form.get("credits") or "").strip()[:10],
                "instructor": (request.form.get("instructor") or "").strip()[:120],
                "status": (request.form.get("status") or "Active").strip(),
                "schedule": (request.form.get("schedule") or "").strip()[:120],
                "semester": (request.form.get("semester") or "").strip()[:80],
                "syllabus": (request.form.get("syllabus") or "").strip()[:8000],
                "grade": "",
                "created_at": datetime.now().isoformat(),
            })
            flash("Class added", "success")
        return back("classes")

    if action == "update_class":
        cid = request.form.get("item_id")
        for c in data.get("classes") or []:
            if c.get("id") == cid:
                for f in ("name", "code", "credits", "instructor", "status", "schedule", "semester", "syllabus"):
                    if f in request.form:
                        c[f] = (request.form.get(f) or "").strip()
                break
        flash("Class updated", "success")
        return back("classes")

    if action == "delete_class":
        cid = request.form.get("item_id")
        data["classes"] = [c for c in (data.get("classes") or []) if c.get("id") != cid]
        flash("Class deleted", "success")
        return back("classes")

    if action == "set_class_grade":
        cid = request.form.get("item_id")
        grade = (request.form.get("grade") or "").strip().upper()
        for c in data.get("classes") or []:
            if c.get("id") == cid:
                c["grade"] = grade
                break
        flash("Grade saved", "success")
        return back("gpa")

    # ---- Assignments ----
    if action == "add_assignment":
        title = (request.form.get("title") or "").strip()
        if title:
            data.setdefault("assignments", []).insert(0, {
                "id": _sp_id(),
                "title": title[:300],
                "class_id": (request.form.get("class_id") or "").strip(),
                "due": (request.form.get("due") or "").strip()[:10],
                "status": (request.form.get("status") or "Todo").strip(),
                "priority": (request.form.get("priority") or "Medium").strip(),
                "grade": (request.form.get("grade") or "").strip()[:40],
                "notes": (request.form.get("notes") or "").strip()[:2000],
                "created_at": datetime.now().isoformat(),
            })
            flash("Assignment added", "success")
        return back("assignments")

    if action == "update_assignment":
        aid = request.form.get("item_id")
        for a in data.get("assignments") or []:
            if a.get("id") == aid:
                for f in ("title", "class_id", "due", "status", "priority", "grade", "notes"):
                    if f in request.form:
                        a[f] = (request.form.get(f) or "").strip()
                break
        flash("Assignment updated", "success")
        return back("assignments")

    if action == "delete_assignment":
        aid = request.form.get("item_id")
        data["assignments"] = [a for a in (data.get("assignments") or []) if a.get("id") != aid]
        flash("Assignment deleted", "success")
        return back("assignments")

    # ---- Exams ----
    if action == "add_exam":
        title = (request.form.get("title") or "").strip()
        if title:
            data.setdefault("exams", []).insert(0, {
                "id": _sp_id(),
                "title": title[:300],
                "class_id": (request.form.get("class_id") or "").strip(),
                "date": (request.form.get("date") or "").strip()[:10],
                "location": (request.form.get("location") or "").strip()[:120],
                "status": (request.form.get("status") or "Upcoming").strip(),
                "score": (request.form.get("score") or "").strip()[:40],
                "notes": (request.form.get("notes") or "").strip()[:2000],
                "created_at": datetime.now().isoformat(),
            })
            flash("Exam added", "success")
        return back("exams")

    if action == "update_exam":
        eid = request.form.get("item_id")
        for e in data.get("exams") or []:
            if e.get("id") == eid:
                for f in ("title", "class_id", "date", "location", "status", "score", "notes"):
                    if f in request.form:
                        e[f] = (request.form.get(f) or "").strip()
                break
        flash("Exam updated", "success")
        return back("exams")

    if action == "delete_exam":
        eid = request.form.get("item_id")
        data["exams"] = [e for e in (data.get("exams") or []) if e.get("id") != eid]
        flash("Exam deleted", "success")
        return back("exams")

    # ---- Notes ----
    if action == "add_note":
        title = (request.form.get("title") or "").strip()
        if title:
            data.setdefault("notes", []).insert(0, {
                "id": _sp_id(),
                "title": title[:300],
                "class_id": (request.form.get("class_id") or "").strip(),
                "tags": (request.form.get("tags") or "").strip()[:200],
                "body": (request.form.get("body") or "").strip()[:10000],
                "created_at": datetime.now().isoformat(),
            })
            flash("Note saved", "success")
        return back("notes")

    if action == "update_note":
        nid = request.form.get("item_id")
        for n in data.get("notes") or []:
            if n.get("id") == nid:
                for f in ("title", "class_id", "tags", "body"):
                    if f in request.form:
                        n[f] = (request.form.get(f) or "").strip()
                break
        flash("Note updated", "success")
        return back("notes")

    if action == "delete_note":
        nid = request.form.get("item_id")
        data["notes"] = [n for n in (data.get("notes") or []) if n.get("id") != nid]
        flash("Note deleted", "success")
        return back("notes")

    # ---- Study plan ----
    if action == "add_plan":
        title = (request.form.get("title") or "").strip()
        if title:
            data.setdefault("study_plan", []).insert(0, {
                "id": _sp_id(),
                "title": title[:300],
                "class_id": (request.form.get("class_id") or "").strip(),
                "day": (request.form.get("day") or "Any day").strip(),
                "duration": (request.form.get("duration") or "").strip()[:20],
                "status": (request.form.get("status") or "Planned").strip(),
                "notes": (request.form.get("notes") or "").strip()[:2000],
                "created_at": datetime.now().isoformat(),
            })
            flash("Plan item added", "success")
        return back("schedule")

    if action == "update_plan":
        pid = request.form.get("item_id")
        for p in data.get("study_plan") or []:
            if p.get("id") == pid:
                for f in ("title", "class_id", "day", "duration", "status", "notes"):
                    if f in request.form:
                        p[f] = (request.form.get(f) or "").strip()
                break
        flash("Plan updated", "success")
        return back("schedule")

    if action == "delete_plan":
        pid = request.form.get("item_id")
        data["study_plan"] = [p for p in (data.get("study_plan") or []) if p.get("id") != pid]
        flash("Plan item deleted", "success")
        return back("schedule")

    # ---- Resources ----
    if action == "add_resource":
        title = (request.form.get("title") or "").strip()
        if title:
            url = (request.form.get("url") or "").strip()
            if url and not url.startswith(("http://", "https://")):
                url = "https://" + url
            data.setdefault("resources", []).insert(0, {
                "id": _sp_id(),
                "title": title[:300],
                "type": (request.form.get("type") or "Link").strip(),
                "class_id": (request.form.get("class_id") or "").strip(),
                "url": url[:500],
                "notes": (request.form.get("notes") or "").strip()[:2000],
                "created_at": datetime.now().isoformat(),
            })
            flash("Resource added", "success")
        return back("resources")

    if action == "update_resource":
        rid = request.form.get("item_id")
        for r in data.get("resources") or []:
            if r.get("id") == rid:
                for f in ("title", "type", "class_id", "notes"):
                    if f in request.form:
                        r[f] = (request.form.get(f) or "").strip()
                if "url" in request.form:
                    url = (request.form.get("url") or "").strip()
                    if url and not url.startswith(("http://", "https://")):
                        url = "https://" + url
                    r["url"] = url[:500]
                break
        flash("Resource updated", "success")
        return back("resources")

    if action == "delete_resource":
        rid = request.form.get("item_id")
        data["resources"] = [r for r in (data.get("resources") or []) if r.get("id") != rid]
        flash("Resource deleted", "success")
        return back("resources")

    # ---- Sessions ----
    if action == "add_session":
        minutes = (request.form.get("minutes") or "").strip()
        if minutes:
            data.setdefault("sessions", []).insert(0, {
                "id": _sp_id(),
                "date": (request.form.get("date") or _sp_today()).strip()[:10],
                "minutes": minutes[:20],
                "class_id": (request.form.get("class_id") or "").strip(),
                "topic": (request.form.get("topic") or "").strip()[:200],
                "notes": (request.form.get("notes") or "").strip()[:2000],
                "created_at": datetime.now().isoformat(),
            })
            flash("Session logged", "success")
        return back("sessions")

    if action == "update_session":
        sid = request.form.get("item_id")
        for s in data.get("sessions") or []:
            if s.get("id") == sid:
                for f in ("date", "minutes", "class_id", "topic", "notes"):
                    if f in request.form:
                        s[f] = (request.form.get(f) or "").strip()
                break
        flash("Session updated", "success")
        return back("sessions")

    if action == "delete_session":
        sid = request.form.get("item_id")
        data["sessions"] = [s for s in (data.get("sessions") or []) if s.get("id") != sid]
        flash("Session deleted", "success")
        return back("sessions")

    # ---- Flashcards ----
    if action == "add_flash":
        front = (request.form.get("front") or "").strip()
        card_back = (request.form.get("back") or "").strip()
        if front and card_back:
            data.setdefault("flashcards", []).insert(0, {
                "id": _sp_id(),
                "front": front[:500],
                "back": card_back[:2000],
                "class_id": (request.form.get("class_id") or "").strip(),
                "created_at": datetime.now().isoformat(),
                "ease": 2.5,
                "interval": 0,
                "reps": 0,
                "next_review": _sp_today(),
                "last_result": "",
            })
            flash("Flashcard added", "success")
        return back("flashcards")

    if action == "update_flash":
        fid = request.form.get("item_id")
        for f in data.get("flashcards") or []:
            if f.get("id") == fid:
                for k in ("front", "back", "class_id"):
                    if k in request.form:
                        f[k] = (request.form.get(k) or "").strip()
                break
        flash("Flashcard updated", "success")
        return back("flashcards")

    if action == "delete_flash":
        fid = request.form.get("item_id")
        data["flashcards"] = [f for f in (data.get("flashcards") or []) if f.get("id") != fid]
        flash("Flashcard deleted", "success")
        return back("flashcards")

    if action == "review_flash":
        # SM-2 lite: Again / Hard / Good / Easy
        fid = request.form.get("item_id")
        result = (request.form.get("result") or "good").strip().lower()
        from datetime import timedelta
        today = _sp_today()
        for f in data.get("flashcards") or []:
            if f.get("id") != fid:
                continue
            ease = float(f.get("ease") or 2.5)
            interval = int(f.get("interval") or 0)
            reps = int(f.get("reps") or 0)
            if result == "again":
                reps = 0
                interval = 0
                ease = max(1.3, ease - 0.2)
                next_d = today
            elif result == "hard":
                reps += 1
                interval = 1 if interval < 1 else max(1, int(interval * 1.2))
                ease = max(1.3, ease - 0.15)
                next_d = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=interval)).strftime("%Y-%m-%d")
            elif result == "easy":
                reps += 1
                ease = min(3.0, ease + 0.15)
                if interval < 1:
                    interval = 4
                else:
                    interval = int(interval * ease) + 1
                next_d = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=interval)).strftime("%Y-%m-%d")
            else:  # good
                reps += 1
                if interval < 1:
                    interval = 1
                elif interval == 1:
                    interval = 3
                else:
                    interval = int(interval * ease)
                next_d = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=max(1, interval))).strftime("%Y-%m-%d")
            f["ease"] = round(ease, 2)
            f["interval"] = interval
            f["reps"] = reps
            f["next_review"] = next_d
            f["last_result"] = result
            f["last_reviewed"] = datetime.now().isoformat()
            break
        save_student_productivity(username, data)
        return redirect(url_for("student_productivity", page="review"))

    if action == "log_focus_session":
        mins = request.form.get("minutes") or "25"
        try:
            mins_i = max(1, min(180, int(float(mins))))
        except Exception:
            mins_i = 25
        data.setdefault("sessions", []).insert(0, {
            "id": _sp_id(),
            "title": (request.form.get("title") or "Focus session").strip()[:200],
            "minutes": str(mins_i),
            "class_id": (request.form.get("class_id") or "").strip(),
            "date": _sp_today(),
            "notes": "Pomodoro / Focus timer",
            "created_at": datetime.now().isoformat(),
        })
        flash(f"Focus session logged ({mins_i} min)", "success")
        return back("focus")

    # ---- Attendance ----
    if action == "add_attendance":
        cid = (request.form.get("class_id") or "").strip()
        if cid:
            data.setdefault("attendance", []).insert(0, {
                "id": _sp_id(),
                "class_id": cid,
                "date": (request.form.get("date") or _sp_today()).strip()[:10],
                "status": (request.form.get("status") or "Present").strip(),
                "note": (request.form.get("note") or "").strip()[:300],
                "created_at": datetime.now().isoformat(),
            })
            flash("Attendance logged", "success")
        return back("attendance")

    if action == "delete_attendance":
        aid = request.form.get("item_id")
        data["attendance"] = [a for a in (data.get("attendance") or []) if a.get("id") != aid]
        flash("Attendance deleted", "success")
        return back("attendance")

    # ---- Goals ----
    if action == "add_goal":
        title = (request.form.get("title") or "").strip()
        if title:
            data.setdefault("goals", []).insert(0, {
                "id": _sp_id(),
                "title": title[:300],
                "target_date": (request.form.get("target_date") or "").strip()[:10],
                "progress": (request.form.get("progress") or "0").strip()[:10],
                "status": (request.form.get("status") or "Open").strip(),
                "notes": (request.form.get("notes") or "").strip()[:2000],
                "created_at": datetime.now().isoformat(),
            })
            flash("Goal added", "success")
        return back("goals")

    if action == "update_goal":
        gid = request.form.get("item_id")
        for g in data.get("goals") or []:
            if g.get("id") == gid:
                for k in ("title", "target_date", "progress", "status", "notes"):
                    if k in request.form:
                        g[k] = (request.form.get(k) or "").strip()
                break
        flash("Goal updated", "success")
        return back("goals")

    if action == "delete_goal":
        gid = request.form.get("item_id")
        data["goals"] = [g for g in (data.get("goals") or []) if g.get("id") != gid]
        flash("Goal deleted", "success")
        return back("goals")

    # ---- AI ----
    if action == "sp_ai_generate":
        prompt = (request.form.get("prompt") or "").strip()
        kind = (request.form.get("kind") or "general").strip()
        key, _prov, _model, _src = resolve_ai_api_key((data.get("settings") or {}).get("openai_user_key") or "")
        if not prompt:
            flash("Enter some text first", "warning")
            return back("ai")
        result = ""
        system_map = {
            "summarize": "You help students. Summarize the notes clearly with bullet points and key terms.",
            "quiz": "You help students. Generate 5-8 quiz questions with short answers from the material.",
            "explain": "You help students. Explain the concept in simple language with an example.",
            "plan": "You help students. Build a realistic weekly revision plan from the input.",
            "general": "You are a friendly study coach for students. Be concise and practical.",
        }
        system = system_map.get(kind, system_map["general"])
        if key:
            try:
                import urllib.request
                body = json.dumps({
                    "model": os.environ.get("OPENAI_MODEL") or "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt[:6000]},
                    ],
                    "max_tokens": 900,
                }).encode("utf-8")
                req = urllib.request.Request(
                    "https://api.openai.com/v1/chat/completions",
                    data=body,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=45) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                result = payload["choices"][0]["message"]["content"]
            except Exception as e:
                result = (
                    f"(AI error: {e})\n\nDemo fallback:\n"
                    "• Review the main headings in your notes\n"
                    "• Write 3 questions you still cannot answer\n"
                    "• Schedule a 45-minute revision block tomorrow"
                )
        else:
            result = (
                "Demo mode (no API key).\n\n"
                f"Mode: {kind}\n"
                "• Break the topic into 3 smaller chunks\n"
                "• Active recall: close notes and write what you remember\n"
                "• Teach the idea out loud in 2 minutes\n"
                "• Sleep well — memory consolidates overnight\n\n"
                "Add your OpenAI API key in Settings for real AI output."
            )
        data.setdefault("ai_log", []).insert(0, {
            "id": _sp_id(),
            "kind": kind,
            "prompt": prompt[:500],
            "result": result[:8000],
            "created_at": datetime.now().isoformat(),
        })
        data["ai_log"] = data["ai_log"][:20]
        flash("AI response ready", "success")
        return back("ai")

    if action == "save_sp_openai_key":
        key = (request.form.get("openai_user_key") or "").strip()
        data.setdefault("settings", {})["openai_user_key"] = key
        flash("API key saved" if key else "API key cleared", "success")
        return back("settings")

    # ---- Settings ----
    if action == "save_sp_settings":
        st = data.setdefault("settings", {})
        st["semester"] = (request.form.get("semester") or "").strip()[:80]
        st["target_gpa"] = (request.form.get("target_gpa") or "").strip()[:10]
        st["timezone"] = (request.form.get("timezone") or "Asia/Dhaka").strip()
        try:
            st["week_starts_on"] = int(request.form.get("week_starts_on") or 1)
        except Exception:
            st["week_starts_on"] = 1
        flash("Settings saved", "success")
        return back("settings")

    if action == "export_sp":
        payload = json.dumps(data, indent=2, ensure_ascii=False)
        from flask import Response
        return Response(
            payload,
            mimetype="application/json",
            headers={"Content-Disposition": f"attachment; filename=student-productivity-{username}.json"},
        )

    if action == "import_sp":
        f = request.files.get("file")
        if f and f.filename:
            try:
                raw = json.loads(f.read().decode("utf-8"))
                if isinstance(raw, dict):
                    for key in ("classes", "assignments", "exams", "notes", "study_plan", "resources", "sessions", "flashcards", "attendance", "goals", "ai_log"):
                        if isinstance(raw.get(key), list):
                            existing = {x.get("id") for x in (data.get(key) or []) if x.get("id")}
                            for item in raw[key]:
                                if item.get("id") and item["id"] not in existing:
                                    data.setdefault(key, []).append(item)
                    if isinstance(raw.get("settings"), dict):
                        data.setdefault("settings", {}).update(raw["settings"])
                    flash("Import merged successfully", "success")
                else:
                    flash("Invalid JSON", "danger")
            except Exception as e:
                flash(f"Import failed: {e}", "danger")
        return back("settings")

    flash("Unknown action", "warning")
    return back()




def ensure_admin():
    """Only create bootstrap admin if NO admin role exists at all.
    Never recreate username 'admin' when another admin (e.g. farhad) already exists.
    """
    if any_admin_exists():
        return
    admin = {
        "username": "admin",
        "email": "admin@portfolio.local",
        "full_name": "System Admin",
        "password": generate_password_hash("admin123"),
        "role": "admin",
        "plan": "lifetime",
        "plan_name": "Lifetime Free",
        "created_at": datetime.now().isoformat(),
        "referral_code": "ADMIN001",
        "referred_by": None,
        "portfolio_published": False,
        "portfolio_slug": "admin",
    }
    save_user(admin)
    print("Bootstrap admin created (no admin existed). Change password after login.")



# ==================== DIGITAL PRODUCT SELLER OS ====================
DPS_MODULE_ID = "digital-product-seller"

DEFAULT_DIGITAL_PRODUCT_SELLER = {
    "products": [],
    "orders": [],
    "customers": [],
    "coupons": [],
    "bundles": [],
    "campaigns": [],
    "launches": [],
    "affiliates": [],
    "reviews": [],
    "deliveries": [],
    "expenses": [],
    "messages": [],
    "ai_log": [],
    "settings": {
        "store_name": "",
        "store_slug": "",
        "store_tagline": "",
        "store_banner": "",
        "currency": "USD",
        "timezone": "Asia/Dhaka",
        "tax_rate": "0",
        "support_email": "",
        "openai_user_key": "",
        "default_view": "home",
        "checklist": {},
        "payment_note": "Digital delivery is instant after checkout.",
        "store_logo": "",
        "about_text": "",
        "footer_text": "",
        "hero_slides": [],
    },
}


def dps_path(username):
    d = MODULES_DIR / DPS_MODULE_ID
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{username}.json"



def _dps_store_customers_path(username):
    p = DATA_DIR / "modules" / "digital-product-seller" / f"{username}_store_customers.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

def load_dps_store_customers(username):
    path = _dps_store_customers_path(username)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []

def save_dps_store_customers(username, items):
    path = _dps_store_customers_path(username)
    path.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")

def _dps_customer_session_key(slug):
    return f"dps_customer_{slug}"

def get_dps_store_customer(slug):
    key = _dps_customer_session_key(slug)
    return session.get(key)


def load_digital_product_seller(username):
    path = dps_path(username)
    base = json.loads(json.dumps(DEFAULT_DIGITAL_PRODUCT_SELLER))
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for k, v in base.items():
                    if k not in raw:
                        raw[k] = v
                    elif k == "settings" and isinstance(v, dict):
                        merged = dict(v)
                        merged.update(raw.get("settings") or {})
                        raw["settings"] = merged
                for key in ("products", "orders", "customers", "coupons", "bundles", "campaigns",
                            "launches", "affiliates", "reviews", "deliveries",
                            "expenses", "messages", "ai_log"):
                    if not isinstance(raw.get(key), list):
                        raw[key] = []
                return raw
        except Exception:
            pass
    return base


def save_digital_product_seller(username, data):
    data["updated_at"] = datetime.now().isoformat()
    path = dps_path(username)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _dps_id():
    return uuid.uuid4().hex[:12]


def _dps_today():
    return datetime.now().strftime("%Y-%m-%d")


def _dps_guard():
    user = get_user(session.get("user") or "")
    if not user or not user_has_module(user, DPS_MODULE_ID):
        return None
    return user


def dps_counts(data):
    products = data.get("products") or []
    orders = data.get("orders") or []
    customers = data.get("customers") or []
    def _is_active_product(p):
        st = (p.get("status") or "Active").strip().lower()
        if st in ("archived", "inactive", "draft", "disabled", "hidden", "deleted"):
            return False
        return True  # Active, Live, empty, or any other = active
    active_products = sum(1 for p in products if _is_active_product(p))
    paid_orders = [o for o in orders if (o.get("status") or "").lower() in ("paid", "completed", "delivered")]
    revenue = 0.0
    for o in paid_orders:
        try:
            revenue += float(o.get("amount") or 0)
        except Exception:
            pass
    pending = sum(1 for o in orders if (o.get("status") or "").lower() in ("pending", "processing"))
    refunded = sum(1 for o in orders if (o.get("status") or "").lower() == "refunded")
    coupons_active = sum(1 for c in (data.get("coupons") or []) if (c.get("status") or "active").lower() == "active")
    launches_live = sum(1 for L in (data.get("launches") or []) if (L.get("status") or "").lower() in ("live", "active", "running"))
    affiliates = len(data.get("affiliates") or [])
    return {
        "products": len(products),
        "active_products": active_products,
        "orders": len(orders),
        "paid_orders": len(paid_orders),
        "pending_orders": pending,
        "refunded": refunded,
        "customers": len(customers),
        "revenue": round(revenue, 2),
        "coupons": coupons_active,
        "launches": launches_live,
        "affiliates": affiliates,
        "reviews": len(data.get("reviews") or []),
        "bundles": len(data.get("bundles") or []),
        "expenses": len(data.get("expenses") or []),
        "messages": len(data.get("messages") or []),
    }


def _dps_product_name(data, pid):
    for p in data.get("products") or []:
        if p.get("id") == pid:
            return p.get("name") or "Product"
    return ""


def _dps_customer_name(data, cid):
    for c in data.get("customers") or []:
        if c.get("id") == cid:
            return c.get("name") or c.get("email") or "Customer"
    return ""


def _dps_search(data, q):
    q = (q or "").strip().lower()
    hits = []
    if not q:
        return hits
    for p in data.get("products") or []:
        blob = " ".join(str(p.get(k) or "") for k in ("name", "sku", "category", "description", "tags")).lower()
        if q in blob:
            hits.append({"kind": "Product", "title": p.get("name") or "Product", "page": "products", "id": p.get("id")})
    for o in data.get("orders") or []:
        blob = " ".join(str(o.get(k) or "") for k in ("order_number", "customer_name", "customer_email", "product_name", "status", "notes")).lower()
        if q in blob:
            hits.append({"kind": "Order", "title": o.get("order_number") or o.get("product_name") or "Order", "page": "orders", "id": o.get("id")})
    for c in data.get("customers") or []:
        blob = " ".join(str(c.get(k) or "") for k in ("name", "email", "notes", "tags")).lower()
        if q in blob:
            hits.append({"kind": "Customer", "title": c.get("name") or c.get("email") or "Customer", "page": "customers", "id": c.get("id")})
    for c in data.get("coupons") or []:
        blob = " ".join(str(c.get(k) or "") for k in ("code", "notes")).lower()
        if q in blob:
            hits.append({"kind": "Coupon", "title": c.get("code") or "Coupon", "page": "coupons", "id": c.get("id")})
    for L in data.get("launches") or []:
        blob = " ".join(str(L.get(k) or "") for k in ("title", "notes", "status")).lower()
        if q in blob:
            hits.append({"kind": "Launch", "title": L.get("title") or "Launch", "page": "launches", "id": L.get("id")})
    for a in data.get("affiliates") or []:
        blob = " ".join(str(a.get(k) or "") for k in ("name", "email", "code")).lower()
        if q in blob:
            hits.append({"kind": "Affiliate", "title": a.get("name") or a.get("code") or "Affiliate", "page": "affiliates", "id": a.get("id")})
    return hits[:40]


@app.route("/os/digital-product-seller")
@app.route("/os/digital-product-seller/<page>")
@login_required
def digital_product_seller(page="home"):
    user = _dps_guard()
    if not user:
        flash("Digital Product Seller is not unlocked on your account.", "warning")
        return redirect(url_for("subscription_page"))
    site = load_site_settings()
    modules = {m["id"]: m for m in get_modules(site)}
    mod = modules.get(DPS_MODULE_ID) or {
        "id": DPS_MODULE_ID,
        "name": "Digital Product Seller",
        "icon": "🛒",
        "desc": "Products, sales, customers & launches",
    }
    data = load_digital_product_seller(session["user"])
    page = (page or "home").strip().lower().replace(" ", "-")
    allowed = {
        "home", "start-here", "products", "orders", "customers", "coupons",
        "bundles", "launches", "affiliates", "reviews", "deliveries",
        "expenses", "analytics", "messages", "ai", "settings", "search", "promote",
    }
    if page not in allowed:
        page = "home"
    counts = dps_counts(data)
    # enrich display fields
    for o in data.get("orders") or []:
        if not o.get("product_name") and o.get("product_id"):
            o["product_name"] = _dps_product_name(data, o.get("product_id"))
        if not o.get("customer_name") and o.get("customer_id"):
            o["customer_name"] = _dps_customer_name(data, o.get("customer_id"))
    for d in data.get("deliveries") or []:
        if not d.get("product_name") and d.get("product_id"):
            d["product_name"] = _dps_product_name(data, d.get("product_id"))
        if not d.get("customer_name") and d.get("customer_id"):
            d["customer_name"] = _dps_customer_name(data, d.get("customer_id"))
    for r in data.get("reviews") or []:
        if not r.get("product_name") and r.get("product_id"):
            r["product_name"] = _dps_product_name(data, r.get("product_id"))
    for b in data.get("bundles") or []:
        names = []
        for pid in (b.get("product_ids") or []):
            n = _dps_product_name(data, pid)
            if n:
                names.append(n)
        b["_product_names"] = names
    for c in data.get("customers") or []:
        stats = _dps_customer_purchase_stats(data, c)
        c["_purchase_count"] = stats["count"]
        c["_purchased_products"] = stats["products"]
    q = (request.args.get("q") or "").strip()
    search_hits = _dps_search(data, q) if page == "search" and q else []
    openai_configured = bool(resolve_ai_api_key((data.get("settings") or {}).get("openai_user_key") or "")[0])
    return render_template(
        "digital_product_seller.html",
        user=user,
        site=site,
        site_name=(site.get("site_name") or "Portfolio SaaS"),
        mod=mod,
        data=data,
        page=page,
        counts=counts,
        search_hits=search_hits,
        q=q,
        openai_configured=openai_configured,
        today=_dps_today(),
    )


@app.route("/os/digital-product-seller/api/search")
@login_required
def digital_product_seller_search_api():
    user = _dps_guard()
    if not user:
        return jsonify({"ok": False, "hits": []}), 403
    data = load_digital_product_seller(session["user"])
    q = (request.args.get("q") or "").strip()
    hits = _dps_search(data, q)
    return jsonify({"ok": True, "hits": hits, "q": q})


@app.route("/os/digital-product-seller/action", methods=["POST"])
@login_required
def digital_product_seller_action():
    user = _dps_guard()
    if not user:
        flash("Module not unlocked.", "warning")
        return redirect(url_for("subscription_page"))
    username = session["user"]
    data = load_digital_product_seller(username)
    action = (request.form.get("action") or "").strip()
    page = (request.form.get("page") or "home").strip()
    item_id = (request.form.get("item_id") or "").strip()

    def back(p=None):
        return redirect(url_for("digital_product_seller", page=p or page or "home"))

    def find_list(key):
        lst = data.setdefault(key, [])
        if not isinstance(lst, list):
            data[key] = []
            lst = data[key]
        return lst

    def upsert(key, fields, extra=None):
        lst = find_list(key)
        obj = {k: (request.form.get(k) or "").strip() for k in fields}
        if extra:
            obj.update(extra)
        if item_id:
            for i, row in enumerate(lst):
                if row.get("id") == item_id:
                    row.update({k: v for k, v in obj.items() if v is not None})
                    lst[i] = row
                    save_digital_product_seller(username, data)
                    flash("Updated", "success")
                    return back()
        obj["id"] = _dps_id()
        obj["created_at"] = datetime.now().isoformat()
        lst.insert(0, obj)
        save_digital_product_seller(username, data)
        flash("Created", "success")
        return back()

    def delete_item(key):
        lst = find_list(key)
        data[key] = [x for x in lst if x.get("id") != item_id]
        save_digital_product_seller(username, data)
        flash("Deleted", "success")
        return back()

    # —— Products ——
    if action == "save_product":
        price = (request.form.get("price") or "0").strip()
        try:
            price = str(float(price))
        except Exception:
            price = "0"
        # Optional product image upload
        image_url = (request.form.get("image_url") or "").strip()
        f = request.files.get("image_file")
        if f and getattr(f, "filename", None):
            url = _dps_save_upload(f, username, "images")
            if url:
                image_url = url
        # Digital product FILE upload (ebook, zip, pdf, etc.) — sets delivery_url
        delivery_url = (request.form.get("delivery_url") or "").strip()
        pf = request.files.get("product_file")
        original_name = ""
        if pf and getattr(pf, "filename", None):
            try:
                up_dir = Path("static") / "uploads" / "dps" / username / "files"
                up_dir.mkdir(parents=True, exist_ok=True)
                original_name = Path(pf.filename).name
                ext = Path(pf.filename).suffix.lower() or ".bin"
                # allow common digital product types
                allowed = {".pdf", ".zip", ".rar", ".7z", ".epub", ".mobi", ".mp3", ".mp4",
                           ".mov", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".doc", ".docx",
                           ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".csv", ".fig", ".sketch",
                           ".ai", ".psd", ".json", ".html", ".css", ".js"}
                if ext not in allowed:
                    ext = ext if len(ext) <= 8 else ".bin"
                fname = _dps_id()[:12] + ext
                dest = up_dir / fname
                pf.save(str(dest))
                delivery_url = url_for("static", filename=f"uploads/dps/{username}/files/{fname}")
            except Exception as e:
                flash(f"File upload failed: {e}", "danger")
        extra = {
            "price": price,
            "status": (request.form.get("status") or "Active").strip(),
            "image_url": image_url,
            "delivery_url": delivery_url,
        }
        if original_name:
            extra["file_name"] = original_name
        return upsert("products",
            ["name", "sku", "category", "price", "status", "description", "delivery_url",
             "license_notes", "tags", "file_name"],
            extra)

    if action == "delete_product":
        return delete_item("products")

    # —— Customers ——
    if action == "save_customer":
        return upsert("customers", ["name", "email", "phone", "country", "tags", "notes", "status"])

    if action == "delete_customer":
        return delete_item("customers")

    # —— Orders ——
    if action == "save_order":
        amount = (request.form.get("amount") or "0").strip()
        try:
            amount = str(float(amount))
        except Exception:
            amount = "0"
        product_id = (request.form.get("product_id") or "").strip()
        customer_id = (request.form.get("customer_id") or "").strip()
        product_name = _dps_product_name(data, product_id) if product_id else (request.form.get("product_name") or "").strip()
        customer_name = _dps_customer_name(data, customer_id) if customer_id else (request.form.get("customer_name") or "").strip()
        customer_email = (request.form.get("customer_email") or "").strip()
        if customer_id and not customer_email:
            for c in data.get("customers") or []:
                if c.get("id") == customer_id:
                    customer_email = c.get("email") or ""
                    break
        order_number = (request.form.get("order_number") or "").strip() or ("ORD-" + _dps_id()[:6].upper())
        extra = {
            "amount": amount,
            "product_id": product_id,
            "product_name": product_name,
            "customer_id": customer_id,
            "customer_name": customer_name,
            "customer_email": customer_email,
            "order_number": order_number,
            "status": (request.form.get("status") or "Pending").strip(),
            "order_date": (request.form.get("order_date") or _dps_today()).strip(),
            "coupon_code": (request.form.get("coupon_code") or "").strip(),
            "affiliate_code": (request.form.get("affiliate_code") or "").strip(),
            "notes": (request.form.get("notes") or "").strip(),
            "payment_method": (request.form.get("payment_method") or "").strip(),
        }
        lst = find_list("orders")
        if item_id:
            for i, row in enumerate(lst):
                if row.get("id") == item_id:
                    row.update(extra)
                    lst[i] = row
                    save_digital_product_seller(username, data)
                    flash("Order updated", "success")
                    return back()
        extra["id"] = _dps_id()
        extra["created_at"] = datetime.now().isoformat()
        lst.insert(0, extra)
        # auto-link / create customer stub
        if customer_email and not customer_id:
            custs = find_list("customers")
            found = None
            for c in custs:
                if (c.get("email") or "").lower() == customer_email.lower():
                    found = c
                    break
            if not found:
                found = {
                    "id": _dps_id(),
                    "name": customer_name or customer_email.split("@")[0],
                    "email": customer_email,
                    "status": "Active",
                    "created_at": datetime.now().isoformat(),
                }
                custs.insert(0, found)
            extra["customer_id"] = found["id"]
        save_digital_product_seller(username, data)
        flash("Order created", "success")
        return back()

    if action == "delete_order":
        return delete_item("orders")

    if action == "set_order_status":
        st = (request.form.get("status") or "").strip()
        for o in find_list("orders"):
            if o.get("id") == item_id:
                o["status"] = st
                break
        save_digital_product_seller(username, data)
        flash("Status updated", "success")
        return back()

    # —— Coupons ——
    if action == "save_coupon":
        return upsert("coupons",
            ["code", "type", "value", "status", "max_uses", "used_count", "expires_on", "notes"],
            {"status": (request.form.get("status") or "Active").strip(),
             "used_count": (request.form.get("used_count") or "0").strip()})

    if action == "delete_coupon":
        return delete_item("coupons")

    # —— Bundles ——
    if action == "save_bundle":
        pids = request.form.getlist("product_ids") or []
        if not pids:
            raw = (request.form.get("product_ids") or "").strip()
            pids = [x.strip() for x in raw.split(",") if x.strip()]
        price = (request.form.get("price") or "0").strip()
        try:
            price = str(float(price))
        except Exception:
            price = "0"
        image_url = (request.form.get("image_url") or "").strip()
        f = request.files.get("image_file")
        if f and getattr(f, "filename", None):
            url = _dps_save_upload(f, username, "bundles")
            if url:
                image_url = url
        lst = find_list("bundles")
        obj = {
            "name": (request.form.get("name") or "").strip(),
            "price": price,
            "status": (request.form.get("status") or "Active").strip(),
            "description": (request.form.get("description") or "").strip(),
            "product_ids": pids,
            "image_url": image_url,
        }
        if item_id:
            for i, row in enumerate(lst):
                if row.get("id") == item_id:
                    row.update(obj)
                    lst[i] = row
                    save_digital_product_seller(username, data)
                    flash("Bundle updated", "success")
                    return back("bundles")
        obj["id"] = _dps_id()
        obj["created_at"] = datetime.now().isoformat()
        lst.insert(0, obj)
        save_digital_product_seller(username, data)
        flash("Bundle created", "success")
        return back("bundles")

    if action == "delete_bundle":
        return delete_item("bundles")

    # —— Launches ——
    if action == "save_launch":
        return upsert("launches",
            ["title", "product_id", "status", "starts_on", "ends_on", "goal_sales", "goal_revenue", "notes"])

    if action == "delete_launch":
        return delete_item("launches")

    # —— Affiliates ——
    if action == "save_affiliate":
        return upsert("affiliates",
            ["name", "email", "code", "commission_pct", "status", "notes", "payout_info"])

    if action == "delete_affiliate":
        return delete_item("affiliates")

    # —— Reviews ——
    if action == "save_review":
        return upsert("reviews",
            ["product_id", "customer_name", "rating", "title", "body", "status", "review_date"])

    if action == "delete_review":
        return delete_item("reviews")

    # —— Deliveries ——
    if action == "save_delivery":
        return upsert("deliveries",
            ["order_id", "product_id", "customer_id", "customer_email", "delivery_url",
             "license_key", "status", "delivered_on", "notes"])

    if action == "delete_delivery":
        return delete_item("deliveries")

    # —— Expenses ——
    if action == "save_expense":
        amount = (request.form.get("amount") or "0").strip()
        try:
            amount = str(float(amount))
        except Exception:
            amount = "0"
        return upsert("expenses",
            ["title", "category", "amount", "expense_date", "notes"],
            {"amount": amount})

    if action == "delete_expense":
        return delete_item("expenses")

    # —— Messages ——

    if action == "promote_save":
        channel = (request.form.get("channel") or "email").strip().lower()
        subject = (request.form.get("subject") or "Message from our store").strip()
        body = (request.form.get("body") or "").strip()
        if not body:
            flash("Message body is required.", "danger")
            return back("promote")
        attach_url = ""
        attach_name = ""
        f = request.files.get("attachment")
        if f and getattr(f, "filename", None):
            try:
                up_dir = Path("static") / "uploads" / "dps" / username / "campaigns"
                up_dir.mkdir(parents=True, exist_ok=True)
                ext = Path(f.filename).suffix.lower() or ".bin"
                fname = _dps_id()[:12] + ext
                f.save(str(up_dir / fname))
                attach_url = url_for("static", filename=f"uploads/dps/{username}/campaigns/{fname}")
                attach_name = f.filename
            except Exception:
                pass
        data.setdefault("campaigns", []).insert(0, {
            "id": _dps_id(),
            "subject": subject,
            "body": body,
            "channel": channel,
            "recipient_count": 0,
            "recipients": [],
            "attachment_url": attach_url,
            "attachment_name": attach_name,
            "status": "draft",
            "created_at": datetime.now().isoformat(),
        })
        save_digital_product_seller(username, data)
        flash("Campaign saved. Open View campaigns to send it to selected customers.", "success")
        return back("promote")

    if action == "promote_send":
        campaign_id = (request.form.get("campaign_id") or "").strip()
        selected = request.form.getlist("customer_ids") or []
        if not selected:
            selected = [x.strip() for x in (request.form.get("customer_ids_csv") or "").split(",") if x.strip()]
        if not campaign_id:
            flash("Select a campaign first (View campaigns).", "danger")
            return back("promote")
        if not selected:
            flash("Select at least one customer to send.", "danger")
            return back("promote")
        camp = None
        for c in data.get("campaigns") or []:
            if c.get("id") == campaign_id:
                camp = c
                break
        if not camp:
            flash("Campaign not found.", "danger")
            return back("promote")
        channel = (camp.get("channel") or "email").strip().lower()
        subject = camp.get("subject") or "Message from our store"
        body = camp.get("body") or ""
        attach_url = camp.get("attachment_url") or ""
        attach_name = camp.get("attachment_name") or ""
        customers = data.get("customers") or []
        recipients = []
        sent = 0
        for c in customers:
            if c.get("id") not in selected and (c.get("email") or "") not in selected:
                continue
            email = (c.get("email") or "").strip()
            phone = (c.get("phone") or "").strip()
            name = c.get("name") or email or "Customer"
            recipients.append({"id": c.get("id"), "name": name, "email": email, "phone": phone})
            data.setdefault("messages", []).insert(0, {
                "id": _dps_id(),
                "customer_id": c.get("id"),
                "customer_email": email,
                "customer_name": name,
                "subject": subject,
                "body": body + (f"\n\n[Attachment: {attach_name}]" if attach_name else ""),
                "status": "sent",
                "channel": channel,
                "source": "promote",
                "seller_reply": "",
                "attachment_url": attach_url,
                "created_at": datetime.now().isoformat(),
            })
            try:
                for uf in USERS_DIR.glob("*.json"):
                    try:
                        uu = json.loads(uf.read_text())
                    except Exception:
                        continue
                    if email and (uu.get("email") or "").strip().lower() == email.lower():
                        add_notification(uu.get("username"), subject, body[:500], "info", from_user=username)
                        break
            except Exception:
                pass
            sent += 1
        camp["recipient_count"] = int(camp.get("recipient_count") or 0) + sent
        camp["status"] = "sent"
        camp["last_sent_at"] = datetime.now().isoformat()
        if recipients:
            camp["recipients"] = (camp.get("recipients") or [])[:20] + recipients[:30]
        save_digital_product_seller(username, data)
        flash(f"Campaign sent to {sent} customer(s) via {channel}.", "success")
        return back("promote")


    if action == "delete_campaign":
        cid = (request.form.get("item_id") or "").strip()
        data["campaigns"] = [c for c in (data.get("campaigns") or []) if c.get("id") != cid]
        save_digital_product_seller(username, data)
        flash("Campaign deleted", "success")
        return back("promote")


    if action == "save_message":
        # Support seller_reply for storefront threads
        extra = {}
        reply = (request.form.get("seller_reply") or "").strip()
        if reply:
            extra["seller_reply"] = reply
            extra["status"] = (request.form.get("status") or "replied").strip() or "replied"
        return upsert("messages",
            ["customer_id", "customer_email", "customer_name", "subject", "body", "status", "channel", "seller_reply"],
            extra if extra else None)

    if action == "delete_message":
        return delete_item("messages")

    # —— Checklist (Start Here) ——
    if action == "toggle_checklist":
        st = data.setdefault("settings", {})
        cl = st.setdefault("checklist", {})
        if not isinstance(cl, dict):
            cl = {}
            st["checklist"] = cl
        key = (request.form.get("key") or "").strip()
        if key:
            # Explicit checked value from form if sent, else flip
            if "checked" in request.form:
                cl[key] = (request.form.get("checked") or "") in ("1", "true", "on", "yes")
            else:
                cl[key] = not bool(cl.get(key))
        save_digital_product_seller(username, data)
        return back("start-here")

    # —— Settings ——

    if action == "upload_slide":
        st = data.setdefault("settings", {})
        slides = list(st.get("hero_slides") or [])
        title = (request.form.get("new_slide_title") or st.get("store_name") or "Welcome").strip()
        subtitle = (request.form.get("new_slide_subtitle") or st.get("store_tagline") or "").strip()
        files = request.files.getlist("slide_images") or []
        if not files:
            f = request.files.get("slide_image")
            if f:
                files = [f]
        added = 0
        for f in files:
            if not f or not getattr(f, "filename", None):
                continue
            url = _dps_save_upload(f, username, "slides")
            if url:
                slides.append({
                    "id": _dps_id()[:10],
                    "title": title,
                    "subtitle": subtitle,
                    "image": url,
                    "cta_text": "Shop now",
                    "cta_link": "#products",
                    "eyebrow": "Featured",
                })
                added += 1
        st["hero_slides"] = slides
        save_digital_product_seller(username, data)
        flash(f"{added} slide image(s) uploaded" if added else "No image selected", "success" if added else "warning")
        return back("settings")

    if action == "delete_slide_ajax":
        st = data.setdefault("settings", {})
        sid = (request.form.get("slide_id") or "").strip()
        slides = list(st.get("hero_slides") or [])
        st["hero_slides"] = [s for i, s in enumerate(slides) if str(s.get("id") or i) != sid]
        save_digital_product_seller(username, data)
        flash("Slide removed", "success")
        return back("settings")

    if action == "upload_logo":
        st = data.setdefault("settings", {})
        f = request.files.get("store_logo_file")
        url = _dps_save_upload(f, username, "logo") if f else ""
        if url:
            st["store_logo"] = url
            save_digital_product_seller(username, data)
            flash("Logo uploaded", "success")
        else:
            flash("No logo file selected", "warning")
        return back("settings")

    if action == "save_settings":
        st = data.setdefault("settings", {})
        for k in ("store_name", "store_slug", "store_tagline", "store_banner", "store_logo", "about_text", "footer_text", "currency", "timezone", "tax_rate", "support_email", "default_view", "payment_note"):
            if k in request.form:
                st[k] = (request.form.get(k) or "").strip()
        if "store_slug" in st:
            st["store_slug"] = _dps_slugify(st.get("store_slug") or "")
        # Logo file upload
        logo_file = request.files.get("store_logo_file")
        if logo_file and getattr(logo_file, "filename", None):
            url = _dps_save_upload(logo_file, username, "logo")
            if url:
                st["store_logo"] = url
        # Hero slides from gallery (image URLs list) + optional titles
        # Keep existing slides not marked for delete; add new uploads
        existing = list(st.get("hero_slides") or [])
        delete_ids = set(request.form.getlist("delete_slide") or [])
        kept = []
        for idx, s in enumerate(existing):
            sid = str(s.get("id") or idx)
            if sid in delete_ids:
                continue
            kept.append(s)
        # New uploaded slide images
        for f in request.files.getlist("slide_images") or []:
            if not f or not getattr(f, "filename", None):
                continue
            url = _dps_save_upload(f, username, "slides")
            if url:
                kept.append({
                    "id": _dps_id()[:10],
                    "title": (request.form.get("new_slide_title") or st.get("store_name") or "Welcome").strip(),
                    "subtitle": (request.form.get("new_slide_subtitle") or st.get("store_tagline") or "").strip(),
                    "image": url,
                    "cta_text": "Shop now",
                    "cta_link": "#products",
                    "eyebrow": "Featured",
                })
        # Also accept single slide text fields if provided (legacy)
        for i in range(1, 5):
            title = (request.form.get(f"slide{i}_title") or "").strip()
            subtitle = (request.form.get(f"slide{i}_subtitle") or "").strip()
            image = (request.form.get(f"slide{i}_image") or "").strip()
            if title or subtitle or image:
                # update matching kept slide by index if exists
                if i - 1 < len(kept):
                    if title:
                        kept[i - 1]["title"] = title
                    if subtitle:
                        kept[i - 1]["subtitle"] = subtitle
                    if image:
                        kept[i - 1]["image"] = image
                elif image or title:
                    kept.append({
                        "id": _dps_id()[:10],
                        "title": title or (st.get("store_name") or "Welcome"),
                        "subtitle": subtitle,
                        "image": image,
                        "cta_text": "Shop now",
                        "cta_link": "#products",
                        "eyebrow": "",
                    })
        st["hero_slides"] = kept
        save_digital_product_seller(username, data)
        flash("Settings saved", "success")
        return back("settings")

    if action == "save_openai_key":
        st = data.setdefault("settings", {})
        key = (request.form.get("openai_user_key") or "").strip()
        st["openai_user_key"] = key
        save_digital_product_seller(username, data)
        flash("API key saved" if key else "API key cleared", "success")
        return back("settings")

    # —— AI assist (placeholder until key; still logs prompt) ——
    if action == "ai_generate":
        prompt = (request.form.get("prompt") or "").strip()
        kind = (request.form.get("kind") or "copy").strip()
        key = ((data.get("settings") or {}).get("openai_user_key") or os.environ.get("OPENAI_API_KEY") or "").strip()
        output = ""
        if not key:
            output = "Coming Soon / No API key — add your OpenAI API key in Settings to generate live copy. Your prompt was saved."
        else:
            # Attempt real call if openai package available; else friendly message
            try:
                import urllib.request
                req_body = json.dumps({
                    "model": os.environ.get("OPENAI_MODEL") or "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": "You are a digital product marketing assistant. Write clear, conversion-focused copy."},
                        {"role": "user", "content": prompt or "Write a short product description."},
                    ],
                    "temperature": 0.7,
                }).encode("utf-8")
                req = urllib.request.Request(
                    "https://api.openai.com/v1/chat/completions",
                    data=req_body,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": "Bearer " + key,
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=45) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                    output = payload["choices"][0]["message"]["content"]
            except Exception as e:
                output = f"AI request failed: {e}. Check your API key and try again."
        data.setdefault("ai_log", []).insert(0, {
            "id": _dps_id(),
            "kind": kind,
            "prompt": prompt[:4000],
            "output": (output or "")[:8000],
            "created_at": datetime.now().isoformat(),
        })
        save_digital_product_seller(username, data)
        flash("AI response ready", "success")
        return back("ai")

    # —— Export / Import ——
    if action == "export_json":
        from flask import Response
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        return Response(
            payload,
            mimetype="application/json",
            headers={"Content-Disposition": f"attachment; filename=digital-product-seller-{username}.json"},
        )

    if action == "import_json":
        f = request.files.get("file")
        if not f:
            flash("No file", "danger")
            return back("settings")
        try:
            incoming = json.loads(f.read().decode("utf-8"))
            if not isinstance(incoming, dict):
                raise ValueError("Invalid JSON")
            for k, v in incoming.items():
                if k in DEFAULT_DIGITAL_PRODUCT_SELLER:
                    if k == "settings" and isinstance(v, dict):
                        st = data.setdefault("settings", {})
                        st.update(v)
                    elif isinstance(v, list):
                        # merge by id
                        existing = {x.get("id"): x for x in (data.get(k) or []) if isinstance(x, dict)}
                        for row in v:
                            if isinstance(row, dict) and row.get("id"):
                                existing[row["id"]] = row
                            elif isinstance(row, dict):
                                row = dict(row)
                                row["id"] = row.get("id") or _dps_id()
                                existing[row["id"]] = row
                        data[k] = list(existing.values())
            save_digital_product_seller(username, data)
            flash("Import merged successfully", "success")
        except Exception as e:
            flash(f"Import failed: {e}", "danger")
        return back("settings")

    flash("Unknown action", "warning")
    return back()




# —— Digital Product Seller: public storefront helpers ——

def _dps_save_upload(file_storage, username, sub="slides"):
    """Save uploaded image under static/uploads/dps/<user>/<sub>/ and return public URL."""
    if not file_storage or not getattr(file_storage, "filename", None):
        return ""
    try:
        up_dir = Path("static") / "uploads" / "dps" / username / sub
        up_dir.mkdir(parents=True, exist_ok=True)
        ext = Path(file_storage.filename).suffix.lower() or ".jpg"
        if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
            ext = ".jpg"
        fname = _dps_id()[:12] + ext
        dest = up_dir / fname
        file_storage.save(str(dest))
        return url_for("static", filename=f"uploads/dps/{username}/{sub}/{fname}")
    except Exception:
        return ""


def _dps_customer_purchase_stats(data, customer):
    """Return {count, products[]} for a customer from paid orders."""
    email = (customer.get("email") or "").strip().lower()
    cid = customer.get("id") or ""
    names = []
    seen = set()
    for o in data.get("orders") or []:
        st = (o.get("status") or "").lower()
        if st and st not in ("paid", "completed", "delivered", "complete"):
            # still count if amount present and not cancelled/refunded
            if st in ("cancelled", "canceled", "refunded", "failed"):
                continue
        match = False
        if cid and o.get("customer_id") == cid:
            match = True
        if email and (o.get("customer_email") or "").strip().lower() == email:
            match = True
        if not match:
            continue
        pname = o.get("product_name") or _dps_product_name(data, o.get("product_id")) or "Product"
        if o.get("bundle_name"):
            pname = o.get("bundle_name") + " (bundle)"
        key = pname.lower()
        if key not in seen:
            seen.add(key)
            names.append(pname)
    return {"count": len(names), "products": names}


def _dps_slugify(text):
    import re
    s = (text or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:48] or ""



def _dps_storefront_ctx(username, data, **extra):
    st = data.get("settings") or {}
    store_slug = _dps_slugify(st.get("store_slug") or username)
    store_customer = get_dps_store_customer(store_slug)
    viewer = None
    try:
        lu = session.get("user")
        if lu:
            u = get_user(lu)
            if u:
                viewer = {
                    "username": u.get("username"),
                    "full_name": u.get("full_name") or u.get("username"),
                    "email": u.get("email") or "",
                    "initial": ((u.get("full_name") or u.get("username") or "?")[:1] or "?").upper(),
                }
    except Exception:
        viewer = None
    return dict(
        store_customer=store_customer,
        slug=store_slug,
        seller_username=username,
        store_name=st.get("store_name") or f"{username}'s Store",
        store_tagline=st.get("store_tagline") or "Digital products — instant delivery",
        store_banner=st.get("store_banner") or "",
        store_logo=st.get("store_logo") or "",
        about_text=st.get("about_text") or "",
        footer_text=st.get("footer_text") or "",
        hero_slides=st.get("hero_slides") or [],
        currency=st.get("currency") or "USD",
        support_email=st.get("support_email") or "",
        payment_note=st.get("payment_note") or "Instant digital delivery after checkout.",
        viewer=viewer,
        **extra,
    )

def _dps_seller_by_slug(slug):
    """Return (username, data) for a public store slug, or (None, None)."""
    slug = _dps_slugify(slug)
    if not slug:
        return None, None
    folder = MODULES_DIR / DPS_MODULE_ID
    if not folder.exists():
        return None, None
    # Prefer explicit store_slug match; fallback to username match
    for path in folder.glob("*.json"):
        username = path.stem
        try:
            data = load_digital_product_seller(username)
        except Exception:
            continue
        st = data.get("settings") or {}
        store_slug = _dps_slugify(st.get("store_slug") or "")
        if store_slug and store_slug == slug:
            return username, data
        if _dps_slugify(username) == slug:
            return username, data
    return None, None


def _dps_active_products(data):
    products = []
    for p in data.get("products") or []:
        st = (p.get("status") or "Active").strip().lower()
        if st in ("archived", "inactive", "draft", "disabled", "hidden", "deleted"):
            continue
        products.append(p)
    return products


def _dps_ensure_customer(data, name, email, phone=""):
    email = (email or "").strip().lower()
    name = (name or "").strip()
    phone = (phone or "").strip()
    customers = data.setdefault("customers", [])
    if not isinstance(customers, list):
        data["customers"] = []
        customers = data["customers"]
    for c in customers:
        if (c.get("email") or "").strip().lower() == email and email:
            if name and not c.get("name"):
                c["name"] = name
            if phone and not c.get("phone"):
                c["phone"] = phone
            return c
    cust = {
        "id": _dps_id(),
        "name": name or (email.split("@")[0] if email else "Customer"),
        "email": email,
        "phone": phone,
        "status": "Active",
        "source": "storefront",
        "created_at": datetime.now().isoformat(),
    }
    customers.insert(0, cust)
    return cust


def _dps_try_send_delivery_email(to_email, store_name, product_name, download_url, order_number, amount, currency):
    """Best-effort email; never blocks checkout."""
    to_email = (to_email or "").strip()
    if not to_email:
        return False
    subject = f"Your download: {product_name}"
    body = (
        f"Thank you for your purchase from {store_name or 'our store'}!\n\n"
        f"Order: {order_number}\n"
        f"Product: {product_name}\n"
        f"Amount: {amount} {currency}\n\n"
        f"Download: {download_url or '(see success page)'}\n\n"
        f"Keep this email as your receipt.\n"
    )
    # 1) SMTP from env
    try:
        import smtplib
        from email.mime.text import MIMEText
        host = os.environ.get("SMTP_HOST") or ""
        port = int(os.environ.get("SMTP_PORT") or "587")
        user = os.environ.get("SMTP_USER") or ""
        password = os.environ.get("SMTP_PASS") or ""
        from_addr = os.environ.get("SMTP_FROM") or user or "noreply@localhost"
        if host and user:
            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"] = from_addr
            msg["To"] = to_email
            with smtplib.SMTP(host, port, timeout=15) as s:
                s.starttls()
                s.login(user, password)
                s.sendmail(from_addr, [to_email], msg.as_string())
            return True
    except Exception:
        pass
    return False



@app.route("/store/<slug>/register", methods=["GET", "POST"])
def dps_store_register(slug):
    username, data = _dps_seller_by_slug(slug)
    if not username or not data:
        return render_template("dps_storefront.html", mode="not_found", slug=slug), 404
    st = data.get("settings") or {}
    store_slug = _dps_slugify(st.get("store_slug") or username)
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        phone = (request.form.get("phone") or "").strip()
        password = (request.form.get("password") or "").strip()
        if not name or not email or not password:
            flash("Name, email and password are required.", "danger")
            return redirect(url_for("dps_store_register", slug=store_slug))
        if len(password) < 4:
            flash("Password must be at least 4 characters.", "danger")
            return redirect(url_for("dps_store_register", slug=store_slug))
        customers = load_dps_store_customers(username)
        if any((c.get("email") or "").lower() == email for c in customers):
            flash("This email is already registered on this store.", "danger")
            return redirect(url_for("dps_store_register", slug=store_slug))
        cust = {
            "id": _dps_id(),
            "name": name,
            "email": email,
            "phone": phone,
            "password": generate_password_hash(password),
            "created_at": datetime.now().isoformat(),
        }
        customers.insert(0, cust)
        save_dps_store_customers(username, customers)
        # also ensure in seller CRM customers list
        crm = data.setdefault("customers", [])
        if not any((c.get("email") or "").lower() == email for c in crm):
            crm.insert(0, {
                "id": _dps_id(),
                "name": name,
                "email": email,
                "phone": phone,
                "source": "store_register",
                "created_at": datetime.now().isoformat(),
            })
            save_digital_product_seller(username, data)
        session[_dps_customer_session_key(store_slug)] = {
            "id": cust["id"], "name": name, "email": email, "phone": phone
        }
        flash("Account created. You are logged in to this store.", "success")
        return redirect(url_for("dps_public_store", slug=store_slug))
    return render_template(
        "dps_storefront.html",
        mode="auth_register",
        **_dps_storefront_ctx(username, data),
    )


@app.route("/store/<slug>/login", methods=["GET", "POST"])
def dps_store_login(slug):
    username, data = _dps_seller_by_slug(slug)
    if not username or not data:
        return render_template("dps_storefront.html", mode="not_found", slug=slug), 404
    st = data.get("settings") or {}
    store_slug = _dps_slugify(st.get("store_slug") or username)
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = (request.form.get("password") or "").strip()
        customers = load_dps_store_customers(username)
        matched = None
        for c in customers:
            if (c.get("email") or "").lower() == email:
                matched = c
                break
        if not matched or not check_password_hash(matched.get("password") or "", password):
            flash("Invalid email or password for this store.", "danger")
            return redirect(url_for("dps_store_login", slug=store_slug))
        session[_dps_customer_session_key(store_slug)] = {
            "id": matched.get("id"),
            "name": matched.get("name"),
            "email": matched.get("email"),
            "phone": matched.get("phone") or "",
        }
        flash("Welcome back!", "success")
        nxt = request.args.get("next") or request.form.get("next") or ""
        if nxt.startswith("/store/"):
            return redirect(nxt)
        return redirect(url_for("dps_public_store", slug=store_slug))
    return render_template(
        "dps_storefront.html",
        mode="auth_login",
        **_dps_storefront_ctx(username, data),
    )


@app.route("/store/<slug>/logout")
def dps_store_logout(slug):
    username, data = _dps_seller_by_slug(slug)
    store_slug = slug
    if data:
        st = data.get("settings") or {}
        store_slug = _dps_slugify(st.get("store_slug") or (username or slug))
    session.pop(_dps_customer_session_key(store_slug), None)
    flash("Logged out of this store.", "info")
    return redirect(url_for("dps_public_store", slug=store_slug))


@app.route("/store/<slug>")
def dps_public_store(slug):
    username, data = _dps_seller_by_slug(slug)
    if not username or not data:
        return render_template("dps_storefront.html", mode="not_found", slug=slug), 404
    st = data.get("settings") or {}
    # If a platform user is logged in, ensure they appear in this store's customers
    try:
        lu = session.get("user")
        if lu:
            u = get_user(lu)
            if u and u.get("email"):
                _dps_ensure_customer(data, u.get("full_name") or u.get("username") or "", u.get("email"), u.get("phone") or "")
                save_digital_product_seller(username, data)
    except Exception:
        pass
    products = _dps_active_products(data)
    # Active bundles
    bundles = []
    for b in data.get("bundles") or []:
        st_b = (b.get("status") or "Active").strip().lower()
        if st_b in ("archived", "inactive", "draft", "disabled", "hidden"):
            continue
        # resolve product names
        names = []
        ids = b.get("product_ids") or []
        if isinstance(ids, str):
            ids = [x.strip() for x in ids.split(",") if x.strip()]
        for pid in ids:
            for p in data.get("products") or []:
                if p.get("id") == pid:
                    names.append(p.get("name") or "Product")
                    break
        bb = dict(b)
        bb["_product_names"] = names
        bundles.append(bb)
    # Active coupons
    coupons = []
    for c in data.get("coupons") or []:
        st_c = (c.get("status") or "active").strip().lower()
        if st_c in ("archived", "inactive", "disabled", "expired", "used"):
            continue
        coupons.append(c)
    # Featured: tags contain featured/offer OR category Featured
    featured = []
    for p in products:
        tags = (p.get("tags") or "").lower()
        cat = (p.get("category") or "").lower()
        if "featured" in tags or "offer" in tags or cat in ("featured", "offer", "offers"):
            featured.append(p)
    reviews = [r for r in (data.get("reviews") or []) if (r.get("status") or "Published").lower() in ("published", "public", "approved", "")]
    return render_template(
        "dps_storefront.html",
        mode="store",
        products=products,
        product=None,
        more_products=[],
        bundles=bundles,
        coupons=coupons,
        featured=featured,
        store_reviews=reviews[:12],
        **_dps_storefront_ctx(username, data),
    )


@app.route("/store/<slug>/p/<product_id>", methods=["GET", "POST"])
def dps_public_product(slug, product_id):
    username, data = _dps_seller_by_slug(slug)
    if not username or not data:
        return render_template("dps_storefront.html", mode="not_found", slug=slug), 404
    st = data.get("settings") or {}
    store_slug = _dps_slugify(st.get("store_slug") or username)
    products = _dps_active_products(data)
    product = None
    for p in products:
        if p.get("id") == product_id:
            product = p
            break
    if not product:
        flash("Product not available.", "warning")
        return redirect(url_for("dps_public_store", slug=store_slug))

    if request.method == "POST":
        name = (request.form.get("full_name") or "").strip()
        email = (request.form.get("email") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        pay_method = (request.form.get("payment_method") or "Instant checkout").strip()
        if not name or not email:
            flash("Name and email are required.", "danger")
            return redirect(url_for("dps_public_product", slug=store_slug, product_id=product_id))

        # —— Zero-touch automation ——
        cust = _dps_ensure_customer(data, name, email, phone)
        try:
            amount = str(float(product.get("price") or 0))
        except Exception:
            amount = "0"
        order_number = "ORD-" + _dps_id()[:8].upper()
        order = {
            "id": _dps_id(),
            "order_number": order_number,
            "product_id": product.get("id"),
            "product_name": product.get("name") or "Product",
            "customer_id": cust.get("id"),
            "customer_name": name,
            "customer_email": email,
            "customer_phone": phone,
            "amount": amount,
            "status": "Paid",
            "order_date": _dps_today(),
            "payment_method": pay_method,
            "source": "storefront",
            "created_at": datetime.now().isoformat(),
            "notes": "Auto-created from public storefront checkout",
        }
        data.setdefault("orders", []).insert(0, order)
        delivery_url = (product.get("delivery_url") or "").strip()
        license_key = (product.get("license_notes") or "").strip()
        delivery = {
            "id": _dps_id(),
            "order_id": order["id"],
            "product_id": product.get("id"),
            "product_name": product.get("name") or "Product",
            "customer_id": cust.get("id"),
            "customer_name": name,
            "customer_email": email,
            "delivery_url": delivery_url,
            "license_key": license_key,
            "status": "Delivered",
            "delivered_on": _dps_today(),
            "source": "storefront",
            "created_at": datetime.now().isoformat(),
            "notes": "Auto-delivered after checkout",
        }
        data.setdefault("deliveries", []).insert(0, delivery)
        save_digital_product_seller(username, data)

        # Absolute download URL for email if relative
        dl = delivery_url
        try:
            _dps_try_send_delivery_email(
                email,
                st.get("store_name") or store_slug,
                product.get("name") or "Product",
                dl,
                order_number,
                amount,
                st.get("currency") or "USD",
            )
        except Exception:
            pass

        return redirect(url_for(
            "dps_public_success",
            slug=store_slug,
            order_id=order["id"],
        ))

    more = [p for p in products if p.get("id") != product_id][:8]
    return render_template(
        "dps_storefront.html",
        mode="checkout",
        products=products,
        product=product,
        more_products=more,
        **_dps_storefront_ctx(username, data),
    )



@app.route("/store/<slug>/download/<order_id>")
def dps_public_download(slug, order_id):
    """Force download of product file after successful order."""
    username, data = _dps_seller_by_slug(slug)
    if not username or not data:
        return "Store not found", 404
    order = None
    for o in data.get("orders") or []:
        if o.get("id") == order_id:
            order = o
            break
    if not order:
        flash("Order not found.", "danger")
        return redirect(url_for("dps_public_store", slug=slug))
    st = (order.get("status") or "").strip().lower()
    if st not in ("paid", "completed", "delivered", "success"):
        flash("This order is not paid yet.", "warning")
        return redirect(url_for("dps_public_success", slug=slug, order_id=order_id))
    delivery_url = ""
    file_name = "download"
    for d in data.get("deliveries") or []:
        if d.get("order_id") == order_id and d.get("delivery_url"):
            delivery_url = d.get("delivery_url")
            break
    if not delivery_url:
        pid = order.get("product_id")
        for p in data.get("products") or []:
            if p.get("id") == pid:
                delivery_url = p.get("delivery_url") or ""
                file_name = p.get("file_name") or p.get("name") or "download"
                break
    if not delivery_url:
        flash("No download file attached to this product.", "warning")
        return redirect(url_for("dps_public_success", slug=slug, order_id=order_id))
    # Local static file → send as attachment
    if "/static/" in delivery_url or delivery_url.startswith("/static/"):
        rel = delivery_url.split("/static/")[-1].split("?")[0]
        path = Path("static") / rel
        if path.exists() and path.is_file():
            from flask import send_file
            return send_file(str(path), as_attachment=True, download_name=file_name if "." in str(file_name) else path.name)
    return redirect(delivery_url)


@app.route("/store/<slug>/success/<order_id>")
def dps_public_success(slug, order_id):
    username, data = _dps_seller_by_slug(slug)
    if not username or not data:
        return render_template("dps_storefront.html", mode="not_found", slug=slug), 404
    st = data.get("settings") or {}
    store_slug = _dps_slugify(st.get("store_slug") or username)
    order = None
    for o in data.get("orders") or []:
        if o.get("id") == order_id:
            order = o
            break
    delivery = None
    for d in data.get("deliveries") or []:
        if d.get("order_id") == order_id:
            delivery = d
            break
    return render_template(
        "dps_storefront.html",
        mode="success",
        order=order,
        delivery=delivery,
        product=None,
        products=[],
        more_products=[],
        **_dps_storefront_ctx(username, data),
    )





@app.route("/store/<slug>/bundle/<bundle_id>", methods=["GET", "POST"])
def dps_public_bundle(slug, bundle_id):
    username, data = _dps_seller_by_slug(slug)
    if not username or not data:
        return render_template("dps_storefront.html", mode="not_found", slug=slug), 404
    st = data.get("settings") or {}
    store_slug = _dps_slugify(st.get("store_slug") or username)
    bundle = None
    for b in data.get("bundles") or []:
        if b.get("id") == bundle_id:
            st_b = (b.get("status") or "Active").strip().lower()
            if st_b not in ("archived", "inactive", "draft", "disabled", "hidden"):
                bundle = b
            break
    if not bundle:
        flash("Bundle not available.", "warning")
        return redirect(url_for("dps_public_store", slug=store_slug))
    # Build synthetic product-like object for checkout UI
    names = []
    delivery_urls = []
    for pid in (bundle.get("product_ids") or []):
        for p in data.get("products") or []:
            if p.get("id") == pid:
                names.append(p.get("name") or "Product")
                if p.get("delivery_url"):
                    delivery_urls.append(p.get("delivery_url"))
                break
    product = {
        "id": bundle.get("id"),
        "name": bundle.get("name") or "Bundle",
        "price": bundle.get("price") or "0",
        "description": bundle.get("description") or (", ".join(names) if names else "Product bundle"),
        "category": "Bundle",
        "image_url": bundle.get("image_url") or "",
        "delivery_url": delivery_urls[0] if delivery_urls else "",
        "license_notes": "Includes: " + (", ".join(names) if names else "bundle items"),
        "_is_bundle": True,
        "_bundle_product_ids": bundle.get("product_ids") or [],
    }
    if request.method == "POST":
        name = (request.form.get("full_name") or "").strip()
        email = (request.form.get("email") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        pay_method = (request.form.get("payment_method") or "Instant checkout").strip()
        if not name or not email:
            flash("Name and email are required.", "danger")
            return redirect(url_for("dps_public_bundle", slug=store_slug, bundle_id=bundle_id))
        cust = _dps_ensure_customer(data, name, email, phone)
        try:
            amount = str(float(product.get("price") or 0))
        except Exception:
            amount = "0"
        order_number = "BDL-" + _dps_id()[:8].upper()
        order = {
            "id": _dps_id(),
            "order_number": order_number,
            "product_id": "",
            "bundle_id": bundle.get("id"),
            "product_name": product["name"],
            "bundle_name": product["name"],
            "customer_id": cust.get("id"),
            "customer_name": name,
            "customer_email": email,
            "customer_phone": phone,
            "amount": amount,
            "status": "Paid",
            "order_date": _dps_today(),
            "payment_method": pay_method,
            "source": "storefront-bundle",
            "created_at": datetime.now().isoformat(),
            "notes": "Bundle checkout: " + (", ".join(names)),
        }
        data.setdefault("orders", []).insert(0, order)
        delivery = {
            "id": _dps_id(),
            "order_id": order["id"],
            "product_id": "",
            "product_name": product["name"],
            "customer_id": cust.get("id"),
            "customer_name": name,
            "customer_email": email,
            "delivery_url": product.get("delivery_url") or "",
            "license_key": product.get("license_notes") or "",
            "status": "Delivered",
            "delivered_on": _dps_today(),
            "source": "storefront-bundle",
            "created_at": datetime.now().isoformat(),
            "notes": "Auto-delivered bundle",
        }
        data.setdefault("deliveries", []).insert(0, delivery)
        save_digital_product_seller(username, data)
        try:
            _dps_try_send_delivery_email(
                email, st.get("store_name") or store_slug, product["name"],
                product.get("delivery_url") or "", order_number, amount, st.get("currency") or "USD",
            )
        except Exception:
            pass
        return redirect(url_for("dps_public_success", slug=store_slug, order_id=order["id"]))
    products = _dps_active_products(data)
    more = products[:8]
    return render_template(
        "dps_storefront.html",
        mode="checkout",
        products=products,
        product=product,
        more_products=more,
        **_dps_storefront_ctx(username, data),
    )


@app.route("/store/<slug>/review", methods=["POST"])
def dps_public_review(slug):
    username, data = _dps_seller_by_slug(slug)
    if not username or not data:
        flash("Store not found.", "danger")
        return redirect(url_for("dps_public_store", slug=slug))
    st = data.get("settings") or {}
    store_slug = _dps_slugify(st.get("store_slug") or username)
    name = (request.form.get("customer_name") or "").strip()
    email = (request.form.get("customer_email") or "").strip().lower()
    product_id = (request.form.get("product_id") or "").strip()
    rating = (request.form.get("rating") or "5").strip()
    title = (request.form.get("title") or "").strip()
    body = (request.form.get("body") or "").strip()
    if not name or not body:
        flash("Name and review text are required.", "danger")
        return redirect(url_for("dps_public_store", slug=store_slug) + "#reviews")
    # One review per product per customer (email or name)
    for existing in data.get("reviews") or []:
        same_person = False
        if email and (existing.get("customer_email") or "").strip().lower() == email:
            same_person = True
        if not email and name and (existing.get("customer_name") or "").strip().lower() == name.lower():
            same_person = True
        if not same_person:
            continue
        ex_pid = (existing.get("product_id") or "").strip()
        if ex_pid == product_id:
            flash("You have already submitted a review for this product.", "danger")
            return redirect(url_for("dps_public_store", slug=store_slug) + "#reviews")
    try:
        rating_n = max(1, min(5, int(float(rating))))
    except Exception:
        rating_n = 5
    rev = {
        "id": _dps_id(),
        "product_id": product_id,
        "product_name": _dps_product_name(data, product_id) if product_id else "",
        "customer_name": name,
        "customer_email": email,
        "rating": str(rating_n),
        "title": title or "Customer review",
        "body": body,
        "review_date": _dps_today(),
        "status": "Published",
        "source": "storefront",
        "created_at": datetime.now().isoformat(),
    }
    data.setdefault("reviews", []).insert(0, rev)
    if email:
        try:
            _dps_ensure_customer(data, name, email, "")
        except Exception:
            pass
    save_digital_product_seller(username, data)
    try:
        add_notification(username, f"New review from {name}", f"{rating_n}★ — {title or body[:120]}", "info", from_user=email or name)
    except Exception:
        pass
    flash("Thank you! Your review was submitted.", "success")
    return redirect(url_for("dps_public_store", slug=store_slug) + "#reviews")



@app.route("/store/<slug>/contact", methods=["POST"])
def dps_public_contact(slug):
    username, data = _dps_seller_by_slug(slug)
    if not username or not data:
        flash("Store not found.", "danger")
        return redirect(url_for("dps_public_store", slug=slug))
    st = data.get("settings") or {}
    store_slug = _dps_slugify(st.get("store_slug") or username)
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    subject = (request.form.get("subject") or "Store inquiry").strip()
    body = (request.form.get("body") or "").strip()
    if not name or not email or not body:
        flash("Name, email and message are required.", "danger")
        return redirect(url_for("dps_public_store", slug=store_slug) + "#contact")
    msg = {
        "id": _dps_id(),
        "customer_name": name,
        "customer_email": email,
        "subject": subject,
        "body": body,
        "status": "new",
        "channel": "storefront",
        "seller_reply": "",
        "source": "storefront",
        "created_at": datetime.now().isoformat(),
    }
    data.setdefault("messages", []).insert(0, msg)
    # ensure customer record
    try:
        _dps_ensure_customer(data, name, email, "")
    except Exception:
        pass
    save_digital_product_seller(username, data)
    try:
        add_notification(
            username,
            f"New store message from {name}",
            f"Subject: {subject}\nFrom: {email}\n\n{body[:400]}",
            "info",
            from_user=email,
        )
    except Exception:
        pass
    flash("Message sent! The seller will reply soon. Check My messages with this email.", "success")
    return redirect(url_for("dps_public_store", slug=store_slug) + "#contact")


@app.route("/store/<slug>/inbox")
def dps_public_inbox(slug):
    username, data = _dps_seller_by_slug(slug)
    if not username or not data:
        return render_template("dps_storefront.html", mode="not_found", slug=slug), 404
    email = (request.args.get("email") or "").strip().lower()
    inbox_messages = []
    if email:
        for m in data.get("messages") or []:
            if (m.get("customer_email") or "").strip().lower() == email:
                inbox_messages.append(m)
    return render_template(
        "dps_storefront.html",
        mode="inbox",
        inbox_email=email,
        inbox_messages=inbox_messages,
        products=[],
        product=None,
        more_products=[],
        bundles=[],
        coupons=[],
        featured=[],
        **_dps_storefront_ctx(username, data),
    )



# Bootstrap: load .env secrets then ensure admin
try:
    load_dotenv_into_environ()
except Exception as _e:
    print("load_dotenv warning:", _e)
try:
    ensure_admin()
except Exception as _e:
    print("ensure_admin warning:", _e)

# ==================== RUN ====================
if __name__ == "__main__":
    ensure_admin()
    print("=" * 50)
    print("  Portfolio SaaS  |  v" + get_version())
    print("  http://127.0.0.1:5000")
    print("  Login with your admin account")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=True)
