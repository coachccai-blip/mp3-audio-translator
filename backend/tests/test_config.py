from app.config import read_env_file


def test_env_inline_comments(tmp_path):
    p = tmp_path / ".env"
    p.write_text('A=            # commentaire\nB=azure     # azure | elevenlabs\nC="x # y"\n# D=1\nE=sk-ant-123\n')
    assert read_env_file(p) == {"A": "", "B": "azure", "C": "x # y", "E": "sk-ant-123"}
