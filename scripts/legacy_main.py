from __future__ import annotations

import argparse
import hashlib
import json
import os
import time as time_module
from datetime import datetime, time
from pathlib import Path

from baidu_maps import BaiduMapsClient, BaiduMapsError
from fetcher import fetch_html
from filters import Profile, deterministic_score, hard_filter, sort_key
from llm_client import evaluate
from parser import Listing, parse_listings
from report import write_report
from store import Store


DEFAULT_CONFIG = Path(__file__).with_name("config.json")
DEFAULT_ENV = Path(__file__).with_name(".env")


def load_dotenv(path: Path = DEFAULT_ENV) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def make_profile(config: dict) -> Profile:
    values = config.get("profile", {})
    return Profile(
        areas=tuple(values.get("areas", [])),
        subjects=tuple(values.get("subjects", [])),
        grades=tuple(values.get("grades", [])),
        min_price=values.get("min_price"),
        max_price=values.get("max_price"),
        max_distance_meters=values.get("max_distance_meters"),
        allow_online=bool(values.get("allow_online", True)),
        conditions=values.get("conditions", ""),
    )


def evaluation_scope(config: dict) -> str:
    material = json.dumps(
        {
            "profile": config.get("profile", {}),
            "maps": config.get("maps", {}),
            "semantic_schema": 2,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def within_schedule(config: dict) -> bool:
    schedule = config.get("schedule", {})
    now = datetime.now().time()
    start = time.fromisoformat(schedule.get("start", "09:00"))
    end = time.fromisoformat(schedule.get("end", "21:00"))
    return start <= now <= end


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


def run(config: dict, dry_run: bool = False) -> int:
    source = config["source"]
    store = Store(config["storage"]["database"])
    run_id = store.start_run()
    try:
        if not dry_run and not within_schedule(config):
            print("当前不在轮询时间窗口内（09:00-21:00）")
            return 0
        document = fetch_html(source["url"], source.get("timeout_seconds", 20))
        listings = parse_listings(document, source["url"])
        profile = make_profile(config)
        maps_config = config.get("maps", {})
        maps_client = BaiduMapsClient.from_environment(maps_config) if maps_config else None
        origin = None
        if maps_client:
            try:
                origin = maps_client.geocode(maps_config["origin"])
            except BaiduMapsError as error:
                print(f"百度地图原点解析失败：{error}")
        elif profile.max_distance_meters is not None:
            print("未设置百度地图 API Key，无法执行距离筛选")
        scope = evaluation_scope(config)
        new_count = 0
        candidates: list[tuple[tuple[float, float, float], float, Listing, dict, float | None]] = []
        rejected: list[dict] = []
        for listing in listings:
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
                        print(f"地址测距失败 [{listing.external_id}]：{error}")
                        store.save_map_cache(listing.address, 0, 0, None)
            passed, reason = hard_filter(listing, profile, distance_meters)
            if not passed:
                store.save_evaluation(
                    listing.external_id,
                    {"hard_pass": False, "hard_reason": reason, "evaluation_scope": scope},
                )
                rejected.append(
                    {"listing": listing, "stage": "硬过滤", "reason": reason, "distance_meters": distance_meters}
                )
                continue
            existing = store.evaluation(listing.external_id)
            if existing and existing["notified"] and existing["evaluation_scope"] == scope:
                continue
            if existing and existing["evaluation_scope"] == scope and existing["llm_pass"] is not None:
                if not existing["llm_pass"]:
                    rejected.append(
                        {
                            "listing": listing,
                            "stage": "语义评估",
                            "reason": existing["llm_reason"],
                            "distance_meters": distance_meters,
                        }
                    )
                    continue
                try:
                    extracted = json.loads(existing["extracted"])
                except (TypeError, json.JSONDecodeError):
                    extracted = {}
                semantic = {"pass": True, "reason": existing["llm_reason"], "extracted": extracted}
            else:
                semantic = evaluate(
                    config.get("llm", {}).get("url", ""),
                    config.get("llm", {}).get("api_key_env", "LLM_API_KEY"),
                    config.get("llm", {}).get("timeout_seconds", 30),
                    profile.conditions,
                    listing_text(listing, distance_meters),
                )
            if not semantic["pass"]:
                store.save_evaluation(
                    listing.external_id,
                    {"hard_pass": True, "llm_pass": False, "llm_reason": semantic["reason"], "evaluation_scope": scope, "extracted": semantic.get("extracted", {})},
                )
                rejected.append(
                    {"listing": listing, "stage": "语义评估", "reason": semantic["reason"], "distance_meters": distance_meters}
                )
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
        candidates.sort(key=lambda item: item[0])
        report_path = write_report(
            Path(config["storage"].get("report", "data/report.html")),
            source_url=source["url"],
            origin=(maps_config or {}).get("origin"),
            max_distance_meters=profile.max_distance_meters,
            fetched=len(listings),
            new_count=new_count,
            candidates=[
                {
                    "listing": listing,
                    "extracted": evaluation.get("extracted", {}),
                    "reason": evaluation.get("llm_reason", ""),
                    "points": points,
                    "distance_meters": distance_meters,
                }
                for _, points, listing, evaluation, distance_meters in candidates
            ],
            rejected=rejected,
        )
        print(f"筛选报告已生成：{report_path}")
        print(f"合格候选 {len(candidates)} 条")
        for index, (_, points, listing, evaluation, distance_meters) in enumerate(candidates, 1):
            extracted = evaluation["extracted"]
            print(
                f"{index}. [{points}] {listing.external_id} {listing.title} | "
                f"时薪 {extracted.get('hourly_rate_min')}-{extracted.get('hourly_rate_max')} | "
                f"总收益 {extracted.get('total_income')} | "
                f"距离 {distance_meters}m | 时间 {extracted.get('schedule_text', listing.teaching_time)}"
            )
        if candidates and not dry_run:
            evaluation = candidates[0][3]
            store.save_evaluation(candidates[0][2].external_id, {**evaluation, "notified": True})
        store.finish_run(run_id, fetched=len(listings), new_count=new_count, candidate_count=len(candidates))
        print(f"本次抓取 {len(listings)} 条，新增 {new_count} 条，候选 {len(candidates)} 条")
        return 0
    except Exception as error:
        store.finish_run(run_id, error=str(error))
        raise
    finally:
        store.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="定时抓取宁波家教信息")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--dry-run", action="store_true", help="只输出推荐，不标记为已询问")
    parser.add_argument("--loop", action="store_true", help="在配置的时间窗口内按间隔持续轮询")
    args = parser.parse_args()
    load_dotenv()
    config = load_config(args.config)
    if args.loop:
        interval = config.get("schedule", {}).get("interval_hours", 2) * 3600
        while True:
            run(config)
            time_module.sleep(interval)
    return run(config, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
