#!/usr/bin/env python3
"""Build a mobile-friendly Feishu card for the daily health report."""

from __future__ import annotations

import argparse
import json


def markdown_section(title: str, lines: list[str]) -> dict[str, str]:
    content = f"**{title}**\n" + "\n".join(f"• {line}" for line in lines)
    return {
        "tag": "markdown",
        "content": content,
        "text_align": "left",
        "text_size": "normal_v2",
        "margin": "0px",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", required=True)
    parser.add_argument("--icon", required=True)
    parser.add_argument("--timestamp", required=True)
    parser.add_argument("--template", choices=("green", "orange", "red"), required=True)
    parser.add_argument("--public-url", required=True)
    parser.add_argument("--critical", action="append", default=[])
    parser.add_argument("--warning", action="append", default=[])
    parser.add_argument("--system", action="append", default=[])
    parser.add_argument("--service", action="append", default=[])
    parser.add_argument("--data", action="append", default=[])
    parser.add_argument("--backup", action="append", default=[])
    args = parser.parse_args()

    elements: list[dict[str, object]] = []
    if args.critical:
        elements.append(markdown_section("🔴 严重问题", args.critical))
    if args.warning:
        elements.append(markdown_section("🟡 注意事项", args.warning))
    if args.critical or args.warning:
        elements.append({"tag": "hr", "margin": "4px 0px"})

    sections = (
        ("🖥️ 系统资源", args.system),
        ("🌐 服务与网络", args.service),
        ("🗄️ 数据库与业务", args.data),
        ("💾 数据备份", args.backup),
    )
    for index, (title, lines) in enumerate(sections):
        if index:
            elements.append({"tag": "hr", "margin": "4px 0px"})
        elements.append(markdown_section(title, lines))

    elements.append(
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "打开资产看板"},
            "type": "default",
            "width": "fill",
            "size": "medium",
            "behaviors": [{"type": "open_url", "default_url": args.public_url}],
            "margin": "4px 0px 0px 0px",
        }
    )

    payload = {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
            "config": {
                "update_multi": True,
                "style": {
                    "text_size": {
                        "normal_v2": {
                            "default": "normal",
                            "pc": "normal",
                            "mobile": "normal",
                        }
                    }
                },
            },
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"{args.icon} Atlas Ledger 每日巡检 · {args.status}",
                },
                "subtitle": {"tag": "plain_text", "content": args.timestamp},
                "template": args.template,
                "padding": "12px",
            },
            "body": {
                "direction": "vertical",
                "padding": "12px",
                "elements": elements,
            },
        },
    }
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
