from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from zjjjzx.config import evaluation_scope, make_profile, within_schedule
from zjjjzx.core.baidu_maps import BaiduMapsClient, BaiduMapsError
from zjjjzx.core.fetcher import fetch_html
from zjjjzx.core.filters import deterministic_score, hard_filter, sort_key
from zjjjzx.core.llm_client import evaluate
from zjjjzx.core.parser import Listing, parse_listings
from zjjjzx.core.report import write_report
from zjjjzx.core.store import Store


EventCallback = Callable[[str, dict[str, Any]], None]


def listing_text(listing: Listing, distance_meters: float | None) -> str:
    distance = "未测得" if distance_meters is None else f"{distance_meters / 1000:.2f} 公里"
    return "\n".join(
        [
            f"标题：{listing.title}",
            f"价格：{listing.price_text}",
            f"区域：{listing.address}",
            f"授课方式：{listing.teaching_mode}",
            f"授课时间：{listing.teaching_time}",
            f"要求：{listing.requirements}",
            f"发布时间：{listing.publish_date}",
            f"百度地图驾车距离：{distance}",
        ]
    )


def run_pipeline(
    config: dict[str, Any],
    dry_run: bool = False,
    ignore_schedule: bool = False,
    enable_llm: bool = True,
    on_event: EventCallback | None = None,
) -> dict[str, Any]:
    def emit(event_type: str, **data: Any) -> None:
        if on_event:
            try:
                on_event(event_type, data)
            except Exception:
                pass

    source = config.get("source", {})
    if not source.get("url"):
        raise ValueError("source.url is not configured")

    db_path = config.get("storage", {}).get("database", "data/watcher.db")
    store = Store(db_path)
    run_id = store.start_run()
    emit("run_started", run_id=run_id, url=source["url"])

    try:
        if not dry_run and not ignore_schedule and not within_schedule(config):
            msg = "当前不在轮询时间窗口内（默认 09:00-21:00），已跳过抓取"
            emit("log", level="warn", message=msg)
            store.finish_run(run_id, error="outside schedule window")
            return {
                "success": True,
                "outside_schedule": True,
                "fetched": 0,
                "new_count": 0,
                "candidates": [],
                "rejected": [],
                "report_path": None,
            }

        emit("log", level="info", message=f"正在请求页面：{source['url']}")
        document = fetch_html(source["url"], source.get("timeout_seconds", 20))
        listings = parse_listings(document, source["url"])
        emit("listings_fetched", count=len(listings))
        emit("log", level="info", message=f"页面解析完成，共发现 {len(listings)} 条家教需求")

        profile = make_profile(config)
        maps_config = config.get("maps", {})
        maps_client = BaiduMapsClient.from_environment(maps_config) if maps_config else None
        origin = None

        if maps_client and maps_config.get("origin"):
            try:
                origin = maps_client.geocode(maps_config["origin"])
                emit("log", level="info", message=f"百度地图原点解析成功：{maps_config['origin']}")
            except BaiduMapsError as error:
                emit("log", level="warn", message=f"百度地图原点解析失败：{error}")
        elif profile.max_distance_meters is not None:
            emit("log", level="warn", message="未配置有效百度地图 AK，将跳过驾车测距")

        scope = evaluation_scope(config)
        new_count = 0
        candidates: list[tuple[tuple[float, float, float], float, Listing, dict, float | None]] = []
        rejected: list[dict[str, Any]] = []

        for idx, listing in enumerate(listings, 1):
            if store.upsert(listing):
                new_count += 1

            distance_meters = None
            if maps_client and origin and listing.address:
                cached = store.map_cache(listing.address)
                if cached:
                    distance_meters = cached["distance_meters"]
                else:
                    try:
                        destination = maps_client.geocode(listing.address)
                        route = maps_client.driving_route(origin, destination)
                        distance_meters = route.distance_meters
                        store.save_map_cache(
                            listing.address,
                            destination.latitude,
                            destination.longitude,
                            distance_meters,
                        )
                    except BaiduMapsError as error:
                        emit("log", level="warn", message=f"地址测距失败 [{listing.external_id}]：{error}")
                        store.save_map_cache(listing.address, 0, 0, None)

            passed, reason = hard_filter(listing, profile, distance_meters)
            if not passed:
                store.save_evaluation(
                    listing.external_id,
                    {"hard_pass": False, "hard_reason": reason, "evaluation_scope": scope},
                )
                rej_item = {
                    "listing": listing,
                    "stage": "硬过滤",
                    "reason": reason,
                    "distance_meters": distance_meters,
                }
                rejected.append(rej_item)
                emit("rejected_item", index=idx, total=len(listings), **rej_item)
                continue

            existing = store.evaluation(listing.external_id)
            if existing and existing["notified"] and existing["evaluation_scope"] == scope and not dry_run:
                # Already processed & notified in current scope
                continue

            if existing and existing["evaluation_scope"] == scope and existing["llm_pass"] is not None:
                if not existing["llm_pass"]:
                    rej_item = {
                        "listing": listing,
                        "stage": "语义评估",
                        "reason": existing["llm_reason"],
                        "distance_meters": distance_meters,
                    }
                    rejected.append(rej_item)
                    emit("rejected_item", index=idx, total=len(listings), **rej_item)
                    continue
                try:
                    extracted = json.loads(existing["extracted"])
                except (TypeError, json.JSONDecodeError):
                    extracted = {}
                semantic = {"pass": True, "reason": existing["llm_reason"], "extracted": extracted}
            elif not enable_llm:
                # LLM evaluation skipped by user flag
                semantic = {
                    "pass": True,
                    "reason": "已跳过 LLM 语义评估（硬过滤通过）",
                    "extracted": {
                        "subject": listing.subject,
                        "grade": listing.grade,
                        "mode": listing.teaching_mode,
                    },
                }
            else:
                emit("log", level="info", message=f"正在进行 LLM 语义判断：[{listing.external_id}] {listing.title}")
                semantic = evaluate(
                    config.get("llm", {}).get("url", ""),
                    config.get("llm", {}).get("api_key_env", "DEEPSEEK_API_KEY"),
                    config.get("llm", {}).get("timeout_seconds", 30),
                    profile.conditions,
                    listing_text(listing, distance_meters),
                )

            if not semantic["pass"]:
                store.save_evaluation(
                    listing.external_id,
                    {
                        "hard_pass": True,
                        "llm_pass": False,
                        "llm_reason": semantic["reason"],
                        "evaluation_scope": scope,
                        "extracted": semantic.get("extracted", {}),
                    },
                )
                rej_item = {
                    "listing": listing,
                    "stage": "语义评估",
                    "reason": semantic["reason"],
                    "distance_meters": distance_meters,
                }
                rejected.append(rej_item)
                emit("rejected_item", index=idx, total=len(listings), **rej_item)
                continue

            points = deterministic_score(
                semantic["extracted"], distance_meters, profile.max_distance_meters or 10000
            )
            evaluation = {
                "hard_pass": True,
                "llm_pass": True,
                "llm_reason": semantic["reason"],
                "score": points,
                "evaluation_scope": scope,
                "extracted": semantic["extracted"],
            }
            store.save_evaluation(listing.external_id, evaluation)
            candidates.append(
                (sort_key(semantic["extracted"], distance_meters), points, listing, evaluation, distance_meters)
            )
            emit(
                "candidate_added",
                index=idx,
                total=len(listings),
                listing=listing,
                points=points,
                distance_meters=distance_meters,
                extracted=semantic["extracted"],
            )

        candidates.sort(key=lambda item: item[0])
        formatted_candidates = [
            {
                "listing": listing,
                "extracted": evaluation.get("extracted", {}),
                "reason": evaluation.get("llm_reason", ""),
                "points": points,
                "distance_meters": distance_meters,
            }
            for _, points, listing, evaluation, distance_meters in candidates
        ]

        report_target = Path(config.get("storage", {}).get("report", "data/report.html"))
        report_path = write_report(
            report_target,
            source_url=source["url"],
            origin=(maps_config or {}).get("origin"),
            max_distance_meters=profile.max_distance_meters,
            fetched=len(listings),
            new_count=new_count,
            candidates=formatted_candidates,
            rejected=rejected,
        )
        emit("report_generated", path=str(report_path))

        if candidates and not dry_run:
            top_eval = candidates[0][3]
            store.save_evaluation(candidates[0][2].external_id, {**top_eval, "notified": True})

        store.finish_run(
            run_id,
            fetched=len(listings),
            new_count=new_count,
            candidate_count=len(candidates),
        )

        summary = {
            "success": True,
            "run_id": run_id,
            "fetched": len(listings),
            "new_count": new_count,
            "candidates": formatted_candidates,
            "rejected": rejected,
            "report_path": str(report_path),
        }
        emit("run_finished", **summary)
        return summary

    except Exception as error:
        emit("log", level="error", message=f"抓取异常终止：{error}")
        store.finish_run(run_id, error=str(error))
        raise
    finally:
        store.close()
