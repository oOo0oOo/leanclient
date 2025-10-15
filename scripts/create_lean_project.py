"""
This script creates a simple Lean project with lake and optionally Mathlib.
Mainly used for testing, but this project could be used as a starting point.

Usage:
    python create_lean_project.py <project_path> <project_name> [--use-mathlib] [--force]

Args:
    project_path (str): The relative path where the Lean project will be created.
    project_name (str): The name of the Lean project.
    --use-mathlib: Include Mathlib in the project.
    --force: Force the recreation of the project if it already exists.
"""

import os
import subprocess
import argparse


def create_lean_project(
    project_path: str,
    project_name: str,
    lean_version: str = "stable",
    use_mathlib: bool = False,
    force: bool = False,
):
    """Create a simple Lean project with lake and optionally Mathlib.
    This is used in testing."""
    # Install lean and lake
    install_env(project_path, lean_version)

    # If project already exists return
    full_path = os.path.join(project_path, project_name)
    if os.path.exists(full_path):
        if force:
            print(f"Project already exists. Deleting {full_path}/ to recreate")
            subprocess.run(f"rm -rf {full_path}", shell=True)
        else:
            print(f"Project already exists. Delete {full_path}/ to recreate")
            return

    subprocess.run(f"lake init {project_name}", shell=True, cwd=project_path)

    # Main.lean and lakefile.toml
    with open(os.path.join(project_path, "Main.lean"), "w") as f:
        main = "import Mathlib\n" if use_mathlib else ""
        f.write(main + "import " + project_name)

    toml = f'name = "{project_name}"\nversion = "0.1.0"\n\n[[lean_lib]]\nname = "{project_name}"\n'
    if use_mathlib:
        toml += f'[[require]]\nname = "mathlib"\nscope = "leanprover-community"\nrev = "{lean_version}"\n'
    with open(os.path.join(project_path, "lakefile.toml"), "w") as f:
        f.write(toml)

    subprocess.run("lake update", shell=True, cwd=project_path)
    subprocess.run("lake exe cache get", shell=True, cwd=project_path)
    subprocess.run(f"lake build", shell=True, cwd=project_path)


def install_env(project_path: str, lean_version: str = "stable"):
    """Install the Lean environment, elan, lake, imports, update and build.
    NOTE: Fails on non-Debian-systems if you can not run `elan self update` in project_path.
    """
    if os.path.exists(project_path):
        print(f"Lean environment already exists. Delete {project_path} to recreate.")
        return

    print("Setting up Lean environment")
    os.makedirs(project_path, exist_ok=True)

    # Install elan
    reply = subprocess.run(
        "elan self update", shell=True, cwd=project_path, capture_output=True
    )

    if reply.returncode != 0:
        # On Debian-based systems install lean and lake
        if os.path.exists("/etc/debian_version"):
            print("Installing lean and lake")
            # Install lean/lake
            cmd = "wget -q https://raw.githubusercontent.com/leanprover-community/mathlib4/master/scripts/install_debian.sh && bash install_debian.sh ; rm -f install_debian.sh && source ~/.profile"
            subprocess.run(cmd, shell=True, cwd=project_path)

            print("Installing elan (Lean version manager)")
            subprocess.run(
                "curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf | sh -s -- -y",
                shell=True,
                cwd=project_path,
            )
            subprocess.run(". $HOME/.elan/env", shell=True)
            subprocess.run("elan self update", shell=True, cwd=project_path)
        # On other systems raise error
        else:
            msg = "Install elan manually or run on a Debian-based system."
            msg += (
                "\nYou should be able to run `elan self update` in your project_path:"
            )
            msg += f"\n{project_path}"
            raise SystemExit(msg)

    # Install lean
    subprocess.run(
        f"elan toolchain install leanprover/lean4:{lean_version}",
        shell=True,
        cwd=project_path,
    ),
    subprocess.run(
        f"elan override set leanprover/lean4:{lean_version}",
        shell=True,
        cwd=project_path,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Set up a new Lean 4 environment.")
    parser.add_argument(
        "project_path",
        type=str,
        help="The path where the Lean project will be created.",
    )
    parser.add_argument("project_name", type=str, help="The name of the Lean project.")
    parser.add_argument(
        "lean_version",
        type=str,
        default="stable",
        help="The version of Lean to install.",
    )
    parser.add_argument(
        "--use-mathlib", action="store_true", help="Include Mathlib in the project."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force the recreation of the project if it already exists.",
    )

    args = parser.parse_args()

    create_lean_project(
        args.project_path,
        args.project_name,
        args.lean_version,
        args.use_mathlib,
        args.force,
    )
