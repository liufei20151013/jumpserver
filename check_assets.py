# -*- coding: utf-8 -*-
"""镜像构建期资源自检。

背景：定制仓库用 Git LFS 管理 *.mo / *.mmdb / *.ipdb。若以 tar 包方式取代码
（codeload、内网镜像等），这些文件会退化成 130 字节左右的 LFS 指针文本，
直接打进镜像会导致 Django 启动崩溃：
    OSError: [Errno 0] Bad magic number: .../locale/zh/LC_MESSAGES/django.mo

本脚本在 docker build 阶段校验，任何一项不通过就让构建失败。
"""
import glob
import gettext
import os
import sys

APP_DIR = "/opt/jumpserver/apps"

BINARIES = [
    f"{APP_DIR}/common/utils/geoip/GeoLite2-City.mmdb",
    f"{APP_DIR}/common/utils/ip/geoip/GeoLite2-City.mmdb",
    f"{APP_DIR}/common/utils/ip/ipip/ipipfree.ipdb",
]

EXPECTED_LOCALES = ["en", "ja", "zh", "zh_Hant"]


def is_lfs_pointer(path):
    try:
        with open(path, "rb") as f:
            return f.read(16).startswith(b"version https://")
    except OSError:
        return False


def main():
    errors = []

    mo_files = sorted(glob.glob(f"{APP_DIR}/locale/*/LC_MESSAGES/*.mo"))
    found_locales = sorted({
        p.split("/locale/")[1].split("/")[0] for p in mo_files
    })
    if found_locales != sorted(EXPECTED_LOCALES):
        errors.append(f"语言目录不完整: {found_locales}")

    for path in mo_files:
        if is_lfs_pointer(path):
            errors.append(f"{path}: 仍是 Git LFS 指针文件")
            continue
        try:
            with open(path, "rb") as f:
                gettext.GNUTranslations(f)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{path}: 解析失败 {exc}")

    for path in BINARIES:
        if not os.path.exists(path):
            errors.append(f"{path}: 文件缺失")
        elif is_lfs_pointer(path):
            errors.append(f"{path}: 仍是 Git LFS 指针文件")
        elif os.path.getsize(path) < 100 * 1024:
            errors.append(f"{path}: 尺寸异常 {os.path.getsize(path)} 字节")

    if errors:
        print("资源自检失败：")
        for item in errors:
            print("  -", item)
        return 1

    print(f"资源自检通过：{len(mo_files)} 个 .mo 可解析，{len(BINARIES)} 个二进制库完整")
    return 0


if __name__ == "__main__":
    sys.exit(main())
