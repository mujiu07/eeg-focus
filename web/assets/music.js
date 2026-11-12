/*
 * 黑胶唱片机背景音乐播放器（全站共用）
 * ------------------------------------
 * - 结构由本脚本注入，各页面只需引入 assets/vinyl.css + assets/music.js
 * - 交互：唱臂落下 = 播放；唱臂抬起 = 暂停并保留进度，再落下从原位置继续
 *         点击唱片 = 同样切换；左右箭头 = 上一首 / 下一首
 * - 曲目顺序来自 /api/music/playlist，直链来自 /api/music/url/{id}
 * - 页面间记住当前曲目与播放位置，进入新页面可接着放
 */
(function () {
  "use strict";

  const IDX_KEY = "bf-music-index";
  const ON_KEY = "bf-music-on";
  const STATE_KEY = "bf-music-state";   // { i: 曲目序号, t: 秒, p: 是否在播放 }
  const URL_LIMIT = 12;                // 连续取直链失败的最大跳曲次数

  // ---------- 注入样式与结构 ----------
  function ensureCss() {
    const found = document.querySelector('link[href*="vinyl.css"]');
    if (found) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "assets/vinyl.css";
    document.head.appendChild(link);
  }

  function mount() {
    const old = document.getElementById("vinyl-player");
    if (old) old.remove();

    const box = document.createElement("div");
    box.className = "vinyl-player";
    box.id = "vinyl-player";
    box.setAttribute("aria-label", "背景音乐控制");
    box.innerHTML = [
      '<button type="button" class="vinyl-nav" id="music-prev" title="上一首" aria-label="上一首歌曲">',
      '  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 5 8 12l7 7" /></svg>',
      "</button>",
      '<div class="vinyl-deck">',
      '  <button type="button" class="vinyl-disc-btn" id="vinyl-toggle" aria-pressed="false"',
      '          aria-label="播放音乐" title="点击唱片播放">',
      '    <span class="vinyl-disc" aria-hidden="true">',
      '      <span class="vinyl-label">♪</span>',
      '      <span class="vinyl-hole"></span>',
      "    </span>",
      "  </button>",
      '  <button type="button" class="vinyl-arm" id="music-arm" aria-pressed="false"',
      '          aria-label="放下唱臂播放音乐" title="放下唱臂播放"></button>',
      '  <span class="vinyl-pivot" aria-hidden="true"></span>',
      '  <span class="vinyl-notes" aria-hidden="true"><i>♪</i><i>♫</i><i>♪</i></span>',
      '  <span class="vinyl-loading" aria-hidden="true"></span>',
      "</div>",
      '<button type="button" class="vinyl-nav" id="music-next" title="下一首" aria-label="下一首歌曲">',
      '  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 5l7 7-7 7" /></svg>',
      "</button>",
      '<div class="vinyl-meta">',
      '  <div class="vinyl-title" id="music-title">专注歌单</div>',
      '  <div class="vinyl-sub" id="music-sub">放下唱臂播放</div>',
      "</div>",
    ].join("\n");
    document.body.appendChild(box);
    return box;
  }

  function boot() {
    ensureCss();
    const root = mount();

    const discBtn = document.getElementById("vinyl-toggle");
    const armBtn = document.getElementById("music-arm");
    const prevBtn = document.getElementById("music-prev");
    const nextBtn = document.getElementById("music-next");
    const titleEl = document.getElementById("music-title");
    const subEl = document.getElementById("music-sub");

    const audio = new Audio();
    audio.preload = "auto";
    audio.volume = 0.35;

    let tracks = null;
    let index = 0;
    let loadedIndex = -1;     // audio.src 当前对应的曲目，-1 表示未装载
    let pendingSeek = null;   // 装载完成后要跳转到的秒数
    let playing = false;
    let busy = false;
    let status = "";
    let errRetry = 0;
    const urlCache = new Map();

    // ---------- 基础工具 ----------
    async function getJSON(url) {
      const res = await fetch(url, { headers: { Accept: "application/json" } });
      if (!res.ok) {
        let msg = res.statusText || ("HTTP " + res.status);
        try {
          const e = await res.json();
          if (e && e.detail) msg = e.detail;
        } catch (_) { /* 忽略非 JSON 错误体 */ }
        throw new Error(msg);
      }
      return res.json();
    }

    function setText(el, text) {
      if (el && el.textContent !== text) el.textContent = text;
    }

    function wrap(i) {
      const n = tracks ? tracks.length : 0;
      if (!n) return 0;
      return ((i % n) + n) % n;
    }

    function shortMsg(msg) {
      const s = String(msg || "未知错误").replace(/\s+/g, " ").trim();
      return s.length > 42 ? s.slice(0, 42) + "…" : s;
    }

    let flashTimer = null;
    function flashStatus(text, ms) {
      status = text;
      refreshMeta();
      clearTimeout(flashTimer);
      flashTimer = setTimeout(() => {
        if (status === text) {
          status = "";
          refreshMeta();
        }
      }, ms || 2400);
    }

    // 暂停时展示"继续"的提示，强调可以从原位置接着放
    function subText(track) {
      if (status) return status;
      if (!track) return "放下唱臂播放";
      if (!playing && (audio.currentTime || 0) > 0.5) return "已暂停 · 落下唱臂继续";
      return (index + 1) + "/" + tracks.length + " · " + (track.artists || "未知");
    }

    function refreshMeta() {
      const t = tracks && tracks[index];
      setText(titleEl, t ? t.name : "专注歌单");
      if (titleEl) titleEl.title = t ? t.name + " · " + (t.artists || "") : "";
      if (subEl) {
        setText(subEl, subText(t));
        subEl.classList.toggle("is-error", !!status);
      }
    }

    function syncUI() {
      root.classList.toggle("is-playing", playing);
      root.classList.toggle("is-busy", busy);

      discBtn.setAttribute("aria-pressed", playing ? "true" : "false");
      discBtn.setAttribute("aria-label", playing ? "暂停音乐" : "播放音乐");
      discBtn.title = busy ? "音乐加载中…" : (playing ? "点击唱片暂停" : "点击唱片播放");

      armBtn.setAttribute("aria-pressed", playing ? "true" : "false");
      armBtn.setAttribute("aria-label", playing ? "抬起唱臂暂停音乐" : "放下唱臂播放音乐");
      armBtn.title = busy ? "音乐加载中…" : (playing ? "抬起唱臂暂停" : "放下唱臂播放");

      const single = !tracks || tracks.length < 2;
      prevBtn.disabled = single;
      nextBtn.disabled = single;
    }

    // ---------- 播放位置记忆 ----------
    function readState() {
      try {
        const raw = localStorage.getItem(STATE_KEY);
        if (!raw) return null;
        const obj = JSON.parse(raw);
        return obj && typeof obj === "object" ? obj : null;
      } catch (_) {
        return null;
      }
    }

    function saveState() {
      try {
        localStorage.setItem(STATE_KEY, JSON.stringify({
          i: index,
          t: Math.max(0, audio.currentTime || 0),
          p: playing ? 1 : 0,
        }));
      } catch (_) { /* 存储不可用时忽略 */ }
    }

    // ---------- 数据 ----------
    async function ensureTracks() {
      if (tracks) return tracks;
      status = "歌单加载中…";
      refreshMeta();
      const data = await getJSON("/api/music/playlist");
      const list = (data.tracks || []).filter(t => t && t.id != null);
      if (!list.length) throw new Error("歌单里没有可播放曲目");
      tracks = list;
      const saved = parseInt(localStorage.getItem(IDX_KEY) || "0", 10);
      index = Number.isFinite(saved) ? Math.min(Math.max(saved, 0), tracks.length - 1) : 0;
      status = "";
      return tracks;
    }

    function prefetch(i) {
      if (!tracks || !tracks.length) return;
      const t = tracks[wrap(i)];
      if (!t) return;
      const key = String(t.id);
      if (urlCache.has(key)) return;
      getJSON("/api/music/url/" + encodeURIComponent(t.id))
        .then(u => { if (u && u.url) urlCache.set(key, u.url); })
        .catch(() => { /* 预取失败不影响主流程 */ });
    }

    async function resolveUrl(track) {
      const key = String(track.id);
      const cached = urlCache.get(key);
      if (cached) return cached;
      const data = await getJSON("/api/music/url/" + encodeURIComponent(track.id));
      if (!data || !data.url) throw new Error("该曲目暂无播放地址");
      urlCache.set(key, data.url);
      return data.url;
    }

    async function loadTrack(i, seekTo) {
      index = wrap(i);
      localStorage.setItem(IDX_KEY, String(index));
      refreshMeta();
      const track = tracks[index];
      const url = await resolveUrl(track);
      pendingSeek = typeof seekTo === "number" && seekTo > 0.3 ? seekTo : null;
      audio.src = url;
      loadedIndex = index;
      audio.load();
      prefetch(index + 1);
    }

    // ---------- 播放控制 ----------
    // 唱臂落下 / 点击唱片：播放；若当前曲目已装载则从暂停处继续
    async function start() {
      if (busy) return;
      busy = true;
      status = "";
      syncUI();
      refreshMeta();
      try {
        await ensureTracks();
        if (loadedIndex !== index || !audio.src) {
          await loadTrack(index, pendingSeek);
        }
        await audio.play();
        playing = true;
        errRetry = 0;
        localStorage.setItem(ON_KEY, "1");
        saveState();
      } catch (e) {
        playing = false;
        status = "播放失败：" + shortMsg(e.message);
        console.warn("[music] 播放失败", e);
      } finally {
        busy = false;
        syncUI();
        refreshMeta();
      }
    }

    // 唱臂抬起：暂停，保留 currentTime，下次落下接着放
    function pause() {
      audio.pause();
      playing = false;
      localStorage.setItem(ON_KEY, "0");
      status = "";
      syncUI();
      refreshMeta();
      saveState();
    }

    function toggle() {
      if (busy) return;
      if (playing) pause();
      else start();
    }

    // 播放中某首拿不到直链时，顺着方向自动跳过，最多 URL_LIMIT 次
    async function advance(i, dir, depth) {
      const guard = depth || 0;
      if (guard >= URL_LIMIT) {
        playing = false;
        status = "连续多首暂时无法播放";
        syncUI();
        refreshMeta();
        return;
      }
      try {
        await loadTrack(i);
        await audio.play();
        playing = true;
        errRetry = 0;
        saveState();
      } catch (e) {
        console.warn("[music] 跳过无法播放的曲目", tracks[wrap(i)] && tracks[wrap(i)].name, e);
        await advance(wrap(i) + dir, dir, guard + 1);
      }
    }

    async function step(dir) {
      if (busy) return;
      if (!tracks) {
        try { await ensureTracks(); }
        catch (e) { status = "歌单加载失败"; syncUI(); refreshMeta(); return; }
      }
      const keepPlaying = playing || localStorage.getItem(ON_KEY) === "1";
      if (!keepPlaying) {
        // 暂停状态切歌：只换曲目，不开始播放
        index = wrap(index + dir);
        localStorage.setItem(IDX_KEY, String(index));
        loadedIndex = -1;
        pendingSeek = null;
        status = "";
        refreshMeta();
        syncUI();
        prefetch(index);
        saveState();
        return;
      }
      busy = true;
      status = "";
      syncUI();
      try {
        await advance(index + dir, dir, 0);
      } finally {
        busy = false;
        syncUI();
        refreshMeta();
      }
    }

    // ---------- 事件 ----------
    discBtn.addEventListener("click", toggle);
    armBtn.addEventListener("click", toggle);
    [discBtn, armBtn].forEach(btn => {
      btn.addEventListener("keydown", e => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          toggle();
        }
      });
    });
    prevBtn.addEventListener("click", () => step(-1));
    nextBtn.addEventListener("click", () => step(1));

    // 装载完成后跳到记忆中的播放位置
    audio.addEventListener("loadedmetadata", () => {
      if (pendingSeek == null) return;
      const target = pendingSeek;
      pendingSeek = null;
      const dur = audio.duration;
      const t = Number.isFinite(dur) && dur > 1 ? Math.min(target, dur - 0.4) : target;
      if (t > 0.3) {
        try { audio.currentTime = t; } catch (_) { /* 忽略 seek 失败 */ }
      }
    });

    let lastSave = 0;
    audio.addEventListener("timeupdate", () => {
      const now = Date.now();
      if (now - lastSave > 1000) {
        lastSave = now;
        saveState();
      }
    });

    audio.addEventListener("ended", () => {
      if (!playing) return;
      errRetry = 0;
      step(1);
    });

    audio.addEventListener("error", () => {
      if (!audio.src || !playing || busy) return;
      const track = tracks && tracks[index];
      console.warn("[music] 音频加载失败", audio.src);
      // 直链有时效，先清缓存重取一次，仍失败才跳到下一首
      if (track && errRetry === 0) {
        errRetry += 1;
        urlCache.delete(String(track.id));
        loadTrack(index)
          .then(() => audio.play())
          .catch(() => { errRetry = 0; advance(index + 1, 1, 0).then(() => { syncUI(); refreshMeta(); }); });
        return;
      }
      errRetry = 0;
      advance(index + 1, 1, 0).then(() => { syncUI(); refreshMeta(); });
    });

    // 离开页面前记住位置并停止音频，避免后台继续播放
    window.addEventListener("pagehide", () => {
      saveState();
      audio.pause();
    });

    // ---------- 启动 ----------
    syncUI();
    refreshMeta();

    // 页面空闲时静默预取；若有上次的播放位置，装载好等用户落针继续
    setTimeout(async () => {
      try {
        await ensureTracks();
        const st = readState();
        if (st && Number.isFinite(st.i) && st.i >= 0 && st.i < tracks.length) {
          index = st.i;
          localStorage.setItem(IDX_KEY, String(index));
        }
        refreshMeta();
        syncUI();
        prefetch(index);
        prefetch(index + 1);

        if (st && Number(st.t) > 1) {
          await loadTrack(index, Number(st.t));
          refreshMeta();
          if (st.p === 1) {
            // 浏览器可能拦截无手势的自动播放，失败就保持抬起唱臂状态
            try {
              await audio.play();
              playing = true;
              saveState();
            } catch (_) {
              playing = false;
            }
            syncUI();
            refreshMeta();
          }
        }
      } catch (e) {
        // 首次自动预取失败不打扰用户，点击时再重试并展示原因
        console.info("[music] 预取歌单失败：", e.message);
      }
    }, 900);

    // 供其它脚本查询状态（可选）
    window.vinylPlayer = {
      toggle,
      next: () => step(1),
      prev: () => step(-1),
      debugTime: () => ({ t: Math.round((audio.currentTime || 0) * 100) / 100, playing }),
    };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
