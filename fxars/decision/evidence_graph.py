"""گراف شواهد — بخش ۵-۲ سند تکمیلی ۱.۱.

به‌جای فهرست خطی، هر تحلیل یک گراف از گره‌های داده، ویژگی، ماژول، شاهد و
تصمیم می‌سازد. گراف امکان شناسایی «شواهد هم‌بسته» و حذف وزن‌دهی چندباره
شواهد تکراری را فراهم می‌کند.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from fxars.config.decision import EvidencePolicy
from fxars.core.hashing import sha256_obj
from fxars.core.timeutil import format_ts
from fxars.domain.enums import Direction
from fxars.domain.models import Decision, Evidence

NODE_DATA = "DATA"
NODE_FEATURE = "FEATURE"
NODE_MODULE = "MODULE"
NODE_EVIDENCE = "EVIDENCE"
NODE_DECISION = "DECISION"


@dataclass(frozen=True)
class GraphNode:
    node_id: str
    kind: str
    label: str
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "kind": self.kind,
            "label": self.label,
            "attributes": self.attributes,
        }


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    relation: str
    weight: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "relation": self.relation,
            "weight": round(self.weight, 4),
        }


@dataclass(frozen=True)
class EvidenceGraph:
    graph_id: str
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    clusters: dict[str, tuple[str, ...]]
    redundant_ids: tuple[str, ...]
    generated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "clusters": {key: list(value) for key, value in self.clusters.items()},
            "redundant_ids": list(self.redundant_ids),
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "generated_at": format_ts(self.generated_at) if self.generated_at else None,
        }


def _evidence_key(evidence: Evidence) -> tuple[str, str, str, datetime, str]:
    return (
        evidence.module_id,
        evidence.family.value,
        evidence.direction.value,
        evidence.observed_at,
        evidence.parameters_hash,
    )


def redundant_evidence(
    evidences: Iterable[Evidence], policy: EvidencePolicy | None = None
) -> list[str]:
    """شناسه شواهدی که تکرار معنایی یک شاهد قوی‌تر هستند.

    تکراری یعنی همان ماژول/خانواده/جهت/زمان مشاهده/پارامتر. این حالت در عمل
    فقط با ورود مضاعف یا بازاجرای همان ماژول رخ می‌دهد و باید یک‌بار وزن بگیرد.
    """
    policy = policy or EvidencePolicy()
    ordered = sorted(evidences, key=lambda item: (item.evidence_id,))
    ordered.sort(key=lambda item: float(item.strength), reverse=True)
    seen: set[tuple] = set()
    redundant: list[str] = []
    for evidence in ordered:
        key = _evidence_key(evidence)
        if key in seen:
            redundant.append(evidence.evidence_id)
        else:
            seen.add(key)
    return redundant


def build_evidence_graph(
    evidences: Iterable[Evidence],
    *,
    decision: Decision | None = None,
    analysis_run_id: str = "",
    rules_version: str = "",
    model_versions: dict[str, str] | None = None,
    policy: EvidencePolicy | None = None,
    generated_at: datetime | None = None,
) -> EvidenceGraph:
    policy = policy or EvidencePolicy()
    items = list(evidences)
    redundant = set(redundant_evidence(items, policy))
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []

    def add_node(node: GraphNode) -> None:
        nodes.setdefault(node.node_id, node)

    for evidence in items:
        if evidence.evidence_id in redundant:
            continue
        evidence_node = f"ev:{evidence.evidence_id}"
        add_node(
            GraphNode(
                node_id=evidence_node,
                kind=NODE_EVIDENCE,
                label=evidence.module_id,
                attributes={
                    "family": evidence.family.value,
                    "direction": evidence.direction.value,
                    "strength": round(float(evidence.strength), 4),
                    "confidence": round(float(evidence.confidence_raw), 4),
                    "available_at": format_ts(evidence.available_at),
                    "parameters_hash": evidence.parameters_hash,
                },
            )
        )
        module_node = f"mod:{evidence.module_id}@{evidence.module_version}"
        add_node(
            GraphNode(
                node_id=module_node,
                kind=NODE_MODULE,
                label=evidence.module_id,
                attributes={"version": evidence.module_version, "family": evidence.family.value},
            )
        )
        edges.append(GraphEdge(module_node, evidence_node, "produces", float(evidence.strength)))
        for ref in evidence.source_refs:
            data_node = f"data:{ref}"
            add_node(GraphNode(node_id=data_node, kind=NODE_DATA, label=ref))
            edges.append(GraphEdge(data_node, evidence_node, "supports", 1.0))
        if evidence.price_zone is not None:
            feature_node = f"feat:{evidence.module_id}:{evidence.parameters_hash or 'na'}"
            add_node(
                GraphNode(
                    node_id=feature_node,
                    kind=NODE_FEATURE,
                    label=f"zone {evidence.module_id}",
                    attributes={
                        "low": format(evidence.price_zone.low, "f"),
                        "high": format(evidence.price_zone.high, "f"),
                    },
                )
            )
            edges.append(GraphEdge(feature_node, evidence_node, "contextualizes", 0.5))

    if decision is not None:
        decision_node = f"dec:{analysis_run_id or decision.action.value}"
        add_node(
            GraphNode(
                node_id=decision_node,
                kind=NODE_DECISION,
                label=decision.action.value,
                attributes={
                    "score": decision.score,
                    "coverage": decision.coverage,
                    "stability": decision.stability,
                    "no_trade_reason": decision.no_trade_reason,
                    "rules_version": rules_version,
                    "model_versions": dict(model_versions or {}),
                },
            )
        )
        for evidence in items:
            if evidence.evidence_id in redundant:
                continue
            edges.append(GraphEdge(f"ev:{evidence.evidence_id}", decision_node, "informs", float(evidence.strength)))

    # خوشه‌بندی: خانواده + جهت؛ چند ماژول هم‌جهت در یک خانواده «هم‌بسته» هستند.
    clusters: dict[str, list[str]] = {}
    for evidence in items:
        if evidence.evidence_id in redundant:
            continue
        key = f"{evidence.family.value}:{evidence.direction.value}"
        clusters.setdefault(key, []).append(evidence.evidence_id)
    clusters_tuple = {
        key: tuple(sorted(value)) for key, value in clusters.items() if len(value) > 1
    }

    graph_id = "eg_" + sha256_obj(
        {
            "run": analysis_run_id,
            "nodes": sorted(nodes.keys()),
            "edges": sorted(
                (edge.source, edge.target, edge.relation) for edge in edges
            ),
            "redundant": sorted(redundant),
            "rules_version": rules_version,
        }
    )[:24]
    return EvidenceGraph(
        graph_id=graph_id,
        nodes=tuple(sorted(nodes.values(), key=lambda node: node.node_id)),
        edges=tuple(edges),
        clusters=clusters_tuple,
        redundant_ids=tuple(sorted(redundant)),
        generated_at=generated_at,
    )


def effective_family_strength(evidences: Iterable[Evidence]) -> dict[str, float]:
    """قدرت مؤثر هر خانواده پس از حذف تکرارها؛ ۱٫۰ یعنی فقط یک شاهد مستقل."""
    items = list(evidences)
    redundant = set(redundant_evidence(items))
    kept = [evidence for evidence in items if evidence.evidence_id not in redundant]
    families: dict[str, set[str]] = {}
    for evidence in kept:
        families.setdefault(evidence.family.value, set()).add(evidence.module_id)
    return {
        family: round(1.0 / max(len(modules), 1), 4)
        for family, modules in families.items()
    }


def graph_direction_summary(graph: EvidenceGraph) -> dict[str, int]:
    summary: dict[str, int] = {}
    for node in graph.nodes:
        if node.kind != NODE_EVIDENCE:
            continue
        direction = str(node.attributes.get("direction", Direction.NEUTRAL.value))
        summary[direction] = summary.get(direction, 0) + 1
    return summary
