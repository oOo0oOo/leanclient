from setuptools import setup, find_packages

setup(
    name="leanclient",
    version="0.1.0",
    packages=find_packages(),
    install_requires=["orjson"],
    extras_require={"dev": ["gprof2dot", "black"]},
    url="https://github.com/oOo0oOo/leanclient",
    description="A client to interact with the Lean theorem prover lsp server",
    python_requires=">=3.5",
)
