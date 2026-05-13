#!/usr/bin/env python3
"""Content production orchestrator.

Usage:
    python3 run.py --store-id ID --type poster --occasion "Mother's Day"
    python3 run.py --store-id ID --type product_image --sku MKR-16
    python3 run.py --store-id ID --type pdp --sku MKR-16 --dry-run
    python3 run.py --store-id ID --type video --sku MKR-16 --enable-video-gen
    python3 run.py --store-id ID --type poster --occasion 母亲节 --language zh
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
LUMICC_SCRIPTS = HERE.parent.parent / "lumicc" / "scripts"
sys.path.insert(0, str(LUMICC_SCRIPTS))
import notify as notify_mod
import prompts as prompts_mod
import render_html as html_mod
import image_client as ic
try:
    import picker as picker_mod  # type: ignore
    import session as session_mod  # type: ignore
except ImportError:
    picker_mod = None  # type: ignore
    session_mod = None  # type: ignore
try:
    import assets as assets_mod  # type: ignore
except ImportError:
    assets_mod = None  # type: ignore


def _data_root() -> Path:
    env = os.environ.get("LUMICC_DATA_ROOT")
    return Path(env).expanduser() if env else Path.home() / ".commerce-os"


ROOT = _data_root()  # snapshot for back-compat; recomputed in main()


def db_path() -> Path:
    return ROOT / "store.db"


# ---------- DB helpers ----------
def get_store(store_id: str | None) -> dict | None:
    if not db_path().exists():
        return None
    db = sqlite3.connect(db_path()); db.row_factory = sqlite3.Row
    try:
        if store_id:
            row = db.execute("SELECT * FROM stores WHERE id=?", (store_id,)).fetchone()
        else:
            row = db.execute("SELECT * FROM stores ORDER BY updated_at DESC LIMIT 1").fetchone()
        return dict(row) if row else None
    finally:
        db.close()


def get_product(sku: str, store_id: str | None) -> dict | None:
    if not db_path().exists():
        return None
    db = sqlite3.connect(db_path()); db.row_factory = sqlite3.Row
    try:
        q = "SELECT * FROM products WHERE sku=?"
        params: list = [sku]
        if store_id:
            q += " AND store_id=?"
            params.append(store_id)
        row = db.execute(q, params).fetchone()
        return dict(row) if row else None
    finally:
        db.close()


def ensure_generated_assets_table() -> None:
    if not db_path().exists():
        return
    db = sqlite3.connect(db_path())
    try:
        db.execute("""
        CREATE TABLE IF NOT EXISTS generated_assets (
          id TEXT PRIMARY KEY,
          run_id TEXT,
          store_id TEXT,
          sku TEXT,
          asset_type TEXT,
          category TEXT,
          prompt_text TEXT,
          model TEXT,
          size TEXT,
          local_path TEXT,
          remote_url TEXT,
          remote_url_expires_at INTEGER,
          credits REAL,
          created_at INTEGER
        )
        """)
        db.commit()
    finally:
        db.close()


def insert_asset(asset: dict) -> None:
    if not db_path().exists():
        return
    db = sqlite3.connect(db_path())
    try:
        db.execute(
            "INSERT OR REPLACE INTO generated_assets (id, run_id, store_id, sku, asset_type, "
            "category, prompt_text, model, size, local_path, remote_url, remote_url_expires_at, "
            "credits, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (asset.get("id"), asset.get("run_id"), asset.get("store_id"), asset.get("sku"),
             asset.get("asset_type"), asset.get("category"), asset.get("prompt_text"),
             asset.get("model"), asset.get("size"), asset.get("local_path"),
             asset.get("remote_url"), asset.get("remote_url_expires_at"),
             asset.get("credits"), int(time.time())),
        )
        db.commit()
    finally:
        db.close()


def append_event(store_id: str | None, content: str) -> None:
    if not db_path().exists():
        return
    db = sqlite3.connect(db_path())
    try:
        db.execute("INSERT INTO events (store_id, ts, category, content) VALUES (?,?,?,?)",
                   (store_id, int(time.time()), "task", content))
        db.commit()
    finally:
        db.close()


def append_run(run_id: str, store_id: str | None, status: str, result_path: str) -> None:
    if not db_path().exists():
        return
    db = sqlite3.connect(db_path())
    try:
        db.execute(
            "INSERT OR REPLACE INTO runs (run_id, skill, store_id, started_at, finished_at, status, result_path) "
            "VALUES (?,?,?,?,?,?,?)",
            (run_id, "lumicc-content", store_id, int(time.time()), int(time.time()), status, result_path),
        )
        db.commit()
    finally:
        db.close()


# ---------- Real generation ----------
def maybe_generate_image(item: dict, run_dir: Path, language: str, dry_run: bool,
                         api_key: str | None) -> tuple[float, list[str]]:
    """If item is an image type AND not dry-run AND API key available, call evolink.
    Returns (credits_consumed, list_of_local_image_paths). Mutates item in place.
    """
    params = item.get("image_gen_params") or {}
    if not params or dry_run or not api_key:
        return 0.0, []
    model = params.get("model") or "auto"
    size = params.get("size", "1024x1024")
    n = params.get("n", 1)
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        local_paths: list[str] = []
        total_cost = 0.0
        for _ in range(max(1, int(n))):
            result = ic.generate_image(
                item["prompt_text"], model=model, size=size,
                out_dir=run_dir,
            )
            local_paths.append(result["image_path"])
            total_cost += float(result.get("cost_estimate_usd") or 0.0)
            item["model"] = result.get("model_used") or model
        item["image_local_paths"] = local_paths
        item["credits"] = round(total_cost, 4)
        return float(total_cost), local_paths
    except Exception as e:
        item["error"] = f"image gen failed: {e}"
        return 0.0, []


def maybe_generate_video(item: dict, run_dir: Path, dry_run: bool,
                         api_key: str | None, enable: bool) -> tuple[float, list[str]]:
    if not enable or dry_run or not api_key:
        return 0.0, []
    if not item.get("video_gen_params"):
        return 0.0, []
    # Late-import to avoid pulling video deps unless explicitly used
    import video_client as vc
    params = item["video_gen_params"]
    safe_subject = item.get("subject", "video").replace("/", "-").replace(" ", "_")[:60]
    dest = run_dir / f"video-{safe_subject}.mp4"
    try:
        result = vc.generate_video(
            item["prompt_text"], dest,
            model=params["model"],
            duration_s=params.get("duration_s", 6),
            resolution=params.get("resolution", "720p"),
            aspect_ratio=params.get("aspect_ratio", "9:16"),
            api_key=api_key,
        )
        local_paths = result.get("local_paths", [])
        credits = vc.estimate_video_credits(
            params["model"],
            duration_s=params.get("duration_s", 6),
            resolution=params.get("resolution", "720p"),
        )
        item["video_local_paths"] = local_paths
        item["task_id"] = result.get("task_id")
        item["model"] = params["model"]
        item["credits"] = credits
        item["video_gen_enabled"] = True
        return float(credits), local_paths
    except Exception as e:
        item["error"] = f"video gen failed: {e}"
        return 0.0, []


# ---------- Preferences (for video opt-in) ----------
def get_pref(key: str) -> str | None:
    if not db_path().exists():
        return None
    db = sqlite3.connect(db_path())
    try:
        row = db.execute("SELECT value FROM preferences WHERE key=?", (key,)).fetchone()
        return row[0] if row else None
    finally:
        db.close()


def set_pref(key: str, value: str) -> None:
    if not db_path().exists():
        return
    db = sqlite3.connect(db_path())
    try:
        db.execute(
            "INSERT OR REPLACE INTO preferences (key, value, updated_at) VALUES (?,?,?)",
            (key, value, int(time.time())),
        )
        db.commit()
    finally:
        db.close()


# ---------- v0.4 generation via image_client.generate_image ----------
def generate_images_v04(items: list[dict], run_id: str, store_id: str | None,
                       sku: str | None, generated_dir: Path) -> tuple[list[dict], list[str], float]:
    """For each image-bearing item, call ic.generate_image and record to assets.

    Returns (generated_images_summary, warnings, total_cost_usd).
    Bubbles MissingSecretError up to caller (so it can print help + exit).
    """
    summary: list[dict] = []
    warnings: list[str] = []
    total_cost = 0.0
    generated_dir.mkdir(parents=True, exist_ok=True)
    for it in items:
        params = it.get("image_gen_params") or {}
        if not params:
            continue
        prompt = it.get("prompt_text", "")
        try:
            result = ic.generate_image(
                prompt, model=params.get("model", "auto"),
                size=params.get("size", "1024x1024"),
                out_dir=generated_dir, run_id=run_id,
            )
        except ic.MissingSecretError:
            raise
        except ic.EvolinkAPIError as e:
            warnings.append(f"image gen failed for {it.get('subject', '?')}: {e}")
            it["error"] = str(e)
            continue
        cost = float(result.get("cost_estimate_usd") or 0.0)
        total_cost += cost
        it["image_local_paths"] = [result["image_path"]]
        it["model"] = result.get("model_used")
        it["credits"] = cost  # store USD as 'credits' for legacy
        summary.append({
            "path": result["image_path"],
            "model": result.get("model_used"),
            "cost_usd": cost,
            "subject": it.get("subject"),
            "prompt": prompt,
        })
        if assets_mod is not None:
            try:
                assets_mod.record_asset(
                    kind="image", path=result["image_path"], prompt=prompt,
                    revised_prompt=result.get("revised_prompt"),
                    model=result.get("model_used"), cost_usd=cost,
                    store_id=store_id, sku=sku, run_id=run_id,
                )
            except Exception as e:
                warnings.append(f"record_asset failed: {e}")
    return summary, warnings, round(total_cost, 4)


def generate_videos_v04(items: list[dict], run_id: str, store_id: str | None,
                       sku: str | None, generated_dir: Path) -> tuple[list[dict], list[str], float]:
    summary: list[dict] = []
    warnings: list[str] = []
    total_cost = 0.0
    generated_dir.mkdir(parents=True, exist_ok=True)
    for it in items:
        vparams = it.get("video_gen_params") or {}
        if not vparams:
            continue
        prompt = it.get("prompt_text", "")
        try:
            result = ic.generate_video(
                prompt, model=vparams.get("model", ic.MODEL_SORA_2),
                duration=vparams.get("duration_s", 5),
                resolution=vparams.get("resolution", "720p"),
                out_dir=generated_dir, run_id=run_id,
            )
        except ic.MissingSecretError:
            raise
        except ic.EvolinkAPIError as e:
            warnings.append(f"video gen failed for {it.get('subject', '?')}: {e}")
            it["error"] = str(e)
            continue
        cost = float(result.get("cost_estimate_usd") or 0.0)
        total_cost += cost
        it["video_local_paths"] = [result["video_path"]]
        it["model"] = result.get("model_used")
        it["video_gen_enabled"] = True
        it["credits"] = cost
        summary.append({
            "path": result["video_path"],
            "model": result.get("model_used"),
            "cost_usd": cost,
            "subject": it.get("subject"),
            "prompt": prompt,
        })
        if assets_mod is not None:
            try:
                assets_mod.record_asset(
                    kind="video", path=result["video_path"], prompt=prompt,
                    model=result.get("model_used"), cost_usd=cost,
                    store_id=store_id, sku=sku, run_id=run_id,
                )
            except Exception as e:
                warnings.append(f"record_asset failed: {e}")
    return summary, warnings, round(total_cost, 4)


def _print_missing_secret_help() -> None:
    print(
        "\n⚠️  EVOLINK_API_KEY 未配置。\n"
        "   生成密钥表单 → 浏览器填写：\n"
        "   python3 ../lumicc/scripts/secret_form.py --generate EVOLINK_API_KEY --open\n",
        file=sys.stderr,
    )


def detect_language(args_lang: str | None, store: dict | None) -> str:
    if args_lang:
        return args_lang
    if store:
        market = (store.get("target_market") or "").lower()
        if market in ("cn", "china", "tw", "hk"):
            return "zh"
    return "en"


# ---------- Main ----------
def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--store-id", default=None)
    p.add_argument("--sku", action="append", default=[])
    p.add_argument("--type", required=False, choices=list(prompts_mod.TEMPLATES.keys()))
    p.add_argument("--pick-style", action="store_true",
                   help="Open the landing-style picker and return the session id.")
    p.add_argument("--build", action="store_true",
                   help="Build content; requires --session with a confirmed style choice.")
    p.add_argument("--session", default=None, help="Session id (shared with lumicc picker/session)")
    p.add_argument("--open", action="store_true", help="Open picker URL in a browser.")
    p.add_argument("--occasion", default=None)
    p.add_argument("--style", default=None)
    p.add_argument("--count", type=int, default=1)
    p.add_argument("--model", default=None)
    p.add_argument("--size", default="auto")
    p.add_argument("--quality", default="1K")
    p.add_argument("--angles", default=None, help="Comma-separated: hero,lifestyle,scale,feature,packaging")
    p.add_argument("--language", default=None, choices=["en", "zh"])
    p.add_argument("--platform", default="meta")
    p.add_argument("--campaign", default="welcome")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--enable-video-gen", action="store_true")
    p.add_argument("--auto-confirm", action="store_true")
    p.add_argument("--max-credits", type=float, default=20.0)
    p.add_argument("--notify-channel", default=None)
    p.add_argument("--notify-target", default="")
    p.add_argument("--quiet-stdout", action="store_true")
    p.add_argument("--run-id", default=None)
    # v0.4 flags
    p.add_argument("--generate-images", action="store_true",
                   help="Actually call evolink to generate images (otherwise prompts only).")
    p.add_argument("--video", action="store_true",
                   help="Enable video generation (requires preference + --confirm-cost).")
    p.add_argument("--enable-video", action="store_true",
                   help="Persist video_gen_enabled=true preference and exit.")
    p.add_argument("--confirm-cost", action="store_true",
                   help="Bypass interactive cost confirmation (useful with --video).")
    p.add_argument("--estimate-only", action="store_true",
                   help="Print cost estimate and exit without calling the API.")
    args = p.parse_args()

    global ROOT
    ROOT = _data_root()
    ROOT.mkdir(exist_ok=True)

    # ---- v0.4: --enable-video persists preference and exits ----
    if args.enable_video:
        set_pref("video_gen_enabled", "true")
        print("✓ 视频生成已启用。下次运行可直接加 --video --confirm-cost")
        return 0

    # ---- v0.4: --video opt-in flow ----
    if args.video and not args.enable_video:
        pref = (get_pref("video_gen_enabled") or "").lower()
        if pref != "true" and not args.confirm_cost:
            print(
                "⚠️  视频生成默认关闭。\n"
                "   成本估算：~$0.4-1.5 / 视频 (Sora 2)\n"
                "   启用一次：python3 run.py --enable-video\n"
                "   一次性试用：python3 run.py --video --confirm-cost"
            )
            return 0

    # ---- Step 1: picker mode (synchronous render, immediate return) ----
    if args.pick_style:
        if picker_mod is None or session_mod is None:
            print("error: picker/session modules not importable", file=sys.stderr)
            return 2
        sid = args.session or session_mod.current_session("lumicc-content") \
            or session_mod.new_session("lumicc-content", args.store_id)
        path = picker_mod.render_picker("landing_style", sid)
        if args.open:
            import webbrowser
            webbrowser.open(f"file://{path}")
        print(json.dumps({
            "session_id": sid,
            "picker_url": f"file://{path}",
            "next": "等用户在浏览器选完风格后回来运行 --build --session " + sid,
        }, ensure_ascii=False))
        return 0

    if not args.type:
        print("error: --type is required (unless using --pick-style)", file=sys.stderr)
        return 2

    ROOT.mkdir(exist_ok=True)
    (ROOT / "runs").mkdir(exist_ok=True)
    ensure_generated_assets_table()

    # ---- Step 2: read style/palette choices if session given ----
    style_choice: dict | None = None
    palette_choice: dict | None = None
    if args.session and session_mod is not None:
        style_choice = session_mod.read_choice(args.session, "landing_style")
        palette_choice = session_mod.read_choice(args.session, "color_palette")
        if args.build and not style_choice:
            print(f"error: --build requires a confirmed landing_style choice. "
                  f"Run with --pick-style --session {args.session} first.",
                  file=sys.stderr)
            return 2

    store = get_store(args.store_id)
    language = detect_language(args.language, store)
    run_id = args.run_id or str(uuid.uuid4())
    run_dir = ROOT / "runs" / run_id
    generated_dir = run_dir / "generated"
    run_dir.mkdir(parents=True, exist_ok=True)

    # API key probe (silent if missing — falls back to prompt-only).
    # New image_client (v0.4) uses secret_form; if available it returns the key.
    api_key: str | None = None
    if not args.dry_run:
        if hasattr(ic, "get_api_key"):
            try:
                api_key = ic.get_api_key()  # type: ignore[attr-defined]
            except Exception:
                api_key = None
        else:
            # v0.4 image_client — probe via _require_key
            try:
                api_key = ic._require_key()  # type: ignore[attr-defined]
            except Exception:
                api_key = None

    # Build items
    sku_list = args.sku or ([None] if args.type in ("email_sequence",) else [None])
    all_items: list[dict] = []
    for sku in sku_list:
        prod = get_product(sku, args.store_id) if sku else None
        kwargs = {
            "sku": sku or (store.get("niche") if store else "default"),
            "title": (prod.get("title") if prod else None),
            "niche": (store.get("niche") if store else None),
            "target_market": (store.get("target_market") if store else "us"),
            "occasion": args.occasion,
            "style": args.style,
            "count": args.count,
            "model": args.model,
            "size": args.size,
            "language": language,
            "platform": args.platform,
            "campaign": args.campaign,
            "enable_video_gen": args.enable_video_gen,
            "style_choice": style_choice,
        }
        if args.angles:
            kwargs["angles"] = [a.strip() for a in args.angles.split(",") if a.strip()]
        items = prompts_mod.generate(args.type, **kwargs)
        all_items.extend(items)

    # Cost estimation (USD via image_client.estimate_cost; falls back to legacy)
    estimated_credits = 0.0
    for it in all_items:
        params = it.get("image_gen_params") or {}
        if params and not args.dry_run and api_key:
            n = int(params.get("n", 1) or 1)
            model = params.get("model", "auto")
            if hasattr(ic, "estimate_credits"):
                estimated_credits += ic.estimate_credits(  # type: ignore[attr-defined]
                    model, n=n, quality=args.quality,
                )
            elif hasattr(ic, "estimate_cost"):
                estimated_credits += ic.estimate_cost(model, n)
        vparams = it.get("video_gen_params") or {}
        if vparams and args.enable_video_gen and not args.dry_run and api_key:
            try:
                import video_client as vc  # type: ignore
                estimated_credits += vc.estimate_video_credits(
                    vparams["model"],
                    duration_s=vparams.get("duration_s", 6),
                    resolution=vparams.get("resolution", "720p"),
                )
            except ImportError:
                if hasattr(ic, "estimate_cost"):
                    estimated_credits += ic.estimate_cost(
                        vparams.get("model", "sora-2"), 1,
                        duration=vparams.get("duration_s", 5),
                        resolution=vparams.get("resolution", "720p"),
                    )

    if estimated_credits > args.max_credits:
        msg = f"Estimated cost {estimated_credits} credits exceeds --max-credits {args.max_credits}. Aborting."
        print(msg, file=sys.stderr)
        return 2

    if not args.dry_run and api_key and estimated_credits > 0 and not args.auto_confirm and sys.stdin.isatty():
        print(f"\n⚠️  About to consume ~{estimated_credits} credits via evolink.ai. Continue? [y/N] ", end="", flush=True)
        ans = sys.stdin.readline().strip().lower()
        if ans not in ("y", "yes"):
            print("Aborted.")
            return 0

    # --estimate-only short circuit
    if args.estimate_only:
        est_usd = sum(
            ic.estimate_cost((it.get("image_gen_params") or {}).get("model", "auto"), 1)
            for it in all_items if it.get("image_gen_params")
        )
        if args.video:
            est_usd += sum(
                ic.estimate_cost(
                    (it.get("video_gen_params") or {}).get("model", ic.MODEL_SORA_2),
                    1,
                    duration=(it.get("video_gen_params") or {}).get("duration_s", 5),
                    resolution=(it.get("video_gen_params") or {}).get("resolution", "720p"),
                ) for it in all_items if it.get("video_gen_params")
            )
        print(json.dumps({"estimate_usd": round(est_usd, 4),
                          "items": len(all_items)}, ensure_ascii=False))
        return 0

    # Generate
    credits_consumed = 0.0
    generated_images: list[dict] = []
    generated_videos: list[dict] = []
    warnings: list[str] = []
    total_cost_usd = 0.0
    primary_sku = args.sku[0] if args.sku else None

    if args.generate_images and not args.dry_run:
        try:
            generated_images, w, cost_i = generate_images_v04(
                all_items, run_id, args.store_id, primary_sku, generated_dir,
            )
            warnings.extend(w)
            total_cost_usd += cost_i
            credits_consumed += cost_i
        except ic.MissingSecretError:
            _print_missing_secret_help()
            return 1

    if args.video and (args.confirm_cost or (get_pref("video_gen_enabled") or "").lower() == "true") \
            and not args.dry_run:
        try:
            generated_videos, w, cost_v = generate_videos_v04(
                all_items, run_id, args.store_id, primary_sku, generated_dir,
            )
            warnings.extend(w)
            total_cost_usd += cost_v
            credits_consumed += cost_v
        except ic.MissingSecretError:
            _print_missing_secret_help()
            return 1

    # Legacy generation path: preserved for backwards compat (existing tests).
    if not args.dry_run and api_key and not args.generate_images and not args.video:
        generated_dir.mkdir(exist_ok=True)
        for it in all_items:
            c1, _ = maybe_generate_image(it, generated_dir, language, args.dry_run, api_key)
            c2, _ = maybe_generate_video(it, generated_dir, args.dry_run, api_key, args.enable_video_gen)
            credits_consumed += c1 + c2

    # Persist each item as a generated_assets row
    for it in all_items:
        local = ""
        if it.get("image_local_paths"):
            local = it["image_local_paths"][0]
        elif it.get("video_local_paths"):
            local = it["video_local_paths"][0]
        insert_asset({
            "id": it.get("id") or str(uuid.uuid4()),
            "run_id": run_id,
            "store_id": args.store_id,
            "sku": (args.sku[0] if args.sku else None),
            "asset_type": "image" if it.get("image_local_paths") else
                          "video" if it.get("video_local_paths") else
                          "prompt",
            "category": it.get("category", args.type),
            "prompt_text": it.get("prompt_text"),
            "model": it.get("model") or (it.get("image_gen_params") or {}).get("model"),
            "size": (it.get("image_gen_params") or {}).get("size"),
            "local_path": local,
            "remote_url": None,
            "remote_url_expires_at": (int(time.time()) + 24 * 3600) if local else None,
            "credits": it.get("credits", 0),
        })

    # Render HTML
    html_path = run_dir / "content.html"
    page = html_mod.render_page(
        run_id=run_id,
        store_name=(store.get("name") if store else None),
        items=all_items,
        credits_consumed=round(credits_consumed, 2),
        dry_run=args.dry_run,
        html_path=html_path,
        style_choice=style_choice,
        palette_choice=palette_choice,
        generated_images=generated_images,
        total_cost_usd=round(total_cost_usd, 4),
    )
    html_path.write_text(page, encoding="utf-8")

    # Result
    result = {
        "run_id": run_id, "skill": "lumicc-content", "status": "success",
        "store_id": args.store_id, "type": args.type,
        "items_count": len(all_items),
        "credits_consumed": round(credits_consumed, 2),
        "total_cost_usd": round(total_cost_usd, 4),
        "generated_images": generated_images,
        "generated_videos": generated_videos,
        "warnings": warnings,
        "html_path": str(html_path),
        "items": [{
            "id": it.get("id") or "",
            "category": it.get("category"),
            "subject": it.get("subject"),
            "model": it.get("model") or (it.get("image_gen_params") or {}).get("model"),
            "image_local_paths": it.get("image_local_paths", []),
            "video_local_paths": it.get("video_local_paths", []),
            "credits": it.get("credits", 0),
            "error": it.get("error"),
        } for it in all_items],
    }
    (run_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    append_run(run_id, args.store_id, "success", str(run_dir / "result.json"))
    append_event(args.store_id, f"lumicc-content: generated {len(all_items)} items of type '{args.type}' "
                                f"(credits={round(credits_consumed,2)})")

    if not args.quiet_stdout:
        print(f"✓ Generated {len(all_items)} items · {round(credits_consumed,2)} credits used")
        print(f"  Open: file://{html_path}")

    if args.notify_channel:
        notify_mod.notify(
            channel=args.notify_channel, target=args.notify_target,
            title=f"🎨 内容工厂 · {len(all_items)} 个产出 · {round(credits_consumed,2)} credits",
            body_md=f"打开页面查看: file://{html_path}\n类型: {args.type}",
            severity="info", skill="lumicc-content", run_id=run_id,
        )

    if args.quiet_stdout:
        print(json.dumps({"run_id": run_id, "items": len(all_items),
                          "credits": round(credits_consumed, 2),
                          "html": str(html_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
