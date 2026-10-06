#!/usr/bin/env python3
"""Build tài liệu: render Mermaid -> PNG, compile xelatex 2 lần, soát log, dọn file phụ.

    python build.py                  # build bình thường (chỉ render lại .mmd đã thay đổi)
    python build.py --force-mermaid  # render lại toàn bộ sơ đồ
    python build.py --mermaid-only   # chỉ render sơ đồ, không compile
    python build.py --keep-aux       # giữ .aux/.log/.toc/.out để debug

Quy ước: mermaid_src/<ten>.mmd  ->  images/<ten>.png  (mmdc -s 2 -b white).
"""
import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAIN = "main"
AUX_EXT = (".aux", ".log", ".out", ".toc", ".lof", ".lot")
# Overfull dưới ~20pt (~0.7cm) thường không thấy bằng mắt -> chỉ báo những cái lớn hơn.
OVERFULL_LIMIT_PT = 20.0

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", **kw)


def render_mermaid(force):
    src_dir, out_dir = ROOT / "mermaid_src", ROOT / "images"
    sources = sorted(src_dir.glob("*.mmd"))

    def stale(src):
        out = out_dir / f"{src.stem}.png"
        return force or not out.exists() or out.stat().st_mtime < src.stat().st_mtime

    todo = [s for s in sources if stale(s)]
    if not todo:
        print(f"[mermaid] {len(sources)} sơ đồ, không có gì thay đổi.")
        return True

    mmdc = shutil.which("mmdc")
    if not mmdc:
        print("[mermaid] LỖI: không tìm thấy mmdc. Cài bằng: "
              "npm install -g @mermaid-js/mermaid-cli", file=sys.stderr)
        return False

    out_dir.mkdir(exist_ok=True)
    ok = True
    for src in todo:
        out = out_dir / f"{src.stem}.png"
        print(f"[mermaid] {src.name} -> images/{out.name}")
        r = run([mmdc, "-i", str(src), "-o", str(out), "-s", "2", "-b", "white"])
        if r.returncode != 0:
            ok = False
            print(f"[mermaid] LỖI khi render {src.name}:\n{r.stdout}{r.stderr}", file=sys.stderr)
    return ok


def read_log():
    log = ROOT / f"{MAIN}.log"
    return log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""


def print_errors(log):
    lines = log.splitlines()
    shown = 0
    for i, line in enumerate(lines):
        if line.startswith("!") or re.match(r"^\S+\.tex:\d+: ", line):
            print("\n".join(lines[i:i + 4]), file=sys.stderr)
            print("-" * 60, file=sys.stderr)
            shown += 1
            if shown >= 5:
                break
    if not shown:
        print("\n".join(lines[-30:]), file=sys.stderr)


def compile_tex():
    xelatex = shutil.which("xelatex")
    if not xelatex:
        print("[xelatex] LỖI: không tìm thấy xelatex (cần MiKTeX/TeX Live).", file=sys.stderr)
        return False
    for i in (1, 2):  # lần 2 để chốt mục lục + tham chiếu chéo
        print(f"[xelatex] Lần {i}/2 ...")
        r = run([xelatex, "-interaction=nonstopmode", "-halt-on-error", "-file-line-error",
                 f"{MAIN}.tex"], cwd=ROOT)
        if r.returncode != 0:
            print(f"[xelatex] LỖI compile (giữ lại {MAIN}.log để xem):", file=sys.stderr)
            print_errors(read_log())
            return False
    return True


def report_warnings(log):
    # Đoán file nguồn cho mỗi cảnh báo: file sections/*.tex được mở gần nhất trước đó trong log.
    opened = [(m.start(), m.group(1))
              for m in re.finditer(r"\((?:\./)?(sections/[^\s()]+\.tex)", log)]

    def near_file(pos):
        name = MAIN + ".tex"
        for p, f in opened:
            if p > pos:
                break
            name = f
        return name

    warnings = []
    for m in re.finditer(r"Overfull \\hbox \(([\d.]+)pt too wide\)([^\n]*)", log):
        if float(m.group(1)) > OVERFULL_LIMIT_PT:
            warnings.append(f"Overfull {float(m.group(1)):.0f}pt{m.group(2)}  [{near_file(m.start())}]")
    # Log ngắt dòng cứng ở cột 79 (kể cả giữa từ) -> bỏ ký tự xuống dòng để ghép lại câu.
    for m in re.finditer(r"LaTeX Warning: (Reference|Label) `([^']+)' (.+?\.)\n", log, re.S):
        detail = m.group(3).replace("\n", "")
        warnings.append(f"{m.group(1)} '{m.group(2)}' {detail}  [{near_file(m.start())}]")

    if warnings:
        print(f"[check] {len(warnings)} cảnh báo cần xem:")
        for w in warnings:
            print("  - " + w)
    else:
        print("[check] Không có tràn lề lớn hay tham chiếu hỏng.")


def clean_aux():
    for ext in AUX_EXT:
        (ROOT / f"{MAIN}{ext}").unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force-mermaid", action="store_true", help="render lại toàn bộ sơ đồ")
    ap.add_argument("--mermaid-only", action="store_true", help="chỉ render sơ đồ, không compile")
    ap.add_argument("--keep-aux", action="store_true", help="giữ file .aux/.log/... sau khi build")
    args = ap.parse_args()

    if not render_mermaid(args.force_mermaid):
        return 1
    if args.mermaid_only:
        return 0
    if not compile_tex():
        return 1

    report_warnings(read_log())
    if not args.keep_aux:
        clean_aux()
    print(f"[done] {ROOT / (MAIN + '.pdf')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
