from app.core.config import Settings


def test_demo_requires_explicit_flags():
    s = Settings(allow_demo=False, demo_mode=False)
    assert not s.demo_allowed()
    s2 = Settings(allow_demo=True, demo_mode=True)
    assert s2.demo_allowed()
    s3 = Settings(allow_demo=True, demo_mode=False)
    assert not s3.demo_allowed()
