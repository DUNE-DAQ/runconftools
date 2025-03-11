from setuptools import setup

# Metadata goes in setup.cfg. These are here for GitHub's dependency graph.
setup(
    name="config-management",
    install_requires=[
        "click",
        "click-shell",
        "GitPython",
        "sh",
    ],
    extras_require={"develop": ["ipdb", "ipython"]}
)

