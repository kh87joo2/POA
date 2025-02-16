import sys
from exchange.model import MarketOrder, COST_BASED_ORDER_EXCHANGES, STOCK_EXCHANGES
from exchange.utility import settings
from datetime import datetime, timedelta
from dhooks import Webhook, Embed
from loguru import logger
from devtools import debug, pformat
import traceback
import os

# Gate.io 선물은 비용 기반 주문이 아닌 계약 기반 주문이므로,
# COST_BASED_ORDER_EXCHANGES에는 추가하지 않습니다.
# (예: COST_BASED_ORDER_EXCHANGES.append("GATEIO") 는 사용하지 않음)

logger.remove(0)
logger.add(
    "./log/poa.log",
    rotation="1 days",
    retention="7 days",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
)
logger.add(
    sys.stderr,
    colorize=True,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level}</level> | <level>{message}</level>",
)

try:
    url = settings.DISCORD_WEBHOOK_URL.replace("discordapp", "discord")
    hook = Webhook(url)
except Exception as e:
    print("웹훅 URL이 유효하지 않습니다: ", settings.DISCORD_WEBHOOK_URL)


def get_error(e):
    tb = traceback.extract_tb(e.__traceback__)
    target_folder = os.path.abspath(os.path.dirname(tb[0].filename))
    error_msg = []
    for tb_info in tb:
        error_msg.append(f"File {tb_info.filename}, line {tb_info.lineno}, in {tb_info.name}")
        if "raise error." in tb_info.line:
            continue
        error_msg.append(f"  {tb_info.line}")
    error_msg.append(str(e))
    return "\n".join(error_msg)


def parse_time(utc_timestamp):
    timestamp = utc_timestamp + timedelta(hours=9).seconds
    date = datetime.fromtimestamp(timestamp)
    return date.strftime("%y-%m-%d %H:%M:%S")


def logger_test():
    date = parse_time(datetime.utcnow().timestamp())
    logger.info(date)


def log_message(message="None", embed: Embed = None):
    if hook:
        if embed:
            hook.send(embed=embed)
        else:
            hook.send(message)
    else:
        logger.info(message)
        print(message)


def log_order_message(exchange_name, order_result: dict, order_info: MarketOrder):
    date = parse_time(datetime.utcnow().timestamp())
    
    # 선물 주문 처리
    if order_info.is_futures:
        if exchange_name == "GATEIO":
            # Gate.io 선물 주문 응답 예시:
            # { "order_id": "12345", "filled_qty": "10", "avg_deal_price": "5000", ... }
            f_name = "계약"
            filled_qty = order_result.get("filled_qty")
            avg_deal_price = order_result.get("avg_deal_price")
            if filled_qty is not None and avg_deal_price is not None:
                amount = f"{filled_qty} (평균 체결가: {avg_deal_price})"
            else:
                amount = str(order_result.get("amount", ""))
        else:
            # 다른 선물 거래소의 경우 기존 로직 사용 (예: OKX 등)
            if order_result.get("amount") is not None:
                if order_info.contract_size is not None:
                    f_name = "계약"
                    if order_result.get("cost") is not None:
                        f_name = "계약(비용)"
                        amount = f"{order_result.get('amount')}({order_result.get('cost'):.2f})"
                    else:
                        amount = f"{order_result.get('amount')}"
                else:
                    if order_info.amount is not None:
                        f_name = "수량"
                        amount = f"{order_result.get('amount')}"
                    elif order_info.percent is not None:
                        f_name = "비율(수량)" if order_info.is_contract is None else "비율(계약)"
                        amount = f"{order_info.percent}%({order_result.get('amount')})"
            else:
                amount = ""
    else:
        # Spot 주문 및 기타 거래
        if order_info.is_buy and exchange_name in COST_BASED_ORDER_EXCHANGES:
            f_name = "비용"
            if order_info.amount is not None:
                if exchange_name == "UPBIT":
                    amount = str(order_result.get("cost"))
                elif exchange_name == "BITGET":
                    amount = str(order_info.amount * order_info.price)
                elif exchange_name == "BYBIT":
                    amount = str(order_result.get("info").get("orderQty"))
                else:
                    amount = str(order_result.get("cost"))
        else:
            f_name = "수량"
            amount = None
            if exchange_name in STOCK_EXCHANGES:
                # 주식 거래 처리
                content = f"일시\n{date}\n\n거래소\n{exchange_name}\n\n티커\n{order_info.base}\n\n거래유형\n{side}\n\n{amount}"
                embed = Embed(
                    title=order_info.order_name,
                    description=f"체결 {exchange_name} {order_info.base} {side} {amount}",
                    color=0x0000FF,
                )
                embed.add_field(name="일시", value=str(date), inline=False)
                embed.add_field(name="거래소", value=exchange_name, inline=False)
                embed.add_field(name="티커", value=order_info.base, inline=False)
                embed.add_field(name="거래유형", value=side, inline=False)
                embed.add_field(name="수량", value=amount, inline=False)
                embed.add_field(name="계좌", value=f"{order_info.kis_number}번째 계좌", inline=False)
                log_message(content, embed)
                return
            elif order_result.get("amount") is None:
                if order_info.amount is not None:
                    if exchange_name == "OKX":
                        if order_info.is_futures:
                            f_name = "계약(수량)"
                            amount = f"{order_info.amount}"
                        else:
                            amount = f"{order_info.amount}"
                    else:
                        amount = str(order_info.amount)
                elif order_info.percent is not None:
                    if order_info.amount_by_percent is not None:
                        f_name = "비율(수량)" if order_info.is_contract is None else "비율(계약)"
                        amount = f"{order_info.percent}%({order_info.amount_by_percent})"
                    else:
                        f_name = "비율"
                        amount = f"{order_info.percent}%"
            elif order_result.get("amount") is not None:
                if order_info.contract_size is not None:
                    f_name = "계약"
                    if order_result.get("cost") is not None:
                        f_name = "계약(비용)"
                        amount = f"{order_result.get('amount')}({order_result.get('cost'):.2f})"
                    else:
                        amount = f"{order_result.get('amount')}"
                else:
                    if order_info.amount is not None:
                        f_name = "수량"
                        amount = f"{order_result.get('amount')}"
                    elif order_info.percent is not None:
                        f_name = "비율(수량)" if order_info.is_contract is None else "비율(계약)"
                        amount = f"{order_info.percent}%({order_result.get('amount')})"

    # 심볼 구성 (암호화폐인 경우 별도 처리)
    symbol = f"{order_info.base}/{order_info.quote+'.P' if order_info.is_crypto and order_info.is_futures else order_info.quote}"

    # 거래유형(매수/매도) 결정
    side = ""
    if order_info.is_futures:
        if order_info.is_entry:
            if order_info.is_buy:
                side = "롱 진입"
            elif order_info.is_sell:
                side = "숏 진입"
        elif order_info.is_close:
            if order_info.is_buy:
                side = "숏 종료"
            elif order_info.is_sell:
                side = "롱 종료"
    else:
        if order_info.is_buy:
            side = "매수"
        elif order_info.is_sell:
            side = "매도"

    # 메시지 및 임베드 생성
    if exchange_name in STOCK_EXCHANGES:
        content = f"일시\n{date}\n\n거래소\n{exchange_name}\n\n티커\n{order_info.base}\n\n거래유형\n{side}\n\n{amount}"
        embed = Embed(
            title=order_info.order_name,
            description=f"체결 {exchange_name} {order_info.base} {side} {amount}",
            color=0x0000FF,
        )
        embed.add_field(name="일시", value=str(date), inline=False)
        embed.add_field(name="거래소", value=exchange_name, inline=False)
        embed.add_field(name="티커", value=order_info.base, inline=False)
        embed.add_field(name="거래유형", value=side, inline=False)
        embed.add_field(name="수량", value=amount, inline=False)
        embed.add_field(name="계좌", value=f"{order_info.kis_number}번째 계좌", inline=False)
        log_message(content, embed)
    else:
        content = f"일시\n{date}\n\n거래소\n{exchange_name}\n\n심볼\n{symbol}\n\n거래유형\n{order_result.get('side')}\n\n{amount}"
        embed = Embed(
            title=order_info.order_name,
            description=f"체결: {exchange_name} {symbol} {side} {amount}",
            color=0x0000FF,
        )
        embed.add_field(name="일시", value=str(date), inline=False)
        embed.add_field(name="거래소", value=exchange_name, inline=False)
        embed.add_field(name="심볼", value=symbol, inline=False)
        embed.add_field(name="거래유형", value=side, inline=False)
        if amount:
            embed.add_field(name=f_name, value=amount, inline=False)
        if order_info.leverage is not None:
            embed.add_field(name="레버리지", value=f"{order_info.leverage}배", inline=False)
        if order_result.get("price"):
            embed.add_field(name="체결가", value=str(order_result.get("price")), inline=False)
        log_message(content, embed)


def log_hedge_message(exchange, base, quote, exchange_amount, upbit_amount, hedge):
    date = parse_time(datetime.utcnow().timestamp())
    hedge_type = "헷지" if hedge == "ON" else "헷지 종료"
    content = f"{hedge_type}: {base} ==> {exchange}:{exchange_amount} UPBIT:{upbit_amount}"
    embed = Embed(title="헷지", description=content, color=0x0000FF)
    embed.add_field(name="일시", value=str(date), inline=False)
    embed.add_field(name="거래소", value=f"{exchange}-UPBIT", inline=False)
    embed.add_field(name="심볼", value=f"{base}/{quote}-{base}/KRW", inline=False)
    embed.add_field(name="거래유형", value=hedge_type, inline=False)
    embed.add_field(name="수량", value=f"{exchange}:{exchange_amount} UPBIT:{upbit_amount}", inline=False)
    log_message(content, embed)


def log_error_message(error, name):
    embed = Embed(title=f"{name} 에러", description=f"[{name} 에러가 발생했습니다]\n{error}", color=0xFF0000)
    logger.error(f"{name} [에러가 발생했습니다]\n{error}")
    log_message(embed=embed)


def log_order_error_message(error: str | Exception, order_info: MarketOrder):
    if isinstance(error, Exception):
        error = get_error(error)
    if order_info is not None:
        embed = Embed(
            title=order_info.order_name,
            description=f"[주문 오류가 발생했습니다]\n{error}",
            color=0xFF0000,
        )
        log_message(embed=embed)
        logger.error(f"[주문 오류가 발생했습니다]\n{error}")
    else:
        embed = Embed(
            title="오류",
            description=f"[오류가 발생했습니다]\n{error}",
            color=0xFF0000,
        )
        log_message(embed=embed)
        logger.error(f"[오류가 발생했습니다]\n{error}")


def log_validation_error_message(msg):
    logger.error(f"검증 오류가 발생했습니다\n{msg}")
    log_message(msg)


def print_alert_message(order_info: MarketOrder, result="성공"):
    msg = pformat(order_info.dict(exclude_none=True))
    if result == "성공":
        logger.info(f"주문 {result} 웹훅메세지\n{msg}")
    else:
        logger.error(f"주문 {result} 웹훅메세지\n{msg}")


def log_alert_message(order_info: MarketOrder, result="성공"):
    embed = Embed(
        title=order_info.order_name,
        description="[웹훅 alert_message]",
        color=0xFF0000,
    )
    order_info_dict = order_info.dict(exclude_none=True)
    for key, value in order_info_dict.items():
        embed.add_field(name=key, value=str(value), inline=False)
    log_message(embed=embed)
    print_alert_message(order_info, result)
