"""Generate video-course.html from manifest.json and course metadata JSON."""
import argparse
import json
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(
    os.path.dirname(SCRIPT_DIR), "resources", "course_template.html"
)


def fmt_mmss(sec: float) -> str:
    total = int(round(sec))
    return f"{total // 60:02d}:{total % 60:02d}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, help="Path to videos/manifest.json")
    parser.add_argument("--out-html", required=True, help="Output video-course.html path")
    parser.add_argument("--title", default="文档精讲视频课程")
    parser.add_argument("--kicker", default="DOC-TO-VIDEO · 零基础系列课程")
    parser.add_argument("--lead", default="配套高清分章讲解视频与同步字幕。")
    parser.add_argument("--source-doc", default="", help="Relative path to source document")
    parser.add_argument("--video-prefix", default="videos/")
    parser.add_argument("--meta-json", default=None, help="Optional JSON mapping ep_num -> {title, desc, anchor}")
    args = parser.parse_args()

    manifest = json.load(open(args.manifest, encoding="utf-8"))
    meta = json.load(open(args.meta_json, encoding="utf-8")) if args.meta_json else {}

    episodes_payload = []
    total_sec = 0.0
    for item in manifest:
        ep_num = item["ep_num"]
        m = meta.get(ep_num, {})
        total_sec += item["duration_sec"]
        episodes_payload.append({
            "num": f"EP {ep_num}",
            "title": m.get("title", os.path.splitext(os.path.basename(item["mp4"]))[0]),
            "file": os.path.basename(item["mp4"]),
            "srt": os.path.basename(item["srt"]),
            "dur": item.get("duration_mmss", fmt_mmss(item["duration_sec"])),
            "anchor": m.get("anchor", args.source_doc or "#"),
            "desc": m.get("desc", ""),
        })

    tpl = open(TEMPLATE_PATH, encoding="utf-8").read()
    source_badge = (
        f'<span class="badge"><a href="{args.source_doc}">打开原讲义 →</a></span>'
        if args.source_doc else ""
    )
    html = (
        tpl.replace("{{COURSE_TITLE}}", args.title)
        .replace("{{COURSE_KICKER}}", args.kicker)
        .replace("{{COURSE_LEAD}}", args.lead)
        .replace("{{EP_COUNT}}", str(len(episodes_payload)))
        .replace("{{TOTAL_MMSS}}", fmt_mmss(total_sec))
        .replace("{{SOURCE_LINK_BADGE}}", source_badge)
        .replace("{{CHEATSHEET_HTML}}", "")
        .replace("{{EPISODES_JSON}}", json.dumps(episodes_payload, ensure_ascii=False))
        .replace("{{VIDEO_PREFIX_JSON}}", json.dumps(args.video_prefix, ensure_ascii=False))
    )
    with open(args.out_html, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Generated course hub: {args.out_html}")


if __name__ == "__main__":
    main()
