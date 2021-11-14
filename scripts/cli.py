import os
import platform
import subprocess
import sys
from argparse import ArgumentParser, Namespace
from pathlib import Path

parser = ArgumentParser(description="A simple command line interface for running spanner v2.", allow_abbrev=True)
parser.add_argument(
    "--enforce-cwd",
    action="store_true",
    default=False,
    help="Enforce the current working directory to be the project root.",
)
parser.add_argument(
    "--force-setup", action="store_true", help="Force the setup to run even if the project is already setup."
)
parser.add_argument("--version", action="store_true", help="Displays simple version information")
parser.add_argument("--debug-info", action="store_true", help="Displays debug information, very similar to --version.")

args: Namespace = parser.parse_args()

if args.version:
    print("Resolving version...")
    git_revision = (
        subprocess.run(("git", "rev-parse", "HEAD", "--short"), check=True, capture_output=True)
        .stdout.decode("utf-8")
        .strip()
    )
    print("Spanner v2 revision:", git_revision)
    sys.exit()

if args.debug_info:
    print("Resolving information...", end="\r")
    try:
        from discord import __version__ as discord_version
    except ImportError:
        discord_version = "Not installed"

    try:
        from aiohttp import __version__ as aiohttp_version
    except ImportError:
        aiohttp_version = "Not installed"

    SPANNER_GIT_REVISION: str = (
        subprocess.run(("git", "rev-parse", "HEAD", "--short"), capture_output=True).stdout.decode("utf-8").strip()
    )

    # try:
    #     import orjson
    # except ImportError:
    #     orjson = False
    # I'm so tired of trying to figure out how to install this god forbidden package
    # I can't install it on windows because build tools, I can't install it on my raspberry pi because idfk
    # My only option left is to reboot into linux, but I can't be arsed dealing with the hardware conflicts
    # So lets just say fuck it and check the pip output.
    output = [
        ("Python Version:", sys.version),
        ("Operating System:", platform.platform()),
        ("discord.py (py-cord) version:", discord_version),
        ("AioHTTP Version:", aiohttp_version),
        ("Spanner v2 revision:", SPANNER_GIT_REVISION or "UNKNOWN"),
    ]

    orjson_version = "OrJSON Version: "
    proc = subprocess.run(("pip", "show", "orjson", "--no-input"), capture_output=True)
    if proc.returncode == 0:
        # Installed
        line = proc.stdout.decode("utf-8").split("\n")[1][9:]
        orjson_version += line
    else:
        orjson_version += "Not Installed."
    output.append((orjson_version,))

    longest_value = 0
    for parts in output:
        length = len(" ".join(parts))
        if length > longest_value:
            longest_value = length

    header = "=" * (longest_value + 2)
    print("+" + header + "+")
    for parts in output:
        length = len(" ".join(parts))
        spaces = longest_value - length
        print("|", *parts, (" " * spaces) + "|")
    print("+" + header + "+")

if args.force_setup:
    from scripts.first_run import main
    main()

if args.enforce_cwd:
    os.chdir(Path(__file__).parents[2])
