import shutil
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent
projectName="atmafest";
FRONTEND_DIST = BASE_DIR / projectName / "dist"
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"


def deploy_frontend():
    print("🚀 Deploying frontend...")

    assets_src = FRONTEND_DIST / "assets"
    fonts_src = FRONTEND_DIST / "fonts"

    assets_dst = STATIC_DIR / "assets"
    fonts_dst = STATIC_DIR / "fonts"

    index_src = FRONTEND_DIST / "index.html"
    index_dst = TEMPLATES_DIR / "index.html"

    # 1. assets
    if assets_dst.exists():
        shutil.rmtree(assets_dst)
    shutil.copytree(assets_src, assets_dst)
    print("✅ assets copied")

    # 2. fonts (опционально)
    if fonts_src.exists():
        if fonts_dst.exists():
            shutil.rmtree(fonts_dst)
        shutil.copytree(fonts_src, fonts_dst)
        print("✅ fonts copied")

    # 3. index.html
    shutil.copy2(index_src, index_dst)
    print("✅ index.html copied")

    print("🎉 Frontend deployed successfully")


if __name__ == "__main__":
    deploy_frontend()