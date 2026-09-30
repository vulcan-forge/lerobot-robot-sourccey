"""Zero-install web dashboard for live LD19 scan visualization."""

from __future__ import annotations

import argparse
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .ld19 import DEFAULT_BAUDRATE, DEFAULT_DEVICE
from .monitor import LidarMonitor

DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Sourccey LiDAR</title>
  <style>
    :root{color-scheme:dark;--bg:#090d12;--panel:#111820;--line:#263442;--muted:#8ea1b2;--text:#edf5fb;--cyan:#44d7e8;--green:#50dc8d;--red:#ff667a}
    *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px system-ui,sans-serif}
    header{height:64px;display:flex;align-items:center;justify-content:space-between;padding:0 22px;border-bottom:1px solid var(--line)}
    h1{font-size:18px;margin:0;letter-spacing:.02em}small,.muted{color:var(--muted)}
    #state{font-weight:700;padding:7px 11px;border:1px solid currentColor;border-radius:999px}.good{color:var(--green)}.bad{color:var(--red)}
    main{display:grid;grid-template-columns:minmax(0,1fr) 280px;gap:16px;padding:16px;height:calc(100vh - 64px)}
    .plot,.side{background:var(--panel);border:1px solid var(--line);border-radius:12px}.plot{position:relative;overflow:hidden;min-height:420px}
    canvas{width:100%;height:100%;display:block}.legend{position:absolute;left:14px;bottom:12px;color:var(--muted)}
    .side{padding:16px;overflow:auto}.section{border-bottom:1px solid var(--line);padding:0 0 15px;margin:0 0 15px}.section:last-child{border:0}
    h2{font-size:12px;text-transform:uppercase;color:var(--muted);letter-spacing:.12em;margin:0 0 12px}
    dl{display:grid;grid-template-columns:1fr auto;gap:9px;margin:0}dt{color:var(--muted)}dd{margin:0;font-variant-numeric:tabular-nums}
    label{display:flex;justify-content:space-between;color:var(--muted)}input{width:100%;margin-top:9px;accent-color:var(--cyan)}
    @media(max-width:760px){main{grid-template-columns:1fr;height:auto}.plot{height:65vh}.side{min-height:0}}
  </style>
</head>
<body>
<header><div><h1>Sourccey 2D LiDAR</h1><small>LDROBOT LD19 · live clockwise scan</small></div><span id="state" class="bad">STARTING</span></header>
<main>
  <section class="plot"><canvas id="plot"></canvas><div class="legend">▲ robot front / 0°</div></section>
  <aside class="side">
    <div class="section"><h2>Scan</h2><dl><dt>Rotation</dt><dd id="hz">--</dd><dt>Valid points</dt><dd id="points">--</dd><dt>Nearest</dt><dd id="near">--</dd><dt>Farthest</dt><dd id="far">--</dd><dt>Data age</dt><dd id="age">--</dd></dl></div>
    <div class="section"><h2>Connection</h2><dl><dt>Device</dt><dd id="device">--</dd><dt>Baud</dt><dd id="baud">--</dd><dt>Scans</dt><dd id="scans">--</dd><dt>Packets</dt><dd id="packets">--</dd><dt>CRC errors</dt><dd id="crc">--</dd></dl></div>
    <div class="section"><h2>Display range</h2><label><span>Maximum</span><span id="rangeLabel">12 m</span></label><input id="range" type="range" min="1" max="12" step="1" value="12"></div>
    <div class="section"><h2>Status</h2><div id="message" class="muted">Waiting for serial data…</div></div>
  </aside>
</main>
<script>
const canvas=document.querySelector('#plot'),ctx=canvas.getContext('2d'),range=document.querySelector('#range');let points=[];
const $=id=>document.getElementById(id),fmt=(v,n=2)=>v==null?'--':Number(v).toFixed(n);
range.oninput=()=>{$('rangeLabel').textContent=range.value+' m';draw()};
function resize(){const d=devicePixelRatio||1,r=canvas.getBoundingClientRect();canvas.width=r.width*d;canvas.height=r.height*d;ctx.setTransform(d,0,0,d,0,0);draw()}addEventListener('resize',resize);
function draw(){const w=canvas.clientWidth,h=canvas.clientHeight,cx=w/2,cy=h/2,max=+range.value,rad=Math.max(20,Math.min(w,h)*.44);ctx.clearRect(0,0,w,h);ctx.strokeStyle='#263442';ctx.fillStyle='#8ea1b2';ctx.lineWidth=1;ctx.font='11px system-ui';for(let i=1;i<=4;i++){let r=rad*i/4;ctx.beginPath();ctx.arc(cx,cy,r,0,Math.PI*2);ctx.stroke();ctx.fillText((max*i/4).toFixed(0)+'m',cx+4,cy-r+13)}ctx.beginPath();ctx.moveTo(cx-rad,cy);ctx.lineTo(cx+rad,cy);ctx.moveTo(cx,cy-rad);ctx.lineTo(cx,cy+rad);ctx.stroke();ctx.fillStyle='#50dc8d';ctx.beginPath();ctx.moveTo(cx,cy-10);ctx.lineTo(cx-5,cy+6);ctx.lineTo(cx+5,cy+6);ctx.fill();for(const p of points){if(p[1]<=0||p[1]>max)continue;const a=p[0]*Math.PI/180,r=p[1]/max*rad,x=cx+Math.sin(a)*r,y=cy-Math.cos(a)*r,intensity=Math.max(.2,p[2]/255);ctx.fillStyle=`rgba(68,215,232,${intensity})`;ctx.fillRect(x-1.5,y-1.5,3,3)}}
async function update(){try{const r=await fetch('/api/state',{cache:'no-store'}),s=await r.json();points=s.scan?.points||[];$('state').textContent=s.healthy?'HEALTHY':(s.connected?'WAITING':'DISCONNECTED');$('state').className=s.healthy?'good':'bad';$('hz').textContent=fmt(s.rotation_hz)+' Hz';$('points').textContent=s.valid_point_count+' / '+s.point_count;$('near').textContent=fmt(s.minimum_distance_m)+' m';$('far').textContent=fmt(s.maximum_distance_m)+' m';$('age').textContent=fmt(s.data_age_s)+' s';$('device').textContent=s.device;$('baud').textContent=s.baudrate.toLocaleString();$('scans').textContent=s.scan_count;$('packets').textContent=s.packet_count;$('crc').textContent=s.crc_error_count+' ('+fmt(s.crc_error_percent)+'%)';$('message').textContent=s.error||(!s.scan?'Waiting for one complete revolution…':'Receiving valid LD19 data.');draw()}catch(e){$('state').textContent='INTERFACE ERROR';$('state').className='bad';$('message').textContent=e.message}}
resize();update();setInterval(update,100);
</script>
</body></html>"""


def _make_handler(monitor: LidarMonitor) -> type[BaseHTTPRequestHandler]:
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/" or self.path == "/index.html":
                self._send(DASHBOARD_HTML.encode(), "text/html; charset=utf-8")
                return
            if self.path == "/api/state":
                state = monitor.snapshot()
                state.update(monitor.scan_payload())
                self._send(json.dumps(state, separators=(",", ":")).encode(), "application/json")
                return
            self.send_error(404)

        def _send(self, body: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, format: str, *args: object) -> None:
            return

    return DashboardHandler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Visualize the Sourccey LD19 in a web browser")
    parser.add_argument("--device", default=DEFAULT_DEVICE, help=f"Serial device (default: {DEFAULT_DEVICE})")
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("--host", default="127.0.0.1", help="Dashboard bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Dashboard port (default: 8765)")
    parser.add_argument("--open-browser", action="store_true", help="Open the dashboard in the local browser")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not 1 <= args.port <= 65_535:
        raise SystemExit("--port must be between 1 and 65535")
    monitor = LidarMonitor(args.device, baudrate=args.baudrate)
    server = ThreadingHTTPServer((args.host, args.port), _make_handler(monitor))
    server.daemon_threads = True
    display_host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    url = f"http://{display_host}:{server.server_port}"
    monitor.start()
    print(f"Sourccey LiDAR dashboard: {url}")
    print("Press Ctrl+C to stop.")
    if args.open_browser:
        threading.Timer(0.2, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nStopping LiDAR dashboard.")
    finally:
        server.server_close()
        monitor.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

