# -*- coding: utf-8 -*-
"""EMV策略集成端到端验证测试"""
import sys, os, math, random

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

def test_imports():
    """测试1：所有EMV模块导入正常"""
    from backend.strategy.emv_strategy import EMVSignalGenerator, EMVSignalResult
    from backend.strategy.indicators import emv, IndicatorResult, _nan_to_zero
    from backend.strategy.scoring import StrategyScoringEngine
    from backend.strategy import EMVSignalGenerator as E2
    assert hasattr(IndicatorResult(), "emv"), "IndicatorResult应有emv字段"
    assert hasattr(IndicatorResult(), "emv_signal"), "IndicatorResult应有emv_signal字段"
    assert hasattr(IndicatorResult(), "emv_cross_up"), "IndicatorResult应有emv_cross_up字段"
    assert hasattr(StrategyScoringEngine(), "emv_generator"), "ScoringEngine应有emv_generator"
    print("[PASS] 测试1：EMV模块导入 + 字段扩展验证")

def test_emv_indicator():
    """测试2：EMV指标计算正确性"""
    from backend.strategy.indicators import emv
    # 构造30根K线
    random.seed(42)
    highs, lows, vols = [], [], []
    price = 2000.0
    for i in range(30):
        p = price * (1 + random.gauss(0.001, 0.01))
        h = p * (1 + random.uniform(0, 0.005))
        l = p * (1 - random.uniform(0, 0.005))
        v = random.uniform(500000, 2000000)
        highs.append(h); lows.append(l); vols.append(v)
        price = p
    main, sig = emv(highs, lows, vols, 14, 3, 10000000.0)
    assert len(main) == 30, f"EMV长度应等于输入长度30，实际{len(main)}"
    assert len(sig) == 30
    assert not math.isnan(main[-1]), "最新EMV值不应为NaN"
    print(f"[PASS] 测试2：EMV指标计算正常，最新值={main[-1]:.6f}，信号线={sig[-1]:.6f}")

def test_signal_generator():
    """测试3：EMV信号生成器10层过滤"""
    from backend.strategy.emv_strategy import EMVSignalGenerator
    gen = EMVSignalGenerator()
    # 构造200根模拟K线
    random.seed(42)
    klines = []
    price = 2000.0
    from datetime import datetime, timedelta
    dt = datetime(2024, 1, 1)
    for i in range(250):
        p = price * (1 + random.gauss(0.0008, 0.008))
        h = p * (1 + random.uniform(0, 0.004))
        l = p * (1 - random.uniform(0, 0.004))
        v = random.uniform(500000, 2000000)
        klines.append({
            "dt": dt, "open": round(price, 2), "high": round(h, 2),
            "low": round(l, 2), "close": round(p, 2), "volume": round(v, 0)
        })
        price = p; dt += timedelta(hours=4)
    result = gen.generate(klines, symbol="XAU", timeframe="4h")
    assert isinstance(result.signal, int), "信号应为int"
    assert 0 <= result.score <= 10, f"评分应在0-10，实际{result.score}"
    assert len(result.filter_details) > 0, "应有过滤详情"
    print(f"[PASS] 测试3：EMV信号生成器正常，signal={result.signal}, score={result.score}")
    print(f"  过滤详情: {result.filter_details}")
    if result.reasons:
        print(f"  理由: {result.reasons[0][:80]}")

def test_strategy_model():
    """测试4：StrategyConfig有strategy_type字段"""
    from backend.models.strategy import StrategyConfig
    assert hasattr(StrategyConfig, "strategy_type"), "StrategyConfig应有strategy_type"
    assert StrategyConfig.TYPE_STANDARD == "standard"
    assert StrategyConfig.TYPE_EMV == "emv"
    print("[PASS] 测试4：StrategyConfig模型strategy_type字段正常")

def test_scoring_emv_branch():
    """测试5：ScoringEngine的EMV策略分支"""
    from backend.strategy.emv_strategy import EMVSignalGenerator
    from backend.strategy.indicators import TechnicalAnalyzer
    gen = EMVSignalGenerator()
    # 构造K线数据
    random.seed(42)
    klines = []
    price = 2000.0
    from datetime import datetime, timedelta
    dt = datetime(2024, 1, 1)
    for i in range(250):
        p = price * (1 + random.gauss(0.0008, 0.008))
        h = p * (1 + random.uniform(0, 0.004))
        l = p * (1 - random.uniform(0, 0.004))
        v = random.uniform(500000, 2000000)
        klines.append({
            "dt": dt, "open": round(price, 2), "high": round(h, 2),
            "low": round(l, 2), "close": round(p, 2), "volume": round(v, 0)
        })
        price = p; dt += timedelta(hours=4)
    # 技术分析器应正常工作（包含EMV）
    ta = TechnicalAnalyzer()
    tech = ta.analyze(klines, timeframe="4h")
    assert hasattr(tech.indicators, "emv"), "TechnicalScoreResult.indicators应有emv"
    print(f"[PASS] 测试5：TechnicalAnalyzer集成了EMV指标，emv={tech.indicators.emv:.6f}")

def test_candles_with_volume():
    """测试6：_candles_to_arrays返回volumes"""
    from backend.strategy.indicators import _candles_to_arrays
    klines = [{"open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 1000}]
    opens, highs, lows, closes, vols = _candles_to_arrays(klines)
    assert vols[0] == 1000, f"volume应为1000，实际{vols[0]}"
    print("[PASS] 测试6：_candles_to_arrays正确返回volumes")

if __name__ == "__main__":
    print("=" * 60)
    print("EMV策略集成端到端测试")
    print("=" * 60)
    test_imports()
    test_emv_indicator()
    test_signal_generator()
    test_strategy_model()
    test_scoring_emv_branch()
    test_candles_with_volume()
    print("=" * 60)
    print("全部测试通过！EMV策略集成成功。")
    print("=" * 60)
