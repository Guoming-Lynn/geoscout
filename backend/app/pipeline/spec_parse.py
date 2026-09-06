from __future__ import annotations

import re

from app.schemas.spec import Criterion, ResearchSpec

ASSAY_PATTERNS = [
    (r"snrna|single[- ]nucleus|单核", "snrna_seq"),
    (r"scrna|single[- ]cell|单细胞", "scrna_seq"),
    (r"\bbulk\b|转录组测序", "bulk_rna_seq"),
]


def heuristic_parse(text: str) -> ResearchSpec:
    """Deterministic parse that never invents unspecified constraints."""
    spec = ResearchSpec(original_request=text)
    lower = text.lower()

    if re.search(r"小鼠|mouse|mus musculus", lower):
        spec.organisms.append("Mus musculus")
    if re.search(r"人|人类|human|homo sapiens", lower):
        spec.organisms.append("Homo sapiens")
    spec.organisms = list(dict.fromkeys(spec.organisms))

    for pattern, assay in ASSAY_PATTERNS:
        if re.search(pattern, lower) and assay not in spec.assay_types:
            if assay == "bulk_rna_seq" and any(x in spec.assay_types for x in ("scrna_seq", "snrna_seq")):
                continue
            spec.assay_types.append(assay)  # type: ignore[arg-type]

    if re.search(r"动脉粥样硬化|atherosclerosis|atheroma", lower):
        spec.disease.append("atherosclerosis")
    if re.search(r"颈动脉|carotid", lower):
        spec.tissues.append("carotid")
    if re.search(r"主动脉|aorta|aortic", lower):
        spec.tissues.append("artery")
    if re.search(r"斑块|plaque", lower):
        spec.tissues.append("plaque")

    if re.search(r"病变|lesion|disease", lower) and re.search(r"对照|control|healthy|adjacent", lower):
        spec.required_groups = ["lesion", "control"]

    donor = re.search(r"(?:每组|each group|per group)[^\d]{0,8}(\d+)", lower)
    if donor:
        spec.minimum_donors_per_group = int(donor.group(1))
    else:
        donor2 = re.search(r"(?:至少|at least)[^\d]{0,8}(\d+)[^\d]{0,6}(?:donor|供体|人|例)", lower)
        if donor2:
            spec.minimum_donors_per_group = int(donor2.group(1))
            spec.unresolved_questions.append("最少供体数是按每组还是总计，原文未写明。")

    if re.search(r"年龄|age", lower):
        spec.preferred_metadata.append("age")
    if re.search(r"性别|sex|gender", lower):
        spec.preferred_metadata.append("sex")
    if re.search(r"处理后矩阵|processed matrix|h5ad|count matrix", lower):
        spec.processed_matrix_requirement = "preferred"
        if re.search(r"必须|必须有|required", lower):
            spec.processed_matrix_requirement = "required"

    _fill_criteria(spec)
    return spec


def _fill_criteria(spec: ResearchSpec) -> None:
    items: list[Criterion] = []
    if spec.organisms:
        items.append(
            Criterion(
                criterion_id="organism",
                field="organism",
                description="物种必须匹配",
                user_text=" / ".join(spec.organisms),
                priority="hard",
                value=spec.organisms,
            )
        )
    if spec.assay_types:
        items.append(
            Criterion(
                criterion_id="assay",
                field="assay",
                description="实验技术必须匹配",
                user_text=" / ".join(spec.assay_types),
                priority="hard",
                value=spec.assay_types,
            )
        )
    if spec.disease:
        items.append(
            Criterion(
                criterion_id="disease",
                field="disease",
                description="疾病相关",
                user_text=" / ".join(spec.disease),
                priority="hard",
                value=spec.disease,
            )
        )
    if spec.tissues:
        items.append(
            Criterion(
                criterion_id="tissue",
                field="tissue",
                description="组织相关；样本描述中可能才出现",
                user_text=" / ".join(spec.tissues),
                priority="soft",
                value=spec.tissues,
            )
        )
    if spec.required_groups:
        items.append(
            Criterion(
                criterion_id="groups",
                field="groups",
                description="需要的实验分组",
                user_text=" / ".join(spec.required_groups),
                priority="hard",
                value=spec.required_groups,
            )
        )
    if spec.minimum_donors_per_group:
        items.append(
            Criterion(
                criterion_id="donors_per_group",
                field="donors",
                description="每组最少独立供体",
                user_text=str(spec.minimum_donors_per_group),
                priority="hard",
                value=spec.minimum_donors_per_group,
            )
        )
    for field in spec.preferred_metadata:
        items.append(
            Criterion(
                criterion_id=f"meta_{field}",
                field=field,
                description=f"最好包含 {field}；GEO 未写不等于数据没有",
                user_text=field,
                priority="soft",
                value=field,
            )
        )
    if spec.processed_matrix_requirement != "none":
        items.append(
            Criterion(
                criterion_id="processed_matrix",
                field="processed_matrix",
                description="处理后矩阵",
                user_text=spec.processed_matrix_requirement,
                priority="hard" if spec.processed_matrix_requirement == "required" else "soft",
                value=spec.processed_matrix_requirement,
            )
        )
    spec.inclusion_criteria = items


def merge_model_parse(base: ResearchSpec, payload: dict) -> ResearchSpec:
    data = base.model_dump()
    for key in (
        "disease",
        "tissues",
        "organisms",
        "assay_types",
        "required_groups",
        "required_metadata",
        "preferred_metadata",
        "unresolved_questions",
    ):
        extra = payload.get(key)
        if isinstance(extra, list):
            merged = list(data.get(key) or [])
            for item in extra:
                if item not in merged:
                    merged.append(item)
            data[key] = merged
    if payload.get("minimum_donors_per_group") and not data.get("minimum_donors_per_group"):
        data["minimum_donors_per_group"] = payload["minimum_donors_per_group"]
    if payload.get("processed_matrix_requirement"):
        data["processed_matrix_requirement"] = payload["processed_matrix_requirement"]
    spec = ResearchSpec.model_validate(data)
    _fill_criteria(spec)
    return spec
