"""
网易云账号扫码登录（仅供本地使用）
================================
用途：登录后服务端才能取到完整歌单（未登录只有前 10 首）。

安全约定
--------
- 凭据只写入 eeg-focus/data/music_cookie.txt，而 data/ 已在 .gitignore 中
- 脚本不回显 cookie，不打印账号昵称等个人信息
- 二维码通过本机 127.0.0.1 临时端口提供，登录结束即关闭
- 不要手动把该文件内容复制到任何源码、文档或 issue 中

用法
----
  python scripts/ncm_login.py            # 扫码登录并保存
  python scripts/ncm_login.py --check    # 检查已保存凭据是否有效
  python scripts/ncm_login.py --logout   # 删除本地凭据
"""

import argparse
import http.server
import json
import os
import pathlib
import sys
import threading
import time
import urllib.request

BASE = "https://music.163.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

HERE = pathlib.Path(__file__).resolve().parent
DATA_DIR = HERE.parent / "data"
COOKIE_FILE = DATA_DIR / "music_cookie.txt"
QR_DIR = HERE.parent.parent / ".deepworks" / "tmp" / "ncm_login"


def log(msg: str) -> None:
    path = os.environ.get("NCM_LOG_FILE")
    if path:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except OSError:
            pass
    try:
        print(msg, flush=True)
    except Exception:
        pass


def _request_json(url: str, cookie: str = "", timeout: float = 12.0) -> dict:
    headers = {"User-Agent": UA, "Referer": BASE + "/"}
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


# --------------------------------------------------------------------------
# 二维码静态服务：只暴露二维码文件，避免把 data/ 目录整体暴露出去
# --------------------------------------------------------------------------
class _QrHandler(http.server.BaseHTTPRequestHandler):
    svg_path = None

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path in ("/", "/qr"):
            body = _QR_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if path != "/qr.svg":
            self.send_error(404)
            return
        try:
            body = type(self).svg_path.read_bytes()
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # 静默
        pass


_QR_HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>网易云扫码登录</title>
<style>
  html,body{height:100%;margin:0}
  body{display:grid;place-items:center;background:#f4f8f9;
       font-family:-apple-system,"Microsoft YaHei",sans-serif;color:#22333b}
  .card{background:#fff;border-radius:26px;padding:28px 30px 24px;text-align:center;
        box-shadow:0 18px 48px rgba(47,110,128,.16);border:1px solid #e6f0f2}
  h1{margin:0 0 6px;font-size:20px;letter-spacing:.5px}
  p{margin:0 0 16px;color:#63787f;font-size:13.5px}
  img{width:272px;height:272px;display:block;margin:0 auto;border-radius:14px;background:#fff}
  .hint{margin-top:16px;font-size:12.5px;color:#8aa0a6}
</style></head>
<body><div class="card">
  <h1>网易云扫码登录</h1>
  <p>用网易云 App 扫码，并在手机上点「确认登录」</p>
  <img id="qr" src="/qr.svg" alt="登录二维码">
  <p class="hint">二维码过期会自动刷新；凭据仅保存在本机</p>
</div>
<script>
  setInterval(function () {
    document.getElementById('qr').src = '/qr.svg?t=' + Date.now();
  }, 4000);
</script>
</body></html>
"""


def _start_qr_server(svg_path: pathlib.Path):
    _QrHandler.svg_path = svg_path
    for port in (8891, 8892, 8893, 8894):
        try:
            httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), _QrHandler)
        except OSError:
            continue
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        return httpd, port
    raise RuntimeError("本机 8891-8894 端口都被占用，无法提供二维码")


def _make_qr(text: str, svg_path: pathlib.Path) -> None:
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(
        text,
        image_factory=qrcode.image.svg.SvgPathImage,
        box_size=10,
        border=2,
    )
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(svg_path))


# --------------------------------------------------------------------------
# 凭据读写
# --------------------------------------------------------------------------
def _normalize_cookie(raw: str) -> str:
    parts = []
    for seg in raw.split(";"):
        seg = seg.strip()
        if not seg or "=" not in seg:
            continue
        k, _, v = seg.partition("=")
        k = k.strip()
        if not k or k.lower() in ("path", "domain", "expires", "max-age",
                                 "httponly", "secure", "samesite"):
            continue
        parts.append(f"{k}={v.strip()}")
    return "; ".join(parts)


def _save_cookie(raw: str) -> pathlib.Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cookie = _normalize_cookie(raw)
    COOKIE_FILE.write_text(cookie + "\n", encoding="utf-8")
    try:  # 尽力限制为当前用户可读（Windows 上通常为空操作）
        os.chmod(COOKIE_FILE, 0o600)
    except OSError:
        pass
    return COOKIE_FILE


def _load_cookie() -> str:
    try:
        return COOKIE_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _check_cookie(cookie: str) -> bool:
    if not cookie:
        return False
    try:
        j = _request_json(BASE + "/api/nuser/account/get", cookie)
    except Exception:
        return False
    return j.get("code") == 200 and bool(j.get("account"))


def _refresh_local_api() -> None:
    """登录后通知本地服务重建歌单缓存（失败不影响登录结果）。"""
    api = os.environ.get("NCM_API", "http://127.0.0.1:8000")
    try:
        with urllib.request.urlopen(api + "/api/music/playlist?refresh=1", timeout=60) as r:
            data = json.loads(r.read().decode("utf-8", "ignore"))
        log(f"API_REFRESHED: 服务端已重建歌单缓存（{data.get('count', '?')} 首）")
    except Exception as e:
        log(f"API_REFRESH_SKIP: {e}")


# --------------------------------------------------------------------------
# 登录主流程
# --------------------------------------------------------------------------
def _new_key(svg_path: pathlib.Path) -> str:
    j = _request_json(BASE + "/api/login/qrcode/unikey?type=1")
    key = j.get("unikey")
    if not key:
        raise RuntimeError("无法获取登录二维码 key")
    _make_qr(f"{BASE}/login?codekey={key}", svg_path)
    return key


def login(timeout: float = 600.0) -> int:
    svg_path = QR_DIR / "qr.svg"
    try:
        key = _new_key(svg_path)
    except Exception as e:
        log(f"LOGIN_FAIL: 生成登录二维码失败 {e}")
        return 2

    httpd = None
    try:
        httpd, port = _start_qr_server(svg_path)
        log(f"QR_URL: http://127.0.0.1:{port}/qr")
        log("等待手机扫码并在 App 内确认登录…")

        deadline = time.time() + timeout
        last_code = None
        while time.time() < deadline:
            time.sleep(2.0)
            try:
                r = _request_json(f"{BASE}/api/login/qrcode/client/login?key={key}&type=1")
            except Exception:
                continue
            code = r.get("code")

            if code == 800:  # 过期，自动换一张新码
                log("STATUS: 二维码过期，已自动换新")
                try:
                    key = _new_key(svg_path)
                except Exception as e:
                    log(f"LOGIN_FAIL: 刷新二维码失败 {e}")
                    return 2
                last_code = None
                continue

            if code != last_code:
                last_code = code
                if code == 801:
                    log("STATUS: 等待扫码")
                elif code == 802:
                    log("STATUS: 已扫码，请在手机上确认")

            if code == 803:
                raw = r.get("cookie") or ""
                if not raw:
                    log("LOGIN_FAIL: 登录成功但未返回凭据")
                    return 2
                path = _save_cookie(raw)
                log(f"SAVED: {path}")
                if _check_cookie(_load_cookie()):
                    log("LOGIN_OK")
                    _refresh_local_api()
                    return 0
                log("LOGIN_WARN: 凭据已保存，但校验未通过")
                return 4
        log("LOGIN_TIMEOUT: 等待超时，请重新运行脚本")
        return 3
    finally:
        if httpd:
            httpd.shutdown()


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="网易云扫码登录（凭据仅保存在本机）")
    ap.add_argument("--check", action="store_true", help="检查已保存凭据是否有效")
    ap.add_argument("--logout", action="store_true", help="删除本地保存的凭据")
    ap.add_argument("--timeout", type=float, default=1800.0, help="等待扫码的秒数")
    args = ap.parse_args()

    if args.logout:
        if COOKIE_FILE.exists():
            COOKIE_FILE.unlink()
            log("已删除本地凭据文件")
        else:
            log("本地没有凭据文件")
        return 0

    if args.check:
        if not COOKIE_FILE.exists():
            log("CHECK: 尚未登录（没有本地凭据）")
            return 1
        ok = _check_cookie(_load_cookie())
        log("CHECK: 凭据有效" if ok else "CHECK: 凭据已失效，请重新登录")
        return 0 if ok else 1

    return login(args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
