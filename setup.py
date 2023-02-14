import subprocess

from setuptools import setup, find_packages

spanner_version = subprocess.run(("git", "rev-list", "--count", "HEAD")), capture_output=True, encoding="utf-8")
spanner_version = spanner_version.stdout.strip()

with open("requirements.txt") as requirements_txt:
    requirements = requirements_txt.readlines()


setup(
    name="spanner",
    version="2.1.0p1.dev" + spanner_version,
    py_modules=["spanner"],
    packages=find_packages(),
    install_requires=requirements,
    extras_requires={"monitoring": ["cronitor==4.6.0"]},
    python_requires=">3.8,<3.11",
    entry_points={
        "console_scripts": ["spanner-cli = spanner:cli"],
    },
)
