"""An account's Vocabulary.com assignments, and which ones several accounts share.

Read in the account's own browser tab: the live list from the site's `/me/assignments` call
(the same one its "My assignments" page makes), falling back to the copy the site caches in
localStorage["me/auth"]. Both shapes are normalised here so this part is testable without Chrome.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone

BASE_URL = "https://www.vocabulary.com"
KIND_LABEL = {"p": "Practice", "s": "Spelling Bee", "q": "Quiz"}

# Runs in the page (execute_async_script). Returns raw data; Python does the parsing.
FETCH_JS = r"""
const done = arguments[arguments.length - 1];
(async () => {
  const out = {api: null, apiError: null, cache: null};
  try {
    const api = window.modules && modules.vcom && modules.vcom.api;
    if (api && api.remote) {
      out.api = await new Promise((resolve, reject) => {
        api.remote("/me/assignments", {data: {complete: false}}).then(resolve, (e) => reject(e));
        setTimeout(() => reject("timed out"), 8000);
      });
    } else {
      out.apiError = "site API not on this page";
    }
  } catch (e) { out.apiError = String((e && (e.statusText || e.message)) || e); }
  try { out.cache = JSON.parse(localStorage.getItem("me/auth") || "null"); } catch (e) {}
  done(out);
})();
"""


@dataclass(frozen=True)
class Assignment:
    id: str
    name: str
    kind: str            # "p" practice, "s" spelling bee, "q" quiz
    url: str
    pct: int             # percent complete
    due: str | None      # ISO timestamp
    class_name: str = ""
    words: int | None = None

    @property
    def supported(self) -> bool:
        return self.kind == "p"  # the answering loop handles practice questions

    @property
    def kind_label(self) -> str:
        return KIND_LABEL.get(self.kind, "Activity")

    def to_dict(self) -> dict:
        return {**asdict(self), "supported": self.supported, "kind_label": self.kind_label}


def _url(kind: str, item: dict) -> str:
    if item.get("url"):
        path = item["url"]
    elif kind == "q":
        path = f"/quiz/assignment/{item.get('class_id')}/{item.get('id')}"
    elif kind == "s":
        path = f"/lists/{item.get('wordlist_id')}/bee"
    else:
        aid = item.get("max_progress_activity_id")
        path = f"/lists/{item.get('wordlist_id')}/practice" + (f"?aid={aid}" if aid else "")
    return path if "://" in path else BASE_URL + path


def _visible(iso: str | None) -> bool:
    if not iso:
        return True
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")) <= datetime.now(timezone.utc)
    except ValueError:
        return True


def from_api(resp: dict) -> list[Assignment]:
    """Shape of the live `/me/assignments` response: snake_case, progress 0..1."""
    classes = {c.get("id"): c.get("name", "") for c in resp.get("classes") or [] if isinstance(c, dict)}
    out = []
    for a in resp.get("assignments") or []:
        if not isinstance(a, dict) or not a.get("id") or not _visible(a.get("visible_at")):
            continue
        kind = a.get("type") or "p"
        if "pctComplete" in a:
            pct = int(a["pctComplete"] or 0)
        else:
            pct = int(100 * float(a.get("progress") or 0))
        out.append(Assignment(
            id=str(a["id"]), name=a.get("name") or "Untitled assignment", kind=kind, url=_url(kind, a),
            pct=pct, due=a.get("due_at"), class_name=classes.get(a.get("class_id"), ""),
            words=a.get("length"),
        ))
    return out


def from_cache(auth: dict) -> list[Assignment]:
    """Shape of the localStorage["me/auth"] copy: camelCase, grouped by class, with pctComplete."""
    value = (auth or {}).get("value") or {}
    out = []
    for cls in ((value.get("classes") or {}).get("memberOf") or []):
        for a in cls.get("assignments") or []:
            if not a.get("id") or not _visible(a.get("visibleDate")):
                continue
            kind = a.get("type") or "p"
            out.append(Assignment(
                id=str(a["id"]), name=a.get("name") or "Untitled assignment", kind=kind, url=_url(kind, a),
                pct=int(a.get("pctComplete") or 0), due=a.get("dueDate"), class_name=cls.get("name", ""),
                words=a.get("length"),
            ))
    return out


def parse(raw: dict) -> tuple[list[Assignment], str]:
    """Unfinished assignments from FETCH_JS output, soonest due first. Returns (list, source)."""
    if isinstance(raw.get("api"), dict) and "assignments" in raw["api"]:
        items, source = from_api(raw["api"]), "live"
    elif isinstance(raw.get("cache"), dict):
        items, source = from_cache(raw["cache"]), "cached"
    else:
        return [], "none"
    todo = {a.id: a for a in items if a.pct < 100}  # de-dup: an assignment can appear under two classes
    return sorted(todo.values(), key=lambda a: (a.due is None, a.due or "", a.name.lower())), source


def shared_ids(lists: list[list[dict]]) -> list[str]:
    """Ids of supported assignments present in every list, in the first list's order."""
    if len(lists) < 2:
        return []
    common = set.intersection(*({a["id"] for a in lst if a.get("supported")} for lst in lists))
    return [a["id"] for a in lists[0] if a["id"] in common]
