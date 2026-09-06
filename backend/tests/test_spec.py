from app.pipeline.spec_parse import heuristic_parse


def test_hard_soft_and_unknowns():
    spec = heuristic_parse("找人类动脉粥样硬化单细胞数据，要病变和对照，至少每组 3 位供体，最好包含年龄和性别，有处理后矩阵。")
    assert "Homo sapiens" in spec.organisms
    assert "scrna_seq" in spec.assay_types
    assert spec.minimum_donors_per_group == 3
    assert "age" in spec.preferred_metadata
    ids = {c.criterion_id: c.priority for c in spec.inclusion_criteria}
    assert ids["organism"] == "hard"
    assert ids["meta_age"] == "soft"


def test_does_not_invent_tissue():
    spec = heuristic_parse("human bulk RNA-seq of influenza")
    assert spec.tissues == []
    assert spec.original_request.startswith("human")
