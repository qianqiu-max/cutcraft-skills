"""Validate effect packages and build a portable, dependency-free GitHub Pages site."""
import argparse
import json
import re
import shutil
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "https://github.com/qianqiu-max/cutcraft-skills"
SITE_URL = "https://qianqiu-max.github.io/cutcraft-skills"
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", "previews"}
EXCLUDED_FILES = {"showcase.json", ".DS_Store", "Thumbs.db"}


def file_list(skill):
    """Whitelist the parts of a skill intended to be installed by another agent."""
    for path in sorted(skill.rglob("*")):
        relative = path.relative_to(skill)
        if any(part in SKIP_DIRS or part.startswith(".") for part in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError(f"{path}: use files inside the skill package")
        if not path.is_file() or path.name in EXCLUDED_FILES or path.suffix == ".pyc":
            continue
        yield path, Path(skill.name) / relative


def read_skill(skill):
    key = skill.name
    if not SLUG.fullmatch(key) or len(key) > 64:
        raise ValueError(f"Invalid skill directory name: {key}")
    meta = json.loads((skill / "showcase.json").read_text(encoding="utf-8"))
    if not isinstance(meta, dict):
        raise ValueError(f"{key}/showcase.json must contain an object")
    if not isinstance(meta.get("draft", False), bool):
        raise ValueError(f"{key}: draft must be a boolean")
    body = (skill / "SKILL.md").read_text(encoding="utf-8")
    sections = body.split("---", 2)
    if len(sections) != 3 or sections[0].strip():
        raise ValueError(f"{key}/SKILL.md needs YAML frontmatter")
    name = re.search(r"^name:\s*([^\r\n]+)", sections[1], re.M)
    if not name or name[1].strip().strip("\"'") != key or not re.search(r"^description:\s*\S", sections[1], re.M):
        raise ValueError(f"{key}: SKILL.md must declare its folder name and a description")
    if meta.get("draft", False):
        return None
    for field in ("title", "summary", "category", "engine", "prompt"):
        if not isinstance(meta.get(field), str) or not meta[field].strip():
            raise ValueError(f"{key}/showcase.json: missing {field}")
    if not isinstance(meta.get("inputs"), list) or not meta["inputs"] or not all(
        isinstance(item, str) and item.strip() for item in meta["inputs"]
    ):
        raise ValueError(f"{key}: inputs must list the required materials")
    if type(meta.get("order")) is not int or not isinstance(meta.get("featured", False), bool):
        raise ValueError(f"{key}: use an integer order and a boolean featured flag")
    for filename in ("poster.webp", "demo.mp4"):
        asset = skill / "previews" / filename
        if not asset.is_file() or asset.is_symlink() or asset.stat().st_size == 0:
            raise ValueError(f"{key}: missing public preview {filename}")
    url = f"{REPOSITORY}/tree/main/skills/{key}"
    raw = f"https://raw.githubusercontent.com/qianqiu-max/cutcraft-skills/main/skills/{key}/SKILL.md"
    download = f"{SITE_URL}/downloads/{key}.zip"
    prompt = (f"请使用 Cutcraft 的「{meta['title']}」Skill 处理我提供的素材。\n"
              f"完整技能包（含脚本和参考文件）：{download}\n技能说明：{raw}\n"
              f"源码目录：{url}\n从完整技能包或源码目录读取 SKILL.md 和它引用的文件，然后执行以下任务。\n\n"
              + meta["prompt"].strip())
    return {**{f: meta[f] for f in ("title", "category", "engine", "summary", "inputs", "order")},
            "id": key, "featured": meta.get("featured", False), "skillUrl": url,
            "poster": f"previews/{key}/poster.webp", "video": f"previews/{key}/demo.mp4",
            "download": download, "prompt": prompt}


def generate(destination):
    shutil.copytree(ROOT / "site", destination, dirs_exist_ok=True)
    (destination / "downloads").mkdir()
    items = []
    with ZipFile(destination / "downloads" / "cutcraft-skills.zip", "w", ZIP_DEFLATED) as collection:
        for source in sorted((ROOT / "skills").iterdir()):
            if not source.is_dir() or source.name.startswith("."):
                continue
            item = read_skill(source)
            if item is None:
                continue
            preview = destination / "previews" / source.name
            preview.mkdir(parents=True)
            for name in ("poster.webp", "demo.mp4"):
                shutil.copy2(source / "previews" / name, preview / name)
            with ZipFile(destination / "downloads" / (source.name + ".zip"), "w", ZIP_DEFLATED) as archive:
                for path, arc in file_list(source):
                    archive.write(path, arc.as_posix())
                    collection.write(path, arc.as_posix())
            items.append(item)
    if not items or sum(item["featured"] for item in items) > 1:
        raise ValueError("Publish at least one skill and feature at most one")
    items.sort(key=lambda item: (item["order"], item["id"]))
    (destination / "catalog.json").write_text(
        json.dumps({"repository": REPOSITORY, "skills": items}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    (destination / ".nojekyll").touch()
    return items


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate and build in a temporary directory")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="cutcraft-build-", dir=ROOT) as temp:
        stage = Path(temp) / "site"
        items = generate(stage)
        if not args.check:
            target = ROOT / "dist"
            if target.is_symlink() or (target.exists() and not target.is_dir()):
                raise ValueError("dist must be a directory inside this checkout")
            if target.exists():
                if target.resolve().parent != ROOT.resolve():
                    raise ValueError("dist resolves outside this checkout")
                shutil.rmtree(target)
            stage.rename(target)
    print(f"{'Checked' if args.check else 'Built'} {len(items)} published skills.")


if __name__ == "__main__":
    main()
