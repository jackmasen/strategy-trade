# 交易所对接包
# 结构：
#   base.py      - 抽象基类 + 工厂函数(按 exchange_account.exchange 值选 Binance/OKX)
#   binance.py   - 币安 USDⓈ-M 合约 API 封装
#   okx.py       - OKX 统一账户 SWAP 合约 API 封装
#   market.py    - 行情管理器：WS 实时价格 + K线聚合 + 缓存(高频减压)
#   _types.py    - 通用数据结构：Order/Position/Balance/Candle/Ticker
