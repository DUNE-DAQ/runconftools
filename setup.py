from setuptools import setup

# Metadata goes in setup.cfg. These are here for GitHub's dependency graph.
setup(
    name="drunc",
    install_requires=[
        "click",
        "click-shell",
        "grpcio",
        "googleapis-common-protos",
        "grpcio-status",
        "grpcio-tools",
        "gunicorn",
        "kafka-python",
        "nest-asyncio",
        "rich",
        "requests",
        "Flask",
        "Flask-RESTful",
        "sh",
        "kubernetes",
        "pytz",
        "psutil",
    ],
    extras_require={"develop": ["ipdb", "ipython", "ruff", "pre-commit", "pytest"]},
