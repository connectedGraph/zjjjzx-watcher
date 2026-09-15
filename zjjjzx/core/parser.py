from __future__ import annotations

import hashlib
import html
import re
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin


@dataclass(frozen=True)
class Listing:
    external_id: str
    site_job_id: str
    title: str
    grade: str
    subject: str
    price_text: str
    price_value: float | None
    address: str
    teaching_mode: str
    gender: str
    teaching_time: str
    requirements: str
    publish_date: str
    detail_url: str
    raw_text: str

    def to_dict(self) -> dict:
        return asdict(self)


class _JobCardParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.cards: list[dict[str, str]] = []
        self._card: dict[str, str] | None = None
        self._card_depth = 0
        self._job_title = ""
        self._job_price = ""
        self._text: list[str] = []
        self._capture_title = False
        self._capture_price = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "div" and "job-card" in classes:
            self._card = {
                key.removeprefix("data-"): value or ""
                for key, value in attributes.items()
                if key.startswith("data-")
            }
            self._card_depth = 1
            self._job_title = ""
            self._job_price = ""
            self._text = []
            return
        if self._card is None:
            return
        if tag == "div":
            self._card_depth += 1
        if tag == "h3" and "job-title" in classes:
            self._capture_title = True
        elif tag == "span" and "job-price" in classes:
            self._capture_price = True

    def handle_endtag(self, tag: str) -> None:
        if self._card is None:
            return
        if tag == "h3" and self._capture_title:
            self._capture_title = False
        elif tag == "span" and self._capture_price:
            self._capture_price = False
        if tag == "div":
            self._card_depth -= 1
            if self._card_depth == 0:
                self._card["title"] = self._job_title
                self._card["price"] = self._job_price
                self._card["raw"] = " ".join(self._text)
                self.cards.append(self._card)
                self._card = None

    def handle_data(self, data: str) -> None:
        if self._card is None:
            return
        value = " ".join(data.split())
        if not value:
            return
        self._text.append(value)
        if self._capture_title:
            self._job_title += value
        if self._capture_price:
            self._job_price += value


def _clean(value: str | None) -> str:
    return " ".join(html.unescape(value or "").split())


def _price_value(value: str) -> float | None:
    match = re.search(r"\d+(?:\.\d+)?", value)
    return float(match.group()) if match else None


def parse_listings(document: str, base_url: str) -> list[Listing]:
    parser = _JobCardParser(base_url)
    parser.feed(document)
    listings: list[Listing] = []
    for card in parser.cards:
        job_number = _clean(card.get("job-number"))
        raw = _clean(card.get("raw"))
        if not job_number:
            job_number = "hash-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        title = _clean(card.get("title"))
        detail_url = urljoin(base_url, "teacher/")
        listings.append(
            Listing(
                external_id=job_number,
                site_job_id=_clean(card.get("job-id")),
                title=title,
                grade=_clean(card.get("grade")),
                subject=_clean(card.get("subject")),
                price_text=_clean(card.get("salary") or card.get("price")),
                price_value=_price_value(card.get("salary") or card.get("price") or ""),
                address=_clean(card.get("address")),
                teaching_mode=_clean(card.get("teaching-mode")),
                gender=_clean(card.get("gender")),
                teaching_time=_clean(card.get("teaching-time")),
                requirements=_clean(card.get("requirements")),
                publish_date=_clean(card.get("publish-date")),
                detail_url=detail_url,
                raw_text=raw,
            )
        )
    return listings
