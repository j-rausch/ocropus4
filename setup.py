#!/usr/bin/python3
#
# Copyright (c) 2017-2019 NVIDIA CORPORATION. All rights reserved.
# This file is part of webloader (see TBD).
# See the LICENSE file for licensing terms (BSD-style).
#

import sys
from distutils.core import setup

if sys.version_info < (3, 6):
    sys.exit("Python versions less than 3.6 are not supported")

VERSION = "0.0.0"

PREREQS = """
click==7.1.1
typer
braceexpand
bs4
editdistance
lxml
matplotlib
scikit-image
scipy
humanhash3
tabulate
webdataset@git+git://github.com/tmbdev/webdataset.git
tensorcom@git+git://github.com/NVlabs/tensorcom.git
torchmore@git+git://github.com/tmbdev/torchmore.git
ocrodeg@git+git://github.com/NVlabs/ocrodeg.git
""".split()
print(PREREQS)

setup(
    name="ocropus",
    version=VERSION,
    description="OCRopus 4",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="http://github.com/tmbdev/ocropus4",
    author="Thomas Breuel",
    author_email="tmbdev+removeme@gmail.com",
    license="MIT",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "License :: OSI Approved :: BSD License",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
    ],
    keywords="ocr, scene text, deep learning, text recognition",
    packages=["ocropus"],
    python_requires=">=3.6",
    scripts=["ocropus4"],
    install_requires=PREREQS,
)
