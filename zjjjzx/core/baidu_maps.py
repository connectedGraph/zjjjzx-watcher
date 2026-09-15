from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from urllib.error import HTTPError, URLError


@dataclass(frozen=True)
class Coordinate:
    latitude: float
    longitude: float


@dataclass(frozen=True)
class Route:
    distance_meters: float
    duration_seconds: float | None


class BaiduMapsError(RuntimeError):
    pass


class BaiduMapsClient:
    def __init__(self, api_key: str, city: str, timeout: float = 10) -> None:
        if not api_key:
            raise ValueError("Baidu Maps API key is empty")
        self.api_key = api_key
        self.city = city
        self.timeout = timeout

    @classmethod
    def from_environment(cls, config: dict) -> BaiduMapsClient | None:
        api_key_env = config.get("api_key_env", "BAIDU_MAP_AK")
        api_key = os.getenv(api_key_env, "")
        if not api_key:
            return None
        return cls(api_key, config["city"], config.get("timeout_seconds", 10))

    def geocode(self, address: str) -> Coordinate:
        params = urllib.parse.urlencode(
            {
                "address": address,
                "city": self.city,
                "output": "json",
                "ak": self.api_key,
            }
        )
        payload = self._get("https://api.map.baidu.com/geocoding/v3/", params)
        result = self._result(payload).get("result")
        if not isinstance(result, dict):
            raise BaiduMapsError("geocoding response has no result")
        location = result.get("location")
        if not isinstance(location, dict):
            raise BaiduMapsError("geocoding response has no location")
        try:
            return Coordinate(float(location["lat"]), float(location["lng"]))
        except (KeyError, TypeError, ValueError) as error:
            raise BaiduMapsError("geocoding response has invalid location") from error

    def driving_route(self, origin: Coordinate, destination: Coordinate) -> Route:
        params = urllib.parse.urlencode(
            {
                "origins": f"{origin.latitude},{origin.longitude}",
                "destinations": f"{destination.latitude},{destination.longitude}",
                "ak": self.api_key,
            }
        )
        payload = self._get("https://api.map.baidu.com/routematrix/v2/driving", params)
        result = self._result(payload)
        rows = result.get("result")
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            raise BaiduMapsError("route response has no result")
        distance = rows[0].get("distance")
        duration = rows[0].get("duration")
        try:
            distance_meters = float(distance["value"])
            duration_seconds = float(duration["value"]) if isinstance(duration, dict) else None
        except (KeyError, TypeError, ValueError) as error:
            raise BaiduMapsError("route response has invalid distance") from error
        return Route(distance_meters, duration_seconds)

    def _get(self, endpoint: str, query: str) -> dict:
        request = urllib.request.Request(
            f"{endpoint}?{query}",
            headers={"User-Agent": "zjjjzx-watcher/1.0", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, ValueError) as error:
            raise BaiduMapsError(f"Baidu Maps request failed: {error}") from error
        if not isinstance(payload, dict):
            raise BaiduMapsError("Baidu Maps response is not an object")
        return payload

    @staticmethod
    def _result(payload: dict) -> dict:
        if payload.get("status") != 0:
            message = payload.get("message") or f"status={payload.get('status')}"
            raise BaiduMapsError(f"Baidu Maps API error: {message}")
        return payload
