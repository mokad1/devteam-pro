"""手写 DAG（有向无环图）数据结构 + 拓扑排序。

设计思路：
- 使用邻接表存储图结构
- 入度表支持拓扑排序（Kahn 算法）
- 支持并行执行同一层级的所有节点（asyncio.gather）
- 检测环路（对于不应该有环的正常流水线阶段）

用途：
- 建模 Agent 流水线的阶段依赖关系
- 未来可扩展为更复杂的 DAG 流程
"""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from devteam_pro.utils.logger import get_logger

logger = get_logger("scheduler.dag")

T = TypeVar("T")


class DAG:
    """有向无环图数据结构。

    支持添加节点和边，以及拓扑排序获取执行顺序。
    """

    def __init__(self) -> None:
        """初始化空 DAG。"""
        self._nodes: dict[str, Any] = {}            # node_id → node payload
        self._edges: dict[str, list[str]] = defaultdict(list)  # from_node → [to_nodes]
        self._in_degree: dict[str, int] = defaultdict(int)

    def add_node(self, node_id: str, payload: Any = None) -> None:
        """添加节点。

        Args:
            node_id: 节点唯一标识。
            payload: 节点附加数据。

        Raises:
            ValueError: 节点已存在。
        """
        if node_id in self._nodes:
            raise ValueError(f"Node '{node_id}' already exists")
        self._nodes[node_id] = payload
        self._in_degree.setdefault(node_id, 0)

    def add_edge(self, from_node: str, to_node: str) -> None:
        """添加有向边 from_node → to_node。

        Args:
            from_node: 源节点 ID。
            to_node: 目标节点 ID。

        Raises:
            ValueError: 节点不存在。
        """
        if from_node not in self._nodes:
            raise ValueError(f"Node '{from_node}' not found")
        if to_node not in self._nodes:
            raise ValueError(f"Node '{to_node}' not found")
        self._edges[from_node].append(to_node)
        self._in_degree[to_node] += 1

    def topological_sort(self) -> list[list[str]]:
        """Kahn 算法拓扑排序，返回按层级分组的节点列表。

        同一层级的节点可并行执行（入度同时为 0）。

        Returns:
            二维列表：外层是层级，内层是该层级的节点 ID。

        Raises:
            RuntimeError: 图中存在环路。
        """
        in_degree = dict(self._in_degree)
        queue: deque[str] = deque(
            n for n in self._nodes if in_degree.get(n, 0) == 0
        )
        levels: list[list[str]] = []
        visited_count = 0

        while queue:
            level: list[str] = []
            for _ in range(len(queue)):
                node = queue.popleft()
                level.append(node)
                visited_count += 1
                for neighbor in self._edges.get(node, []):
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        queue.append(neighbor)
            levels.append(level)

        if visited_count != len(self._nodes):
            raise RuntimeError(
                f"DAG contains a cycle! Visited {visited_count}/{len(self._nodes)} nodes."
            )

        return levels

    async def execute_sequential(
        self,
        executor: Callable[[str, Any], Awaitable[T]],
    ) -> list[T]:
        """按拓扑顺序依次执行所有节点（每层并行，层间串行）。

        Args:
            executor: 执行函数，接收 (node_id, payload)，返回结果。

        Returns:
            按拓扑顺序排列的所有节点执行结果。
        """
        levels = self.topological_sort()
        results: dict[str, T] = {}

        for level_idx, level in enumerate(levels):
            logger.info("Executing level %d: %s", level_idx, level)
            tasks = [
                executor(node_id, self._nodes[node_id])
                for node_id in level
            ]
            level_results = await asyncio.gather(*tasks, return_exceptions=True)
            for node_id, result in zip(level, level_results):
                if isinstance(result, Exception):
                    logger.error("Node '%s' failed: %s", node_id, result)
                    raise result
                results[node_id] = result

        return [results[node_id] for node_id in self.topological_order_flat()]

    def topological_order_flat(self) -> list[str]:
        """获取扁平化的拓扑顺序。"""
        levels = self.topological_sort()
        return [node for level in levels for node in level]

    @property
    def node_count(self) -> int:
        """节点总数。"""
        return len(self._nodes)

    def __repr__(self) -> str:
        return f"<DAG nodes={len(self._nodes)} edges={sum(len(v) for v in self._edges.values())}>"
