from app.pipeline.screening import classify, rule_judgements
from app.pipeline.spec_parse import heuristic_parse


def test_txt_filename_is_clue_not_matrix_pass():
    spec = heuristic_parse("human scRNA-seq 必须有处理后矩阵")
    judgements = rule_judgements(spec, {"taxon": "Homo sapiens", "title": "x", "summary": "single-cell RNA sequencing", "gdstype": "Expression profiling by high throughput sequencing", "suppfile": "TXT"}, [])
    matrix = next(j for j in judgements if j.criterion_id == "processed_matrix")
    assert matrix.verdict == "unknown"
    assert matrix.clue_only


def test_high_throughput_without_bulk_word_is_not_bulk_pass():
    spec = heuristic_parse("human bulk RNA-seq")
    judgements = rule_judgements(
        spec,
        {
            "taxon": "Homo sapiens",
            "title": "RNA-seq of blood",
            "summary": "Expression profiling by high throughput sequencing of blood.",
            "gdstype": "Expression profiling by high throughput sequencing",
        },
        [],
    )
    assay = next(j for j in judgements if j.criterion_id == "assay")
    assert assay.verdict == "unknown"


def test_mixed_bulk_and_scrna_stays_unknown():
    spec = heuristic_parse("human bulk RNA-seq")
    judgements = rule_judgements(
        spec,
        {
            "taxon": "Homo sapiens",
            "title": "bulk and single-cell atlas",
            "summary": "We generated bulk RNA-seq and single-cell RNA sequencing.",
            "gdstype": "Expression profiling by high throughput sequencing",
        },
        [],
    )
    assay = next(j for j in judgements if j.criterion_id == "assay")
    assert assay.verdict == "unknown"
    cat, _ = classify(spec, judgements, verified=True, conflict=False, model_invalid=False)
    assert cat != "excluded"


def test_macrophage_does_not_count_as_age():
    spec = heuristic_parse("人类单细胞，最好包含年龄")
    samples = [
        {
            "gsm": "GSM1",
            "organism": "Homo sapiens",
            "characteristics": [{"key": "cell type", "value": "macrophage", "raw": "cell type: macrophage"}],
        }
    ]
    judgements = rule_judgements(
        spec,
        {"taxon": "Homo sapiens", "title": "macrophage", "summary": "single-cell RNA sequencing of macrophage", "gdstype": "Expression profiling by high throughput sequencing"},
        samples,
    )
    age = next(j for j in judgements if j.criterion_id == "meta_age")
    assert age.verdict == "unknown"


def test_mixed_species_cannot_pass_as_whole_study():
    spec = heuristic_parse("human scRNA-seq")
    samples = [
        {"gsm": "GSM1", "organism": "Homo sapiens", "characteristics": []},
        {"gsm": "GSM2", "organism": "Mus musculus", "characteristics": []},
    ]
    judgements = rule_judgements(
        spec,
        {"taxon": "Homo sapiens; Mus musculus", "title": "cross-species", "summary": "single-cell RNA sequencing", "gdstype": "Expression profiling by high throughput sequencing"},
        samples,
    )
    org = next(j for j in judgements if j.criterion_id == "organism")
    assert org.verdict == "unknown"
    assert org.qualifying_gsms
    cat, _ = classify(spec, judgements, verified=True, conflict=False, model_invalid=False)
    assert cat != "recommended"
