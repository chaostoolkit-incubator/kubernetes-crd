import os
import subprocess
import sys
from typing import List

import pytest
import yaml

curdir = os.path.abspath(os.path.join(os.path.dirname(__file__)))
fixturedir = os.path.join(curdir, "fixtures")
sys.path.insert(0, os.path.join(curdir, ".."))
import controller
from controller import Resource


@pytest.fixture(scope="session")
def topdir():
    return os.path.join(curdir, "..")


@pytest.fixture(scope="session")
def generic(topdir: str) -> List[Resource]:
    cp = subprocess.run("kustomize version", shell=True, check=True,
        cwd=topdir, capture_output=True)
    print(cp.stdout.decode("utf-8"))

    cp = subprocess.run(
        "kustomize build manifests/overlays/generic", shell=True, check=True,
        cwd=topdir, capture_output=True)

    return list(yaml.safe_load_all(cp.stdout.decode("utf-8")))
