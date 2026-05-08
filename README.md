# Crypto Setup Bot

Python-бот для поиска часовых торговых сетапов через публичные market-data API без KYC для чтения данных.

Что умеет:

- грузит свечи через публичный API биржи через `ccxt`
- ищет long/short сетапы по стратегии `EMA + RSI + ADX + volume`
- делает бектест с учетом комиссии, плеча и стартового баланса `100$`
- считает `PnL`, `winrate`, `RR`, `drawdown`, `Sharpe`
- показывает отдельный бектест по последним `30`, `60`, `90` дням
- пишет, сколько сделок было открыто за каждый период
- отправляет сигналы в Telegram в realtime-режиме
- умеет работать как Telegram-бот: по команде показывать бектесты и параллельно слать realtime-сигналы
- ведет paper-профиль Telegram-бота: баланс, сделки, winrate, PnL, открытые позиции

Текущие профили:

- `BTC/USDT`: отдельный профиль, `4h`
- `ETH/USDT`: отдельный профиль, `4h`
- `SOL/USDT`: отдельный профиль, `1h`
- `XRP/USDT`: отдельный профиль, `1h`
- `LINK/USDT`: отдельный профиль, `4h`
- `SUI/USDT`: отдельный профиль, `4h`
- `APT/USDT`: отдельный профиль, `4h`
- `ADA/USDT`: отдельный профиль, `4h`
- `DOT/USDT`: отдельный профиль, `1h`

Бот больше не использует один и тот же набор параметров для всех монет.

Важно:

- это не гарантия прибыли
- автооптимизация параметров полезна как исследовательский инструмент, но не заменяет ручную валидацию

## Быстрый старт

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python main.py --mode backtest
python main.py --mode telegram
```

## Режимы

```bash
python main.py --mode backtest
python main.py --mode optimize
python main.py --mode realtime
python main.py --mode telegram
```

## Telegram paper profile

В режиме `telegram` бот:

- сам отслеживает сигналы по активной корзине
- открывает virtual/paper сделки по профилю
- по умолчанию использует стартовый баланс `100$`, риск `5%` на стоп и плечо `40x`
- считает общий PnL, winrate, число сделок и хранит профиль в `paper_profile.json`

Основные команды:

- `/profile`
- `/trades`
- `/positions`
- `/summary`
- `/coin XRP`

## Что покажет backtest

- полный результат по выбранной истории
- отдельные результаты по `30`, `60`, `90` дням
- `opened_trades`: сколько входов было открыто
- `trades`: сколько сделок закрылось в этом периоде
- `strategy_config`: какой именно профиль применялся к символу

## Стратегия

Long:

- `EMA fast > EMA slow`
- цена выше быстрой EMA
- `RSI` выше порога
- `ADX` подтверждает тренд
- объем выше среднего

Short:

- `EMA fast < EMA slow`
- цена ниже быстрой EMA
- `RSI` ниже порога
- `ADX` подтверждает тренд
- объем выше среднего

Выход:

- stop-loss по `ATR`
- take-profit по `ATR`
- trailing-stop по `ATR`
