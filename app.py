"""Personal file transfer station.

HTTP Basic Auth: empty username + password from FILE_PASSWORD env var.
Uploads are chunked (768KB per request) because the hosting ingress caps a
single request body at ~1MB. Downloads have no such cap.
"""
import html
import os
import re
import shutil
from datetime import datetime
from urllib.parse import quote

from flask import Flask, Response, abort, jsonify, redirect, request, send_file

BASE = os.path.dirname(os.path.abspath(__file__))
FILES_DIR = os.path.join(BASE, "files")
PARTS_DIR = os.path.join(BASE, ".parts")
PASSWORD = os.environ.get("FILE_PASSWORD", "")
CHUNK_SIZE = 768 * 1024

os.makedirs(FILES_DIR, exist_ok=True)
os.makedirs(PARTS_DIR, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024


def authed():
    a = request.authorization
    return (
        bool(PASSWORD)
        and a is not None
        and a.username in ("", None)
        and a.password == PASSWORD
    )


@app.before_request
def gate():
    if not authed():
        return Response(
            "Unauthorized", 401, {"WWW-Authenticate": 'Basic realm="file-station"'}
        )


def safe_name(name):
    name = (name or "").strip().replace("\\", "/").split("/")[-1].strip()
    name = re.sub(r'[\x00-\x1f:*?"<>|]', "_", name).strip(". ")
    return name or None


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>文件中转站</title>
<style>
body{font-family:system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;max-width:900px;margin:24px auto;padding:0 16px;color:#222}
h1{font-size:22px}table{width:100%;border-collapse:collapse;margin-top:12px}
th,td{border-bottom:1px solid #ddd;padding:8px 6px;text-align:left;font-size:14px}
th{color:#666;font-weight:600}.num{text-align:right;white-space:nowrap}
#barwrap{height:10px;background:#eee;border-radius:5px;margin-top:10px;overflow:hidden}
#bar{height:100%;width:0;background:#2f80ed}
#status{font-size:14px;color:#555;margin-top:6px;min-height:20px}
button{cursor:pointer}input[type=file]{max-width:100%}
.note{font-size:13px;color:#888;margin-top:8px}
.del{background:none;border:none;color:#c00;font-size:14px;padding:0}
</style></head><body>
<h1>文件中转站</h1>
<form id="up">
<input type="file" id="file" required>
<button type="submit">上传</button>
<div id="barwrap"><div id="bar"></div></div>
<div id="status"></div>
</form>
<p class="note">大文件自动分片上传，不限大小；下载点文件名直链。</p>
<table><thead><tr><th>文件名</th><th class="num">大小</th><th>修改时间</th><th></th></tr></thead>
<tbody>__ROWS__</tbody></table>
<script>
document.getElementById('up').addEventListener('submit', async function(ev){
  ev.preventDefault();
  var f = document.getElementById('file').files[0];
  if(!f) return;
  var CHUNK = 768*1024, total = Math.max(1, Math.ceil(f.size/CHUNK));
  var id = Date.now().toString(36) + Math.random().toString(36).slice(2,8);
  var bar = document.getElementById('bar'), st = document.getElementById('status');
  var btn = ev.target.querySelector('button'); btn.disabled = true;
  for(var i=0;i<total;i++){
    var fd = new FormData();
    fd.append('chunk', f.slice(i*CHUNK,(i+1)*CHUNK), 'chunk.bin');
    fd.append('upload_id', id); fd.append('index', i);
    fd.append('total', total); fd.append('filename', f.name);
    var ok = false;
    for(var a=0;a<3 && !ok;a++){
      try{ var r = await fetch('/chunk',{method:'POST',body:fd,credentials:'same-origin'}); ok = r.ok; }
      catch(e){ ok = false; }
    }
    if(!ok){ st.textContent = '上传失败（分片 '+(i+1)+'/'+total+'），请重试'; btn.disabled=false; return; }
    bar.style.width = ((i+1)/total*100)+'%';
    st.textContent = '上传中 '+(i+1)+'/'+total;
  }
  st.textContent = '上传完成';
  location.reload();
});
</script>
</body></html>
"""


@app.route("/")
def index():
    rows = []
    for name in sorted(os.listdir(FILES_DIR)):
        path = os.path.join(FILES_DIR, name)
        if not os.path.isfile(path):
            continue
        st = os.stat(path)
        mtime = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
        rows.append(
            f'<tr><td><a href="/d/{quote(name)}">{html.escape(name)}</a></td>'
            f'<td class="num">{human(st.st_size)}</td><td>{mtime}</td>'
            f'<td><form method="post" action="/delete" style="display:inline">'
            f'<input type="hidden" name="name" value="{html.escape(name, quote=True)}">'
            f'<button class="del" type="submit">删除</button></form></td></tr>'
        )
    return PAGE.replace(
        "__ROWS__", "\n".join(rows) if rows else '<tr><td colspan="4">空</td></tr>'
    )


@app.route("/d/<path:name>")
def download(name):
    safe = safe_name(name)
    if not safe:
        abort(404)
    path = os.path.join(FILES_DIR, safe)
    if not os.path.isfile(path):
        abort(404)
    return send_file(
        path,
        as_attachment=True,
        download_name=safe,
        mimetype="application/octet-stream",
        conditional=True,
        max_age=0,
    )


@app.route("/upload", methods=["POST"])
def upload_small():
    """Single-request upload; only usable for files under the ingress ~1MB cap."""
    f = request.files.get("file")
    if f is None:
        abort(400)
    name = safe_name(f.filename)
    if not name:
        abort(400)
    f.save(os.path.join(FILES_DIR, name))
    return redirect("/")


@app.route("/chunk", methods=["POST"])
def upload_chunk():
    uid = request.form.get("upload_id", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", uid):
        abort(400)
    try:
        index = int(request.form.get("index", ""))
        total = int(request.form.get("total", ""))
    except ValueError:
        abort(400)
    if not (0 <= index < total <= 100000):
        abort(400)
    name = safe_name(request.form.get("filename", ""))
    if not name:
        abort(400)
    f = request.files.get("chunk")
    if f is None:
        abort(400)
    part_dir = os.path.join(PARTS_DIR, uid)
    os.makedirs(part_dir, exist_ok=True)
    f.save(os.path.join(part_dir, f"{index:06d}.part"))
    parts = [p for p in os.listdir(part_dir) if p.endswith(".part")]
    if len(parts) == total:
        dest = os.path.join(FILES_DIR, name)
        tmp = dest + ".assembling"
        try:
            with open(tmp, "wb") as out:
                for i in range(total):
                    part = os.path.join(part_dir, f"{i:06d}.part")
                    if not os.path.exists(part):
                        abort(409)
                    with open(part, "rb") as pf:
                        shutil.copyfileobj(pf, out)
            os.replace(tmp, dest)
        finally:
            shutil.rmtree(part_dir, ignore_errors=True)
            if os.path.exists(tmp):
                os.unlink(tmp)
        return jsonify(ok=True, done=True)
    return jsonify(ok=True, done=False)


@app.route("/delete", methods=["POST"])
def delete():
    name = safe_name(request.form.get("name", ""))
    if name:
        path = os.path.join(FILES_DIR, name)
        if os.path.isfile(path):
            os.unlink(path)
    return redirect("/")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "9090")), threaded=True)
