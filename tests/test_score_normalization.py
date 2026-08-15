"""测试分数归一化模块的纯函数逻辑。"""
import pytest

from utils.score_normalization import min_max_normalize


class TestMinMaxNormalize:
    def test_empty_returns_empty(self):
        assert min_max_normalize([]) == []

    def test_normalizes_to_0_1_range(self):
        result = min_max_normalize([0.0, 0.5, 1.0])
        assert result == pytest.approx([0.0, 0.5, 1.0])

    def test_min_max_of_input(self):
        result = min_max_normalize([3.0, 5.0, 7.0])
        assert result == pytest.approx([0.0, 0.5, 1.0])

    def test_constant_scores_return_0_5(self):
        result = min_max_normalize([0.7, 0.7, 0.7])
        assert result == [0.5, 0.5, 0.5]

    def test_explicit_min_max_clip(self):
        # 显式给定 min/max 时，超出范围的值会被线性缩放到区间外
        result = min_max_normalize([0.0, 1.0], min_val=0.0, max_val=1.0)
        assert result == pytest.approx([0.0, 1.0])

    def test_preserves_order_and_scale(self):
        scores = [0.9, 0.1, 0.5, 0.3]
        result = min_max_normalize(scores)
        assert len(result) == len(scores)
        # 相对顺序保持：0.9 > 0.5 > 0.3 > 0.1
        assert result[0] > result[2] > result[3] > result[1]
        # 值域映射到 [0, 1]
        assert max(result) == pytest.approx(1.0)
        assert min(result) == pytest.approx(0.0)
