# Runtime Image Audit: SWE-Bench Lite Data

This audit records the source-backed runtime image inventory for the local
SWE-Bench Lite parquet files under `data/`. The image keys are not stored
directly in the parquet files; they are derived from each dataset row using the
local upstream SWE-Bench harness reference.

## Source Inputs

| Source | Role | Review status |
|--------|------|---------------|
| `data/dev-00000-of-00001.parquet` | SWE-Bench Lite development rows | source_backed |
| `data/test-00000-of-00001.parquet` | SWE-Bench Lite test rows | source_backed |
| `SWE-bench/swebench/harness/test_spec/test_spec.py` | `TestSpec` image-key generation rules | source_backed |
| `SWE-bench/swebench/harness/constants/__init__.py` | `MAP_REPO_TO_EXT` and merged repo/version specs | source_backed |
| `SWE-bench/swebench/harness/constants/python.py` | Python repo/version environment metadata | source_backed |
| `SWE-bench/swebench/harness/test_spec/python.py` | Python repo/env/eval script construction | source_backed |

## Extraction Result

| Metric | Value |
|--------|-------|
| Dataset rows checked | 323 |
| Rows with generated image keys | 323 |
| Generation failures | 0 |
| Dataset files | `data/dev-00000-of-00001.parquet` (23 rows), `data/test-00000-of-00001.parquet` (300 rows) |
| Repositories | 18 |
| Repo/version pairs | 81 |
| Unique base image keys | 1 |
| Unique env image keys | 45 |
| Unique instance image keys | 323 |
| Architecture used by upstream default | `x86_64` |
| Platform used by upstream default | `linux/x86_64` |
| Image tag used by upstream default | `latest` |

## Image-Key Rules

Rules are copied conceptually from `TestSpec` properties in
`SWE-bench/swebench/harness/test_spec/test_spec.py`.

| Layer | Rule |
|-------|------|
| Base Image | `sweb.base.{MAP_REPO_TO_EXT[repo]}.{arch}:{base_image_tag}` when `docker_specs` is empty; include a 10-character `docker_specs` hash before the tag when `docker_specs` is non-empty. |
| Env Image | `sweb.env.{MAP_REPO_TO_EXT[repo]}.{arch}.{sha256(env_script_list + docker_specs)[:22]}:{env_image_tag}`. |
| Instance Image | `sweb.eval.{arch}.{instance_id.lower()}:{instance_image_tag}`. Remote namespace mode is out of scope for the local default path. |

For the current local SWE-Bench Lite data and upstream default arguments,
all rows use Python repository specs with empty base `docker_specs`, so the
single base image key is:

```text
sweb.base.py.x86_64:latest
```

## Supported Repository Versions

| Repo | Version | Rows |
|------|---------|------|
| `astropy/astropy` | `1.3` | 2 |
| `astropy/astropy` | `4.3` | 1 |
| `astropy/astropy` | `5.1` | 2 |
| `astropy/astropy` | `5.2` | 1 |
| `django/django` | `3.0` | 15 |
| `django/django` | `3.1` | 21 |
| `django/django` | `3.2` | 20 |
| `django/django` | `4.0` | 19 |
| `django/django` | `4.1` | 14 |
| `django/django` | `4.2` | 16 |
| `django/django` | `5.0` | 9 |
| `marshmallow-code/marshmallow` | `2.20` | 1 |
| `marshmallow-code/marshmallow` | `3.0` | 1 |
| `matplotlib/matplotlib` | `3.3` | 1 |
| `matplotlib/matplotlib` | `3.5` | 7 |
| `matplotlib/matplotlib` | `3.6` | 8 |
| `matplotlib/matplotlib` | `3.7` | 7 |
| `mwaskom/seaborn` | `0.12` | 3 |
| `mwaskom/seaborn` | `0.13` | 1 |
| `pallets/flask` | `2.0` | 1 |
| `pallets/flask` | `2.3` | 2 |
| `psf/requests` | `0.14` | 1 |
| `psf/requests` | `2.10` | 1 |
| `psf/requests` | `2.3` | 2 |
| `psf/requests` | `2.4` | 1 |
| `psf/requests` | `2.7` | 1 |
| `pvlib/pvlib-python` | `0.7` | 1 |
| `pvlib/pvlib-python` | `0.8` | 2 |
| `pvlib/pvlib-python` | `0.9` | 2 |
| `pydata/xarray` | `0.12` | 5 |
| `pydicom/pydicom` | `1.3` | 1 |
| `pydicom/pydicom` | `2.0` | 1 |
| `pydicom/pydicom` | `2.1` | 2 |
| `pydicom/pydicom` | `2.3` | 1 |
| `pylint-dev/astroid` | `2.10` | 1 |
| `pylint-dev/astroid` | `2.12` | 1 |
| `pylint-dev/astroid` | `2.13` | 1 |
| `pylint-dev/astroid` | `2.14` | 1 |
| `pylint-dev/astroid` | `2.9` | 1 |
| `pylint-dev/pylint` | `2.13` | 1 |
| `pylint-dev/pylint` | `2.14` | 1 |
| `pylint-dev/pylint` | `2.15` | 4 |
| `pytest-dev/pytest` | `4.4` | 2 |
| `pytest-dev/pytest` | `4.5` | 1 |
| `pytest-dev/pytest` | `4.6` | 2 |
| `pytest-dev/pytest` | `5.0` | 1 |
| `pytest-dev/pytest` | `5.2` | 1 |
| `pytest-dev/pytest` | `5.4` | 4 |
| `pytest-dev/pytest` | `6.0` | 1 |
| `pytest-dev/pytest` | `6.3` | 1 |
| `pytest-dev/pytest` | `7.0` | 2 |
| `pytest-dev/pytest` | `8.0` | 2 |
| `pyvista/pyvista` | `0.39` | 1 |
| `scikit-learn/scikit-learn` | `0.20` | 5 |
| `scikit-learn/scikit-learn` | `0.21` | 7 |
| `scikit-learn/scikit-learn` | `0.22` | 7 |
| `scikit-learn/scikit-learn` | `1.3` | 4 |
| `sphinx-doc/sphinx` | `3.1` | 2 |
| `sphinx-doc/sphinx` | `3.2` | 1 |
| `sphinx-doc/sphinx` | `3.3` | 2 |
| `sphinx-doc/sphinx` | `3.4` | 3 |
| `sphinx-doc/sphinx` | `3.5` | 4 |
| `sphinx-doc/sphinx` | `4.0` | 1 |
| `sphinx-doc/sphinx` | `5.0` | 1 |
| `sphinx-doc/sphinx` | `5.1` | 1 |
| `sphinx-doc/sphinx` | `7.1` | 1 |
| `sqlfluff/sqlfluff` | `0.6` | 4 |
| `sqlfluff/sqlfluff` | `0.8` | 1 |
| `sympy/sympy` | `1.0` | 7 |
| `sympy/sympy` | `1.1` | 19 |
| `sympy/sympy` | `1.10` | 2 |
| `sympy/sympy` | `1.11` | 3 |
| `sympy/sympy` | `1.12` | 4 |
| `sympy/sympy` | `1.13` | 1 |
| `sympy/sympy` | `1.2` | 1 |
| `sympy/sympy` | `1.4` | 7 |
| `sympy/sympy` | `1.5` | 7 |
| `sympy/sympy` | `1.6` | 9 |
| `sympy/sympy` | `1.7` | 6 |
| `sympy/sympy` | `1.8` | 5 |
| `sympy/sympy` | `1.9` | 6 |

## Env Image Inventory

| Env image key | Rows | Repo/version coverage |
|---------------|------|-----------------------|
| `sweb.env.py.x86_64.088a7e628bda9770f9757b:latest` | 2 | `pytest-dev/pytest@4.6` |
| `sweb.env.py.x86_64.0d775eb35b541495295791:latest` | 1 | `matplotlib/matplotlib@3.3` |
| `sweb.env.py.x86_64.0d80c7dec81ee2f2f513e2:latest` | 1 | `sympy/sympy@1.13` |
| `sweb.env.py.x86_64.0f99bce2750f3109957bec:latest` | 2 | `pytest-dev/pytest@8.0` |
| `sweb.env.py.x86_64.1c1a6945f732f9391228c5:latest` | 2 | `pytest-dev/pytest@5.0`, `pytest-dev/pytest@5.2` |
| `sweb.env.py.x86_64.1cf2a749a12b4261fa2fc2:latest` | 2 | `pydicom/pydicom@2.1` |
| `sweb.env.py.x86_64.1f92e6d7cef88badc4f744:latest` | 6 | `psf/requests@0.14`, `psf/requests@2.10`, `psf/requests@2.3`, `psf/requests@2.4`, `psf/requests@2.7` |
| `sweb.env.py.x86_64.257e69677081e19b89fe2d:latest` | 5 | `pvlib/pvlib-python@0.7`, `pvlib/pvlib-python@0.8`, `pvlib/pvlib-python@0.9` |
| `sweb.env.py.x86_64.297af196949a2a635bce66:latest` | 19 | `django/django@4.0` |
| `sweb.env.py.x86_64.2baaea72acc974f6c02079:latest` | 15 | `django/django@3.0` |
| `sweb.env.py.x86_64.2f217c8b4490bfa0e2ba14:latest` | 2 | `marshmallow-code/marshmallow@2.20`, `marshmallow-code/marshmallow@3.0` |
| `sweb.env.py.x86_64.31244378a92e3bcce809ac:latest` | 8 | `matplotlib/matplotlib@3.6` |
| `sweb.env.py.x86_64.32fbc81549fb4df7641b77:latest` | 1 | `sqlfluff/sqlfluff@0.8` |
| `sweb.env.py.x86_64.3a59860bcd0dab8bbfb2ff:latest` | 4 | `scikit-learn/scikit-learn@1.3` |
| `sweb.env.py.x86_64.428468730904ff6b4232aa:latest` | 4 | `astropy/astropy@4.3`, `astropy/astropy@5.1`, `astropy/astropy@5.2` |
| `sweb.env.py.x86_64.502d8fc6ebccd881244091:latest` | 5 | `pydata/xarray@0.12` |
| `sweb.env.py.x86_64.5d1fda9d55d65d8a4e5bdb:latest` | 4 | `pytest-dev/pytest@5.4` |
| `sweb.env.py.x86_64.5e79cff8ad12d8ccd4d80b:latest` | 1 | `pylint-dev/pylint@2.13` |
| `sweb.env.py.x86_64.6b135cdb7d820605dd6766:latest` | 4 | `sqlfluff/sqlfluff@0.6` |
| `sweb.env.py.x86_64.6cf8a599aa20403f2c6e0a:latest` | 1 | `pydicom/pydicom@2.3` |
| `sweb.env.py.x86_64.6e512457d345cc593ea700:latest` | 1 | `pylint-dev/pylint@2.14` |
| `sweb.env.py.x86_64.7037e8c448a4b8ebfe9b13:latest` | 7 | `matplotlib/matplotlib@3.5` |
| `sweb.env.py.x86_64.71498c7426dbf05599642f:latest` | 2 | `pytest-dev/pytest@4.4` |
| `sweb.env.py.x86_64.756beac07713d7e8dc1129:latest` | 1 | `pytest-dev/pytest@4.5` |
| `sweb.env.py.x86_64.764c21123474adcba1e003:latest` | 16 | `sphinx-doc/sphinx@3.1`, `sphinx-doc/sphinx@3.2`, `sphinx-doc/sphinx@3.3`, `sphinx-doc/sphinx@3.4`, `sphinx-doc/sphinx@3.5`, `sphinx-doc/sphinx@4.0`, `sphinx-doc/sphinx@5.0`, `sphinx-doc/sphinx@5.1`, `sphinx-doc/sphinx@7.1` |
| `sweb.env.py.x86_64.883a7978acf7bc63b8e5b5:latest` | 1 | `pydicom/pydicom@1.3` |
| `sweb.env.py.x86_64.8f1f7b974f0c57c7aeba39:latest` | 1 | `pytest-dev/pytest@6.3` |
| `sweb.env.py.x86_64.934a137824256b612e9dc5:latest` | 14 | `django/django@4.1` |
| `sweb.env.py.x86_64.a0efca7a0fe6719dbf65c2:latest` | 4 | `mwaskom/seaborn@0.12`, `mwaskom/seaborn@0.13` |
| `sweb.env.py.x86_64.a18371b03f944585b4f08c:latest` | 21 | `django/django@3.1` |
| `sweb.env.py.x86_64.a33dddf55cdff5d8e23374:latest` | 16 | `django/django@4.2` |
| `sweb.env.py.x86_64.aa92880033da20ca313928:latest` | 19 | `scikit-learn/scikit-learn@0.20`, `scikit-learn/scikit-learn@0.21`, `scikit-learn/scikit-learn@0.22` |
| `sweb.env.py.x86_64.b7ce4be3b3c35f68c61248:latest` | 2 | `pytest-dev/pytest@7.0` |
| `sweb.env.py.x86_64.c70909fdac4897d1c685df:latest` | 9 | `django/django@5.0` |
| `sweb.env.py.x86_64.c70974ae7654c7a2c98577:latest` | 2 | `astropy/astropy@1.3` |
| `sweb.env.py.x86_64.c795f4b88616b8462021ed:latest` | 76 | `sympy/sympy@1.0`, `sympy/sympy@1.1`, `sympy/sympy@1.10`, `sympy/sympy@1.11`, `sympy/sympy@1.12`, `sympy/sympy@1.2`, `sympy/sympy@1.4`, `sympy/sympy@1.5`, `sympy/sympy@1.6`, `sympy/sympy@1.7`, `sympy/sympy@1.8`, `sympy/sympy@1.9` |
| `sweb.env.py.x86_64.cc47cc71483942d0c3a15e:latest` | 1 | `pytest-dev/pytest@6.0` |
| `sweb.env.py.x86_64.cca6c53993ff45ca8048d3:latest` | 4 | `pylint-dev/pylint@2.15` |
| `sweb.env.py.x86_64.d13cdf3c18bec0743c2ba2:latest` | 1 | `pallets/flask@2.0` |
| `sweb.env.py.x86_64.d2e9d1be25afa81e65e68c:latest` | 1 | `pyvista/pyvista@0.39` |
| `sweb.env.py.x86_64.d8000bec0a7bf656e851aa:latest` | 2 | `pallets/flask@2.3` |
| `sweb.env.py.x86_64.e10d470400e85820f705a6:latest` | 1 | `pydicom/pydicom@2.0` |
| `sweb.env.py.x86_64.e83e37f52c09532c62acfb:latest` | 20 | `django/django@3.2` |
| `sweb.env.py.x86_64.efa6065ed5bf204410fd53:latest` | 7 | `matplotlib/matplotlib@3.7` |
| `sweb.env.py.x86_64.fe8326858e7fdc7d50d1e5:latest` | 5 | `pylint-dev/astroid@2.10`, `pylint-dev/astroid@2.12`, `pylint-dev/astroid@2.13`, `pylint-dev/astroid@2.14`, `pylint-dev/astroid@2.9` |

## Instance Image Inventory Rule

There are 323 unique instance image keys, one per dataset row. They are
auditable without a static lookup table because each key is generated directly
from `instance_id`:

```text
instance_image_key = "sweb.eval.x86_64." + instance_id.lower() + ":latest"
```

Examples:

| Instance id | Instance image key |
|-------------|--------------------|
| `astropy__astropy-12907` | `sweb.eval.x86_64.astropy__astropy-12907:latest` |
| `django__django-11099` | `sweb.eval.x86_64.django__django-11099:latest` |
| `pytest-dev__pytest-10482` | `sweb.eval.x86_64.pytest-dev__pytest-10482:latest` |
| `sympy__sympy-24909` | `sweb.eval.x86_64.sympy__sympy-24909:latest` |

Implementation MUST compute instance image keys from the selected task record
instead of storing a fixed per-instance table.

## Implementation Constraints

- Production code MUST compute image keys from dataset rows and source-backed
  repo/version metadata.
- Production code MUST NOT branch on fixture task IDs, expected test outputs,
  or the current 323-row dataset shape.
- The env image inventory above is an audit baseline for the current local
  data, not a replacement for the source-backed env-script hashing rule.
- Unknown repo/version pairs or pairs missing upstream specs MUST fail before
  agent execution with a missing source-backed metadata message.
