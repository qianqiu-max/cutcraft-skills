"""Start an unpublished Cutcraft skill; fill its instructions, renderer and previews before publishing."""
import argparse
import json
from pathlib import Path
from build import ROOT, SLUG


def scaffold(root, slug, title, category, engine):
    if not SLUG.fullmatch(slug) or len(slug) > 64:
        raise ValueError("Use a lowercase, hyphenated skill id of up to 64 characters")
    destination = root / "skills" / slug
    destination.mkdir(exist_ok=False)
    (destination / "previews").mkdir()
    frontmatter = f"---\nname: {slug}\ndescription: {json.dumps(title + '剪辑效果的制作与复刻。', ensure_ascii=False)}\n---\n"
    (destination / "SKILL.md").write_text(frontmatter + f"""
# {title}

## 素材与依赖

写明素材数量、角色、运行环境和目标编辑器版本。

## 制作步骤

记录教程中可观察的图层、运动、关键时间、声音和单位。给出相对于本目录的脚本入口、输入参数与输出例子。

## 复现与验收

用两组不同素材实际执行。记录与参考片的差异、工程复开、成片解码和完整听看的结果。
""", encoding="utf-8")
    metadata = {"title": title, "category": category, "summary": "", "engine": engine,
                "inputs": [], "prompt": "", "featured": False, "order": 100, "draft": True}
    (destination / "showcase.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug")
    parser.add_argument("--title", required=True)
    parser.add_argument("--category", required=True)
    parser.add_argument("--engine", required=True)
    args = parser.parse_args()
    folder = scaffold(ROOT, args.slug, args.title, args.category, args.engine)
    print(f"Draft created at {folder}. See docs/adding-a-skill.md for publishing.")
