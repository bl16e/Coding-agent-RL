from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


def _read_script(name: str) -> str:
    return (SCRIPTS / name).read_text(encoding="utf-8")


def test_stage1_script_targets_qwen_vllm_workflow():
    text = _read_script("run_stage1_qwen_vllm.sh")

    assert "coding-agent stage1 run-qwen-vllm" in text
    assert ".env.stage1" in text
    assert "Qwen2.5-Coder-7B-Instruct" in text
    assert "SWE-Bench Lite" in text
    assert "swesmith" not in text


def test_stage2_script_targets_teacher_trajectory_workflow():
    text = _read_script("run_stage2_teacher_trajectories.sh")

    assert "coding-agent stage2 generate-teacher-trajectories" in text
    assert ".env.stage2" in text
    assert "TEACHER_MODEL" in text
    assert "SWE_SMITH_REF" in text
    assert "swebench prepare" not in text


def test_sft_pipeline_script_is_stage2_wrapper_only():
    text = _read_script("run_sft_pipeline.sh")

    assert "run_stage2_teacher_trajectories.sh" in text
    assert "coding-agent swesmith run-subset" not in text
    assert "coding-agent swesmith create-subset" not in text


def test_deploy_script_creates_stage_specific_env_templates():
    text = _read_script("deploy.sh")

    assert ".env.stage1.example" in text
    assert ".env.stage2.example" in text
    assert "STAGE1_BASE_URL" in text
    assert "STAGE2_PROVIDER" in text
    assert "STAGE2_API_KEY" in text
    assert "https://api.deepseek.com" in text
    assert "deepseek-v4-pro" in text
    assert "run_stage1_qwen_vllm.sh" in text
    assert "run_stage2_teacher_trajectories.sh" in text


def test_stage2_env_example_documents_deepseek_teacher_config():
    text = (ROOT / ".env.stage2.example").read_text(encoding="utf-8")

    assert "STAGE2_PROVIDER=deepseek" in text
    assert "TEACHER_MODEL=deepseek-v4-pro" in text
    assert "STAGE2_MODEL=deepseek-v4-pro" in text
    assert "STAGE2_BASE_URL=https://api.deepseek.com" in text
