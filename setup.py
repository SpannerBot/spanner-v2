import subprocess

from setuptools import setup, find_packages

spanner_version = subprocess.run(("git", "rev-parse", "--short", "HEAD"), capture_output=True, encoding="utf-8")
spanner_version = spanner_version.stdout.strip()

setup(
    name='spanner',
    version="2.0.0b" + spanner_version,
    py_modules=['spanner'],
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        'Click',
    ],
    entry_points={
        'console_scripts': [
            'spanner = spanner:main',
        ],
    },
)