from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_readme_documents_stage_boundary_and_entrypoints():
    text = _read("README.md")

    assert "Stage 1" in text
    assert "Stage 2" in text
    assert "run_stage1_qwen_vllm.sh" in text
    assert "run_stage2_teacher_trajectories.sh" in text
    assert "Qwen2.5-Coder-7B-Instruct" in text
    assert "teacher model API" in text


def test_cost_guide_uses_stage_scripts_and_separate_env_files():
    text = _read("docs/cost_optimized_two_stage_deployment.md")

    assert ".env.stage1" in text
    assert ".env.stage2" in text
    assert "run_stage1_qwen_vllm.sh" in text
    assert "run_stage2_teacher_trajectories.sh" in text
    assert "coding-agent swebench batch-run" not in text
    assert "./scripts/run_sft_pipeline.sh" not in text


def test_swesmith_guide_is_stage2_teacher_only():
    text = _read("docs/swesmith_sft_pipeline_guide.md")

    assert "Stage 2" in text
    assert "teacher model API" in text
    assert "run_stage2_teacher_trajectories.sh" in text
    assert ".env.stage2" in text
    assert "Qwen2.5-Coder-7B-Instruct" not in text
    assert "SWE-Bench Lite" not in text
