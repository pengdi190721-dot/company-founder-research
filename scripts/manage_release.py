#!/usr/bin/env python3
"""校验并构建明确文件清单中的插件包和单独技能包。"""
import argparse
import hashlib
import json
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
PLUGIN_FILES = {
    "plugin.json", ".codex-plugin/plugin.json", "README.md", "CHANGELOG.md",
    "CONTRIBUTING.md", "examples/使用示例.md",
    *{f"skills/{NAME}/{p}" for p in EXPECTED},
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
    portable = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
    compat = json.loads((ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
    for manifest in (portable, compat):
        if manifest.get("name") != NAME or manifest.get("version") != version:
            raise ValueError("插件标识或版本与技能不一致")
        if not manifest.get("description") or not manifest.get("author", {}).get("name"):
            raise ValueError("插件描述或作者缺失")
    presentation = portable.get("extensions", {}).get("com.openai", {}).get("interface")
    if presentation != compat.get("interface") or compat.get("skills") != "./skills/":
        raise ValueError("两种插件展示信息不一致或技能入口错误")
    if not isinstance(presentation, dict) or presentation.get("displayName") != "老板与企业资料建档":
        raise ValueError("插件显示名称错误")
    if not presentation.get("shortDescription") or not presentation.get("defaultPrompt"):
        raise ValueError("插件展示简介或调用提示缺失")
    market = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text(encoding="utf-8"))
    expected_entry = {
        "name": NAME, "source": {"source": "local", "path": "./"},
        "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        "category": "Productivity",
    }
    if market.get("name") != NAME or market.get("plugins") != [expected_entry]:
        raise ValueError("插件市场入口与仓库结构不一致")
    for relative in PLUGIN_FILES:
        if not (ROOT / relative).is_file():
            raise ValueError(f"插件文件缺失：{relative}")
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
    print(f"校验通过：{NAME}，版本{version}，技能文件{len(files)}个，插件文件{len(PLUGIN_FILES)}个")
    return version, section.group(1).strip()


def build(tag=None):
    version, notes = check(tag)
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    sums = []
    packages = [
        (dist / f"{NAME}-v{version}.zip", {f"{NAME}/{p}": SKILL / p for p in EXPECTED}),
        (dist / f"{NAME}-plugin-v{version}.zip", {p: ROOT / p for p in PLUGIN_FILES}),
    ]
    for output, entries in packages:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, source in sorted(entries.items()):
                info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, source.read_bytes())
        with zipfile.ZipFile(output) as archive:
            if set(archive.namelist()) != set(entries) or archive.testzip():
                raise ValueError("压缩包结构或完整性异常")
            for name, source in entries.items():
                if archive.read(name) != source.read_bytes():
                    raise ValueError(f"发布包与源码不一致：{name}")
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        sums.append(f"{digest}  {output.name}\n")
        print(f"安装包已生成并回读核对：{output.name}")
    # 清理旧版本产物，避免标签发布流程误传旧包。
    current = {output for output, _ in packages}
    for old in dist.glob(f"{NAME}*.zip"):
        if old not in current:
            old.unlink()
    (dist / "SHA256SUMS.txt").write_text("".join(sums), encoding="utf-8")
    (dist / "发布说明.md").write_text(
        f"# 老板与企业资料建档 {version}\n\n{notes}\n\n"
        "希望在「添加 → 插件」列表看到入口，请按仓库首页安装插件版。\n"
        "带 -plugin- 的压缩包是完整插件包，另一份保留单独技能安装方式。\n"
        "安装后重新打开插件列表；必要时重启 Codex，并在新对话使用。\n"
        "压缩包已逐文件核对；具体渠道能否访问取决于实际运行环境。\n",
        encoding="utf-8",
    )


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
