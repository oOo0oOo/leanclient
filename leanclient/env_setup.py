# Setting up a new lean4 environment on Debian-based systems:
# Installing elan, lean and lake. Setting up a new project w imports, building and updating it.

import os
import subprocess

from .config import LEAN_PROJ_NAME


class ImportConfig:
    def __init__(self, scope: str, name: str, rev: str, import_str: str):
        self.req_str = (
            f'\n[[require]]\nname = "{name}"\nscope = "{scope}"\nrev = "{rev}"\n'
        )
        self.import_str = import_str


def install_env(lake_dir: str, use_mathlib: bool = False):
    """Install the Lean environment, elan, lake, imports, update and build.
    NOTE: Only works on Debian-based systems!"""

    print("Setting up Lean environment")
    os.makedirs(lake_dir, exist_ok=True)

    # Mathlib imports
    imports = (
        [ImportConfig("leanprover-community", "mathlib", "stable", "import Mathlib")]
        if use_mathlib
        else []
    )

    # Install elan
    reply = subprocess.run(
        "elan self update", shell=True, cwd=lake_dir, capture_output=True
    )

    if reply.returncode != 0:
        print("Installing lean and lake")
        # Install lean/lake
        cmd = "wget -q https://raw.githubusercontent.com/leanprover-community/mathlib4/master/scripts/install_debian.sh && bash install_debian.sh ; rm -f install_debian.sh && source ~/.profile"
        subprocess.run(cmd, shell=True, cwd=lake_dir)

        print("Installing elan (Lean version manager)")
        subprocess.run(
            "curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf | sh -s -- -y",
            shell=True,
            cwd=lake_dir,
        )
        subprocess.run(". $HOME/.elan/env", shell=True)
        subprocess.run("elan self update", shell=True, cwd=lake_dir)

    # Install lean
    subprocess.run(
        f"elan toolchain install leanprover/lean4:stable",
        shell=True,
        cwd=lake_dir,
    ),
    subprocess.run(
        f"elan override set leanprover/lean4:stable",
        shell=True,
        cwd=lake_dir,
    )

    # Setup lake
    subprocess.run(f"lake init {LEAN_PROJ_NAME}", shell=True, cwd=lake_dir)

    # New Main.lean, just imports
    imps = "\n".join(imp.import_str for imp in imports)
    with open(f"{lake_dir}/Main.lean", "w") as f:
        f.write(f"{imps}\nimport {LEAN_PROJ_NAME}")

    # New lakefile.toml
    toml = f'name = "{LEAN_PROJ_NAME}"\nversion = "0.1.0"\n\n[[lean_lib]]\nname = "{LEAN_PROJ_NAME}"\n'
    requirements = "\n".join(imp.req_str for imp in imports)
    with open(f"{lake_dir}/lakefile.toml", "w") as f:
        f.write(toml + requirements)

    subprocess.run("lake update", shell=True, cwd=lake_dir)
