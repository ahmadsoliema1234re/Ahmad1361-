# SignalBazan AI — starter Telegram signal bot

This is a starter, educational signal bot. It reads public Binance USDⓈ-M futures market data and posts heuristic LONG/SHORT candidates. It does not connect to a user's exchange account and cannot place trades.

## Security first
A bot token was pasted into chat more than once. Revoke the exposed token in Telegram's official @BotFather and use a NEW token. Never paste the new token into chats or source code committed to a public repository. Set it as a secret/environment variable in the hosting service.

## Features in this starter
- /start, /help, /status and /scan commands
- Scans up to 40 of the highest 24-hour quote-volume USDT perpetual contracts on Binance Futures
- Uses 15-minute candles and simple trend, RSI, volume, breakout checks
- Suggests a recent swing-based stop and 1R/2R targets
- Optional periodic alerts when ALLOWED_CHAT_IDS is configured

## Important limitations
- This is not an institutional AI model and the score is a rule score, NOT a calibrated probability of winning.
- It does not scan every exchange or every listed coin. It currently uses Binance public futures data only.
- Test thoroughly and paper-trade before relying on any signal. No profits are guaranteed.
- API availability and regional restrictions may vary.
- Never add exchange trading API keys to this project.

## Phone-only deployment outline
1. Create a private repository in GitHub from your phone and upload `bot.py`, `requirements.txt`, and `render.yaml`.
2. Create a background worker on a hosting provider that supports Python background processes.
3. Add `TELEGRAM_BOT_TOKEN` as a secret/environment variable in the host dashboard. Do not put it in the repository.
4. Deploy and open the bot in Telegram, press Start, then send `/scan`.
5. To enable automatic alerts, send `/id` to the bot to see your chat ID, then set `ALLOWED_CHAT_IDS` in the host environment and redeploy. Do not use third-party websites that ask for your bot token.
6. Check worker logs and test a few days in paper mode before using signals.

## Running locally
Install Python 3.11+, then:
`pip install -r requirements.txt`
Set environment variable `TELEGRAM_BOT_TOKEN`, then:
`python bot.py`

## Strategy note
The default MIN_SCORE=4 requires all four simple conditions to align. If no signal appears, that's intentional. The code currently uses a fixed 15m timeframe and should be validated and improved before any real-money decisions.
