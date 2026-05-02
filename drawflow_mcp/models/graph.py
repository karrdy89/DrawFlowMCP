from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{1,80}$")]
HexColor = Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")]
MetadataValue = str | int | float | bool


class Point(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: int | float
    y: int | float


class Size(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width: Annotated[int | float, Field(ge=80)]
    height: Annotated[int | float, Field(ge=50)]


class ArrowSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: Literal["none", "classic", "open", "block", "diamond", "oval"] = "none"
    end: Literal["none", "classic", "open", "block", "diamond", "oval"] = "classic"
    startFill: bool = False
    endFill: bool = True


class EdgeStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strokeColor: HexColor | None = None
    strokeWidth: Annotated[int | float, Field(ge=1, le=12)] | None = None
    lineStyle: Literal["solid", "dashed", "dotted"] | None = None


class NodeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Identifier
    label: Annotated[str, Field(min_length=1, max_length=80)]
    kind: Literal[
        "service",
        "database",
        "queue",
        "gateway",
        "actor",
        "container",
        "external",
        "decision",
        "document",
        "custom",
    ] = "service"
    parent: Identifier | None = None
    group: str | None = None
    summary: Annotated[str, Field(max_length=80)] = ""
    detail: Annotated[str, Field(max_length=5000)] = ""
    position: Point | None = None
    size: Size | None = None
    style: dict[str, Any] = Field(default_factory=dict)
    icon: dict[str, Any] | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)


class EdgeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Identifier
    source: Identifier
    target: Identifier
    label: Annotated[str, Field(max_length=40)] = ""
    kind: Literal["sync", "async", "data", "control", "dependency", "inheritance", "custom"] = "sync"
    detail: Annotated[str, Field(max_length=5000)] = ""
    arrow: ArrowSpec = Field(default_factory=ArrowSpec)
    style: EdgeStyle = Field(default_factory=EdgeStyle)
    route: Literal["orthogonal", "straight", "curved", "elbow", "entityRelation"] = "orthogonal"
    waypoints: list[Point] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)


class DetailSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    targetType: Literal["diagram", "node", "edge"]
    targetId: Identifier | None = None
    title: str | None = None
    markdown: Annotated[str, Field(min_length=1, max_length=5000)]
    links: list[dict[str, str]] = Field(default_factory=list)
    properties: dict[str, MetadataValue] = Field(default_factory=dict)


class ClusterSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Identifier
    label: Annotated[str, Field(min_length=1, max_length=80)]
    nodes: Annotated[list[Identifier], Field(min_length=1)]
    summary: Annotated[str, Field(max_length=120)] = ""
    detail: Annotated[str, Field(max_length=5000)] = ""
    style: dict[str, Any] = Field(default_factory=dict)


class GraphDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["drawflow.graph/v1"]
    title: Annotated[str, Field(min_length=1, max_length=120)]
    description: Annotated[str, Field(max_length=1000)] = ""
    type: Literal["architecture", "flowchart", "sequence", "erd", "network", "generic"] = "architecture"
    direction: Literal["TB", "BT", "LR", "RL"] = "LR"
    theme: str = "default"
    page: dict[str, Any] | None = None
    layout: dict[str, Any] = Field(default_factory=dict)
    nodes: Annotated[list[NodeSpec], Field(min_length=1)]
    edges: list[EdgeSpec] = Field(default_factory=list)
    clusters: list[ClusterSpec] = Field(default_factory=list)
    specs: list[DetailSpec] = Field(default_factory=list)
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_graph_integrity(self) -> GraphDocument:
        node_ids = [node.id for node in self.nodes]
        duplicate_node = _first_duplicate(node_ids)
        if duplicate_node:
            raise ValueError(f"duplicate node id: {duplicate_node}")
        edge_ids = [edge.id for edge in self.edges]
        duplicate_edge = _first_duplicate(edge_ids)
        if duplicate_edge:
            raise ValueError(f"duplicate edge id: {duplicate_edge}")
        cluster_ids = [cluster.id for cluster in self.clusters]
        duplicate_cluster = _first_duplicate(cluster_ids)
        if duplicate_cluster:
            raise ValueError(f"duplicate cluster id: {duplicate_cluster}")
        node_id_set = set(node_ids)
        cluster_id_set = set(cluster_ids)
        overlapping_cluster = node_id_set & cluster_id_set
        if overlapping_cluster:
            raise ValueError(f"cluster id conflicts with node id: {sorted(overlapping_cluster)[0]}")
        for edge in self.edges:
            if edge.source not in node_id_set:
                raise ValueError(f"edge '{edge.id}' references missing source node '{edge.source}'")
            if edge.target not in node_id_set:
                raise ValueError(f"edge '{edge.id}' references missing target node '{edge.target}'")
        for node in self.nodes:
            if node.parent and node.parent not in node_id_set:
                raise ValueError(f"node '{node.id}' references missing parent node '{node.parent}'")
            if node.parent == node.id:
                raise ValueError(f"node '{node.id}' cannot be its own parent")
        for cluster in self.clusters:
            duplicate_member = _first_duplicate(cluster.nodes)
            if duplicate_member:
                raise ValueError(f"cluster '{cluster.id}' contains duplicate node '{duplicate_member}'")
            for member_id in cluster.nodes:
                if member_id not in node_id_set:
                    raise ValueError(f"cluster '{cluster.id}' references missing node '{member_id}'")
        return self


class GraphOutputSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width: Annotated[int, Field(ge=600, le=4000)] = 1600
    height: Annotated[int, Field(ge=400, le=3000)] = 1000
    scale: Annotated[int, Field(ge=1, le=3)] = 2
    transparentBackground: bool = False


class DetailsOutputSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width: Annotated[int, Field(ge=600, le=4000)] = 1600
    maxHeight: Annotated[int, Field(ge=800, le=24000)] = 4000
    scale: Annotated[int, Field(ge=1, le=3)] = 2
    layout: Literal["cards"] = "cards"
    autoGrow: bool = False


class OutputSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph: GraphOutputSpec = Field(default_factory=GraphOutputSpec)
    details: DetailsOutputSpec = Field(default_factory=DetailsOutputSpec)


def _first_duplicate(values: list[str]) -> str | None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            return value
        seen.add(value)
    return None
