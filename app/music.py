"""
网易云歌单代理（本地学习/专注背景音乐）
=====================================
浏览器无法直接播放网易云歌单（需要签名、版权校验与登录态），因此由服务端代取：

1. 曲目列表
   - 未登录：/api/v6/playlist/detail 只返回歌单前 10 首（网易未登录限制）
   - 已登录：/api/playlist/track/all 可拿全量曲目
2. 单曲播放直链
   - /api/song/enhance/player/url，直链有时效（约 20 分钟），这里缓存 8 分钟

登录 cookie（可选，用于解锁完整歌单，切勿提交到代码仓库）：
  - 环境变量 NCM_COOKIE，或
  - eeg-focus/data/music_cookie.txt（整行为 `MUSIC_U=...; __csrf=...`）

歌单 ID 可用环境变量 NCM_PLAYLIST_ID 覆盖。
"""

import json
import os
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

PLAYLIST_ID = os.environ.get("NCM_PLAYLIST_ID", "2392709157")
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_COOKIE_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "music_cookie.txt")


def _cookie() -> str:
    env = (os.environ.get("NCM_COOKIE") or "").strip()
    if env:
        return env
    try:
        with open(_COOKIE_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _get_json(url: str, timeout: float = 12.0) -> dict:
    headers = {"User-Agent": _UA, "Referer": "https://music.163.com/"}
    ck = _cookie()
    if ck:
        headers["Cookie"] = ck
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        text = r.read().decode("utf-8", "ignore").lstrip("\ufeff").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 接口偶尔会返回「JSON + 多余内容」，取第一个完整 JSON 对象
        obj, _ = json.JSONDecoder().raw_decode(text)
        return obj


def _shape(track: dict, idx: int) -> dict:
    artists = track.get("ar") or track.get("artists") or []
    album = track.get("al") or track.get("album") or {}
    duration = track.get("dt") or track.get("duration") or 0
    return {
        "index": idx,
        "id": track.get("id"),
        "name": track.get("name") or "未知曲目",
        "artists": " / ".join(a.get("name", "") for a in artists if a.get("name")) or "未知",
        "album": album.get("name", "") or "",
        "duration": round(duration / 1000),
    }


class MusicService:
    """歌单与直链的进程内缓存。"""

    TRACK_TTL = 1800.0   # 歌单缓存 30 分钟
    URL_TTL = 480.0      # 直链缓存 8 分钟（网易直链约 20 分钟过期）

    def __init__(self):
        self._lock = threading.Lock()
        self._load_lock = threading.Lock()
        self._tracks = None
        self._tracks_at = 0.0
        self._name = "专注歌单"
        self._total = 0
        self._limited = False
        self._skipped = 0
        self._urls = {}

    # ---------------- 歌单 ----------------
    def playlist(self, refresh: bool = False) -> dict:
        with self._lock:
            fresh = self._tracks is not None and (time.time() - self._tracks_at) < self.TRACK_TTL
        if refresh or not fresh:
            with self._load_lock:
                with self._lock:
                    fresh = (self._tracks is not None
                             and (time.time() - self._tracks_at) < self.TRACK_TTL)
                if refresh or not fresh:
                    self._load()
        with self._lock:
            return {
                "id": PLAYLIST_ID,
                "name": self._name,
                "total": self._total,
                "limited": self._limited,
                "count": len(self._tracks or []),
                "skipped": self._skipped,
                "tracks": list(self._tracks or []),
            }

    def _load(self) -> None:
        songs, name, total = [], "专注歌单", 0

        if _cookie():
            try:
                j = _get_json("https://music.163.com/api/playlist/track/all"
                              f"?id={PLAYLIST_ID}&limit=1000&offset=0")
                songs = j.get("songs") or []
            except Exception:
                songs = []

        if not songs:
            j = _get_json(f"https://music.163.com/api/v6/playlist/detail?id={PLAYLIST_ID}")
            pl = j.get("playlist") or {}
            songs = pl.get("tracks") or []
            name = pl.get("name") or name
            total = int(pl.get("trackCount") or 0)

        if not songs:
            raise RuntimeError("歌单获取失败（网络不可用或接口限制）")

        if not total:
            total = len(songs)

        shaped = [_shape(t, i) for i, t in enumerate(songs)]
        playable, skipped = shaped, 0
        if len(shaped) > 1:
            keep = self._probe_playable(shaped)
            if keep:  # 全部不可播时保留原列表，交给前端逐首跳过
                playable, skipped = keep, len(shaped) - len(keep)

        with self._lock:
            self._tracks = playable
            self._name = name
            self._total = total
            self._limited = len(playable) < total
            self._skipped = skipped
            self._tracks_at = time.time()

    def _probe_playable(self, tracks: list) -> list:
        """并发探测匿名状态下可播放的曲目，保持歌单原顺序。"""
        def ok(track):
            try:
                self.url_for(str(track["id"]))
                return True
            except Exception:
                return False

        workers = max(1, min(6, len(tracks)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            flags = list(pool.map(ok, tracks))
        return [t for t, good in zip(tracks, flags) if good]

    # ---------------- 播放直链 ----------------
    def url_for(self, track_id: str) -> dict:
        tid = str(track_id)
        if not tid.isdigit():
            raise RuntimeError("曲目 ID 不合法")
        now = time.time()
        with self._lock:
            hit = self._urls.get(tid)
            if hit and (now - hit[1]) < self.URL_TTL:
                return {"id": tid, "url": hit[0], "cached": True}
        url = self._resolve(tid)
        with self._lock:
            self._urls[tid] = (url, now)
        return {"id": tid, "url": url, "cached": False}

    def _resolve(self, tid: str) -> str:
        ids = urllib.parse.quote(f"[{tid}]")
        reasons = []
        for extra in ("&br=128000", "&level=standard"):
            url = ("https://music.163.com/api/song/enhance/player/url"
                   f"?id={tid}&ids={ids}{extra}")
            try:
                j = _get_json(url)
            except Exception as e:
                reasons.append(f"直链请求失败：{e}")
                continue
            data = j.get("data") or []
            if data and data[0].get("url"):
                return data[0]["url"]
            code = data[0].get("code") if data else None
            if code == -110:
                # 无版权/需要会员，换音质也没用，直接快速失败
                raise RuntimeError("该曲目版权受限，当前账号无法播放")
            if code == 404:
                raise RuntimeError("该曲目已下架，无法播放")
            reasons.append("该曲目暂无可播放地址")
        raise RuntimeError("；".join(dict.fromkeys(reasons)) or "该曲目暂无可播放地址")


music = MusicService()
