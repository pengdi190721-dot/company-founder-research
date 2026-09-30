#!/usr/bin/env python3
"""校验并构建仅包含通用技能文件的可安装版本包。"""
import argparse
import hashlib
from pathlib import Path
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
NAME = "company-founder-research"
SKILL = ROOT / "skills" / NAME
EXPECTED = {
    "SKILL.md",
    "agents/openai.yaml",
    "references/collection.md",
    "references/report-template.md",
}


def check(tag=None):
    files = {p.relative_to(SKILL).as_posix() for p in SKILL.rglob("*") if p.is_file()}
    if files != EXPECTED:
        raise ValueError(f"技能文件清单异常：缺少{EXPECTED-files}；多出{files-EXPECTED}")
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    if not match:
        raise ValueError("技能元数据缺失")
    front = match.group(1)
    if not re.search(rf"^name: {NAME}$", front, re.M):
        raise ValueError("技能标识与目录不一致")
    if not re.search(r'^description: ".+"$', front, re.M):
        raise ValueError("技能简介需为非空单行字符串")
    version_match = re.search(r'^  version: "(\d+\.\d+\.\d+)"$', front, re.M)
    if not version_match:
        raise ValueError("技能版本缺失或格式不正确")
    version = version_match.group(1)
    if tag is not None and tag != f"v{version}":
        raise ValueError(f"标签{tag}与技能版本{version}不一致")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if f"当前版本：`{version}`" not in readme:
        raise ValueError("首页版本与技能版本不一致")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    section = re.search(rf"^## {re.escape(version)} — [^\n]+\n(.*?)(?=^## |\Z)", changelog, re.M | re.S)
    if not section or not section.group(1).strip():
        raise ValueError("缺少本版本变化记录")
    for p in [ROOT / "README.md", ROOT / "CONTRIBUTING.md", *SKILL.rglob("*.md")]:
        content = p.read_text(encoding="utf-8")
        if "/Users/" in content or "Documents/Codex" in content:
            raise ValueError(f"包含本机路径：{p.relative_to(ROOT)}")
        for target in re.findall(r"\]\(([^)]+)\)", content):
            if "://" in target or target.startswith("#"):
                continue
            dest = (p.parent / target.split("#", 1)[0]).resolve()
            if not dest.is_relative_to(ROOT) or not dest.is_file():
                raise ValueError(f"引用文件不存在或超出仓库：{p.relative_to(ROOT)} -> {target}")
    interface = (SKILL / "agents/openai.yaml").read_text(encoding="utf-8")
    if f"${NAME}" not in interface:
        raise ValueError("默认调用未指向本技能")
    print(f"校验通过：{NAME}，版本{version}，技能文件{len(files)}个")
    return version, section.group(1).strip()


def build(tag=None):
    version, notes = check(tag)
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    output = dist / f"{NAME}-v{version}.zip"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in sorted(EXPECTED):
            info = zipfile.ZipInfo(f"{NAME}/{relative}", date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, (SKILL / relative).read_bytes())
    with zipfile.ZipFile(output) as archive:
        expected_names = {f"{NAME}/{p}" for p in EXPECTED}
        if set(archive.namelist()) != expected_names or archive.testzip():
            raise ValueError("压缩包结构或完整性异常")
        for relative in EXPECTED:
            if archive.read(f"{NAME}/{relative}") != (SKILL / relative).read_bytes():
                raise ValueError(f"发布包与源码不一致：{relative}")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    (dist / "SHA256SUMS.txt").write_text(f"{digest}  {output.name}\n", encoding="utf-8")
    (dist / "发布说明.md").write_text(
        f"# 老板与企业资料建档 {version}\n\n{notes}\n\n"
        "请下载下方技能压缩包用于安装。安装后重启 Codex。\n"
        "压缩包已逐文件核对；具体渠道能否访问取决于实际运行环境。\n",
        encoding="utf-8",
    )
    print(f"安装包已生成并回读核对：{output.name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "build"))
    parser.add_argument("--tag")
    args = parser.parse_args()
    try:
        (check if args.mode == "check" else build)(args.tag)
    except (ValueError, OSError, zipfile.BadZipFile) as exc:
        print(f"校验失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
