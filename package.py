"""
打包脚本 - 将语音提词器打包为 Windows EXE
运行: python package.py

打包前请确保:
1. pip install pyinstaller
2. 模型在首次运行时自动下载（需联网），或提前运行一次程序让模型缓存
"""

import os
import sys
import shutil
import logging

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def check_dependencies():
    """检查打包依赖"""
    try:
        import PyInstaller
        logger.info("✅ PyInstaller 已安装")
    except ImportError:
        logger.error("❌ 请安装 PyInstaller: pip install pyinstaller")
        return False
    return True


def build():
    """执行打包"""
    base_dir = os.path.dirname(os.path.abspath(__file__))

    # 检查依赖
    if not check_dependencies():
        sys.exit(1)

    # 准备 PyInstaller 参数
    main_script = os.path.join(base_dir, "main.py")

    dist_dir = os.path.join(base_dir, "dist")
    build_dir = os.path.join(base_dir, "build")
    spec_file = os.path.join(base_dir, "teleprompter.spec")

    cmd = [
        "pyinstaller",
        "--name=语音提词器",
        "--onefile",
        "--windowed",
        "--noconfirm",
        "--clean",
        f"--distpath={dist_dir}",
        f"--workpath={build_dir}",
        f"--specpath={base_dir}",
        "--add-data=resources/style.qss;resources/",
    ]

    # faster-whisper 模型在首次运行时自动从 HuggingFace 下载
    # 缓存目录: ~/.cache/huggingface/hub/
    # 无需打包进 EXE

    # 隐式导入（PyInstaller 可能遗漏的）
    hidden_imports = [
        "faster_whisper",
        "pyaudio",
        "docx",
        "requests",
        "ctranslate2",
        "huggingface_hub",
        "tokenizers",
    ]
    for imp in hidden_imports:
        cmd.append(f"--hidden-import={imp}")

    cmd.append(main_script)

    # 执行打包
    logger.info("=" * 40)
    logger.info("开始打包...")
    logger.info(f"输出目录: {dist_dir}")
    logger.info(f"命令: {' '.join(cmd)}")
    logger.info("=" * 40)

    import subprocess
    result = subprocess.run(cmd, cwd=base_dir)

    if result.returncode == 0:
        logger.info("=" * 40)
        logger.info("✅ 打包成功！")
        exe_path = os.path.join(dist_dir, "语音提词器.exe")
        if os.path.exists(exe_path):
            size_mb = os.path.getsize(exe_path) / (1024 * 1024)
            logger.info(f"📦 EXE 文件: {exe_path}")
            logger.info(f"📏 文件大小: {size_mb:.1f} MB")
        logger.info("=" * 40)
    else:
        logger.error("❌ 打包失败，请检查错误信息")


def clean():
    """清理打包产物"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dirs_to_remove = [
        os.path.join(base_dir, "build"),
        os.path.join(base_dir, "dist"),
    ]
    files_to_remove = [
        os.path.join(base_dir, "teleprompter.spec"),
    ]

    for d in dirs_to_remove:
        if os.path.isdir(d):
            shutil.rmtree(d)
            logger.info(f"🗑 已删除目录: {d}")

    for f in files_to_remove:
        if os.path.isfile(f):
            os.remove(f)
            logger.info(f"🗑 已删除文件: {f}")

    logger.info("✅ 清理完成")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="语音提词器 - 打包工具")
    parser.add_argument(
        "--clean", action="store_true",
        help="清理打包产物"
    )
    args = parser.parse_args()

    if args.clean:
        clean()
    else:
        build()
