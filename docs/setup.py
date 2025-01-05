# This and requirements.txt is only required for readthedocs.
from setuptools import setup, find_packages

setup(
    packages=find_packages(where="../"),
    package_dir={"": "../"},
    install_requires=["orjson"],
)
