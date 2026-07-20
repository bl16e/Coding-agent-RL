from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import re
from typing import AbstractSet

from coding_agent.models import AdaptedTestSpec


logger = logging.getLogger(__name__)


class MissingRuntimeImagesError(ValueError):
    """Raised when required runtime images are absent and builds are not allowed."""


@dataclass(frozen=True)
class ImageGraphPlan:
    ordered_image_keys: tuple[str, str, str]
    reused_images: tuple[str, ...]
    missing_images: tuple[str, ...]
    build_missing: bool


AUDIT_SOURCE_REFERENCE = "specs/003-agent-runtime-refactor/runtime-image-audit.md"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _audit_path() -> Path:
    return _project_root() / AUDIT_SOURCE_REFERENCE


def _parse_env_image_keys(audit_text: str) -> dict[tuple[str, str], str]:
    result: dict[tuple[str, str], str] = {}
    for line in audit_text.splitlines():
        match = re.match(r"\| `(sweb\.env\.[^`]+)` \| \d+ \| (.+) \|", line)
        if not match:
            continue
        image_key = match.group(1)
        coverage = match.group(2)
        for repo, version in re.findall(r"`([^`@]+)@([^`]+)`", coverage):
            result[(repo, version)] = image_key
    return result


def audit_env_image_key(repo: str, version: str, *, audit_path: Path | None = None) -> str:
    path = audit_path or _audit_path()
    if not path.is_file():
        raise MissingRuntimeImagesError(f"runtime image audit is missing: {path}")
    mapping = _parse_env_image_keys(path.read_text(encoding="utf-8"))
    try:
        return mapping[(repo, version)]
    except KeyError as exc:
        raise MissingRuntimeImagesError(f"missing env image key for {repo}@{version}") from exc


def derive_base_image_key(*, language: str, arch: str = "x86_64") -> str:
    return f"sweb.base.{language}.{arch}:latest"


def derive_instance_image_key(*, instance_id: str, arch: str = "x86_64") -> str:
    return f"sweb.eval.{arch}.{instance_id.lower()}:latest"


def plan_image_graph(
    testspec: AdaptedTestSpec,
    *,
    existing_images: AbstractSet[str],
    build_missing: bool,
) -> ImageGraphPlan:
    ordered = (testspec.base_image_key, testspec.env_image_key, testspec.instance_image_key)
    reused = tuple(image for image in ordered if image in existing_images)
    missing = tuple(image for image in ordered if image not in existing_images)
    if missing and not build_missing:
        raise MissingRuntimeImagesError("missing runtime images: " + ", ".join(missing))
    return ImageGraphPlan(
        ordered_image_keys=ordered,
        reused_images=reused,
        missing_images=missing,
        build_missing=build_missing,
    )


def inspect_image_graph(testspec: AdaptedTestSpec, *, docker, build_missing: bool) -> ImageGraphPlan:
    logger.info("checking runtime image graph: instance_id=%s build_missing=%s", testspec.instance_id, build_missing)
    existing = {
        image
        for image in (testspec.base_image_key, testspec.env_image_key, testspec.instance_image_key)
        if docker.image_exists(image)
    }
    plan = plan_image_graph(testspec, existing_images=existing, build_missing=build_missing)
    logger.info(
        "runtime image graph resolved: instance_id=%s reused=%s missing=%s",
        testspec.instance_id,
        list(plan.reused_images),
        list(plan.missing_images),
    )
    return plan


def base_dockerfile(testspec: AdaptedTestSpec) -> str:
    docker_specs = {
        "ubuntu_version": "22.04",
        "conda_version": "py311_23.11.0-2",
        "conda_arch": "x86_64",
        **getattr(testspec, "docker_specs", {}),
    }
    return "\n".join(
        [
            f"FROM --platform={testspec.platform} ubuntu:{docker_specs['ubuntu_version']}",
            "",
            "ARG DEBIAN_FRONTEND=noninteractive",
            "ENV TZ=Etc/UTC",
            "",
            "RUN apt update && apt install -y \\",
            "wget \\",
            "git \\",
            "build-essential \\",
            "libffi-dev \\",
            "libtiff-dev \\",
            "python3 \\",
            "python3-pip \\",
            "python-is-python3 \\",
            "jq \\",
            "curl \\",
            "locales \\",
            "locales-all \\",
            "tzdata \\",
            "&& rm -rf /var/lib/apt/lists/*",
            "",
            "RUN wget 'https://repo.anaconda.com/miniconda/Miniconda3-"
            f"{docker_specs['conda_version']}-Linux-{docker_specs['conda_arch']}.sh' -O miniconda.sh \\",
            "    && bash miniconda.sh -b -p /opt/miniconda3",
            "ENV PATH=/opt/miniconda3/bin:$PATH",
            "RUN conda init --all",
            "RUN conda config --append channels conda-forge",
            "",
            "RUN adduser --disabled-password --gecos 'dog' nonroot",
            "",
        ]
    )


def env_dockerfile(testspec: AdaptedTestSpec) -> str:
    return "\n".join(
        [
            f"FROM --platform={testspec.platform} {testspec.base_image_key}",
            'SHELL ["/bin/bash", "-lc"]',
            "RUN cat > /tmp/setup_env.sh <<'EOF_ENV'",
            testspec.env_script,
            "EOF_ENV",
            "RUN chmod +x /tmp/setup_env.sh",
            'RUN /bin/bash -c "source ~/.bashrc && /tmp/setup_env.sh"',
            "WORKDIR /testbed/",
            'RUN echo "source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed" > /root/.bashrc',
            "",
        ]
    )


def instance_dockerfile(testspec: AdaptedTestSpec) -> str:
    return "\n".join(
        [
            f"FROM --platform={testspec.platform} {testspec.env_image_key}",
            'SHELL ["/bin/bash", "-lc"]',
            "RUN cat > /tmp/setup_repo.sh <<'EOF_REPO'",
            testspec.repo_script,
            "EOF_REPO",
            "RUN bash /tmp/setup_repo.sh",
            "WORKDIR /testbed/",
            "RUN cat > /opt/swebench_eval.sh <<'EOF_EVAL'",
            testspec.eval_script,
            "EOF_EVAL",
            "RUN chmod +x /opt/swebench_eval.sh",
            "",
        ]
    )


def build_missing_images(testspec: AdaptedTestSpec, *, docker, plan: ImageGraphPlan) -> tuple[str, ...]:
    built: list[str] = []
    dockerfiles = {
        testspec.base_image_key: base_dockerfile(testspec),
        testspec.env_image_key: env_dockerfile(testspec),
        testspec.instance_image_key: instance_dockerfile(testspec),
    }
    for image in plan.ordered_image_keys:
        if image not in plan.missing_images:
            continue
        logger.info("docker image build started: image=%s instance_id=%s", image, testspec.instance_id)
        docker.build_image(image=image, dockerfile=dockerfiles[image], context=".")
        logger.info("docker image build completed: image=%s instance_id=%s", image, testspec.instance_id)
        built.append(image)
    return tuple(built)
