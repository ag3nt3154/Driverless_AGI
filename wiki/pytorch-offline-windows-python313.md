---
title: 'Offline PyTorch CUDA 12.6 wheels for Windows Python 3.13'
description: 'Verified pip resolution, exact wheel URLs, and commands to identify and install an offline wheel set.'
tags: [torch, torchvision, pip, wheels, offline, cu126, win_amd64, cp313]
updated: 2026-10-11
---

Target: Windows x64, standard CPython 3.13 (cp313 ABI), torch and torchvision from the CUDA 12.6 index. Free-threaded Python uses a different ABI.

On 2026-10-11 pip 26.2.1 resolved 13 wheels with `--dry-run --ignore-installed --only-binary=:all: --platform win_amd64 --python-version 3.13 --implementation cp --abi cp313`. No packages were installed. The resolver ran under Windows Python 3.14 with explicit target compatibility flags; inspection of the selected metadata found no non-extra dependency marker that changes the set between Python 3.13 and 3.14. This verifies dependency resolution, not imports or GPU execution on the target.

## Exact file request

These are the resolver-selected versions at the verification date, not permanent minimum versions. An existing environment may need fewer wheels if compatible dependencies are installed. Optional extras were not requested.

- [torch-2.14.1+cu126-cp313-cp313-win_amd64.whl](https://download-r2.pytorch.org/whl/cu126/torch-2.14.1%2Bcu126-cp313-cp313-win_amd64.whl)
- [torchvision-0.29.1+cu126-cp313-cp313-win_amd64.whl](https://download-r2.pytorch.org/whl/cu126/torchvision-0.29.1%2Bcu126-cp313-cp313-win_amd64.whl)
- [filelock-3.32.3-py3-none-any.whl](https://files.pythonhosted.org/packages/a7/8e/50f46a9c0ce8d2861a394c1347caae037ea0431d2f67d7feb151cbc4649a/filelock-3.32.3-py3-none-any.whl)
- [typing_extensions-4.16.0-py3-none-any.whl](https://files.pythonhosted.org/packages/49/d3/b8441a820a491ddfc024b0b0cf0393375b75ea13866d9c66727e54c2fc80/typing_extensions-4.16.0-py3-none-any.whl)
- [setuptools-78.1.0-py3-none-any.whl](https://download.pytorch.org/whl/setuptools-78.1.0-py3-none-any.whl)
- [sympy-1.14.0-py3-none-any.whl](https://files.pythonhosted.org/packages/a2/09/77d55d46fd61b4a135c444fc97158ef34a095e5681d0a6c10b75bf356191/sympy-1.14.0-py3-none-any.whl)
- [mpmath-1.3.0-py3-none-any.whl](https://files.pythonhosted.org/packages/43/e3/7d92a15f894aa0c9c4b49b8ee9ac9850d6e63b03c9c32c0367a13ae62209/mpmath-1.3.0-py3-none-any.whl)
- [networkx-3.6.1-py3-none-any.whl](https://files.pythonhosted.org/packages/9e/c9/b2622292ea83fbb4ec318f5b9ab867d0a28ab43c5717bb85b0a5f6b3b0a4/networkx-3.6.1-py3-none-any.whl)
- [jinja2-3.1.6-py3-none-any.whl](https://download.pytorch.org/whl/jinja2-3.1.6-py3-none-any.whl)
- [markupsafe-3.0.3-cp313-cp313-win_amd64.whl](https://download.pytorch.org/whl/markupsafe-3.0.3-cp313-cp313-win_amd64.whl)
- [fsspec-2026.7.0-py3-none-any.whl](https://files.pythonhosted.org/packages/fd/3c/6a2bf344106328fd04963664a60b9bb6496fc25df8e962fcdc1367285fb9/fsspec-2026.7.0-py3-none-any.whl)
- [numpy-2.5.2-cp313-cp313-win_amd64.whl](https://files.pythonhosted.org/packages/15/20/f3489f86d81ea460b2bcdceaed094142ca6579f6be0ec527b781d39afe68/numpy-2.5.2-cp313-cp313-win_amd64.whl)
- [pillow-12.3.0-cp313-cp313-win_amd64.whl](https://files.pythonhosted.org/packages/a6/9b/7a58e61d62be561da3a356fe2384d4059a6345fc130e23ef1c36a5b81d24/pillow-12.3.0-cp313-cp313-win_amd64.whl)

torch requires filelock, typing-extensions>=4.10.0, setuptools>=77.0.3, sympy>=1.13.3, networkx>=2.5.1, jinja2, and fsspec>=0.8.5. torchvision requires torch>=2.14.0, numpy, and pillow>=5.3.0 excluding 8.3.*. sympy requires mpmath; jinja2 requires MarkupSafe. This Windows resolution includes no separate NVIDIA CUDA wheels.

## Reproduce without installing

On an internet-connected machine, in PowerShell:

```powershell
python -m pip install --dry-run --ignore-installed --only-binary=:all: --platform win_amd64 --python-version 3.13 --implementation cp --abi cp313 --report torch-report.json torch==2.14.1+cu126 torchvision==0.29.1+cu126 --index-url https://download.pytorch.org/whl/cu126
(Get-Content -Raw torch-report.json | ConvertFrom-Json).install.download_info.url
```

`--ignore-installed` produces the full fresh-environment set. On a matching connected target environment, omit it and the target flags to account for already installed packages. Pip uses wheel tags, Requires-Python, and Requires-Dist metadata to resolve compatibility and recursive dependencies. Target flags do not fully emulate every environment marker; use a matching interpreter/OS for arbitrary package sets.

To download the complete set instead, replace `install --dry-run --ignore-installed` with `download --dest wheelhouse` and remove `--report torch-report.json`. Transfer the wheelhouse to the target, activate its Python 3.13 environment, then install:

```powershell
python -m pip install --no-index --find-links .\wheelhouse torch==2.14.1+cu126 torchvision==0.29.1+cu126
python -m pip check
```

Sources: [pip install report](https://pip.pypa.io/en/stable/cli/pip_install/), [pip download](https://pip.pypa.io/en/stable/cli/pip_download/), [torch index](https://download.pytorch.org/whl/cu126/torch/), [torchvision index](https://download.pytorch.org/whl/cu126/torchvision/).

## Downloaded bundle (2026-10-11)

Created the requested [ZIP bundle](C:/Users/alexr/.codex/visualizations/2026/10/11/01a128ee-c5ab-7653-94bd-172fa84c9644/pytorch-offline-win313-cu126.zip): 2,639,252,997 bytes, containing all 13 listed wheels under `wheelhouse/`, pinned `requirements.txt`, `README.txt`, `SHA256SUMS.txt`, and `manifest.json`. The extracted source files remain beside the ZIP in `pytorch-offline-win313-cu126/`.

Archive SHA-256: `95b8309dfdd439fd0a0a68a4775f3d56396176a6a7a5b25247d59bea3e2baee5`.

Verified wheel filenames exactly match the requested set; all wheel and final archive ZIP CRC checks passed. Compared the 10 publisher hashes available in the original pip report; all matched. Calculated SHA-256 for every wheel and the final ZIP. A fresh-environment pip dry run with `--no-index --find-links` resolved the complete pinned requirement set using only local files. No packages were installed. Runtime/GPU execution on the target remains untested.

After extraction, activate the target Python 3.13 environment and run from the extracted folder:

```powershell
python -m pip install --no-index --find-links .\wheelhouse -r requirements.txt
python -m pip check
```
