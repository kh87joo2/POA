from exchange.pexchange import ccxt, httpx
from exchange.model import MarketOrder
import exchange.error as error
import gate_api
from gate_api.exceptions import ApiException, GateApiException
from devtools import debug

class GateIO:
    def __init__(self, key, secret):
        # Gate.io API 클라이언트 초기화
        self.configuration = gate_api.Configuration(
            host = "https://api.gateio.ws/api/v4",
            key = key,
            secret = secret
        )
        self.api_client = gate_api.ApiClient(self.configuration)
        self.spot_api = gate_api.SpotApi(self.api_client)
        self.unified_api = gate_api.UnifiedApi(self.api_client)
        self.client = self.api_client  # 호환성을 위한 별칭
        self.order_info: MarketOrder = None
        self.position_mode = "one-way"

    def init_info(self, order_info: MarketOrder):
        self.order_info = order_info
        unified_symbol = order_info.unified_symbol
        
        # 마켓 타입 설정
        if order_info.is_futures:
            if order_info.is_coinm:
                self.api_client.default_header['Settle'] = 'usd'
            else:
                self.api_client.default_header['Settle'] = 'usdt'
            self.client.options["defaultType"] = "swap"
        else:
            self.client.options["defaultType"] = "spot"

        # 계약 정보 파싱
        market = self.spot_api.list_tickers(currency_pair=unified_symbol)[0]
        if hasattr(market, 'contract_size'):
            order_info.is_contract = True
            order_info.contract_size = market.contract_size

        # 금액 정밀도 설정
        if order_info.amount is not None:
            order_info.amount = float(
                self.spot_api.amount_to_precision(unified_symbol, order_info.amount)
            )

    def get_ticker(self, symbol: str):
        return self.spot_api.list_tickers(currency_pair=symbol)[0]

    def get_price(self, symbol: str):
        return self.get_ticker(symbol).last

    def get_futures_position(self, symbol=None, all=False):
        try:
            positions = self.unified_api.list_unified_positions(settle='usdt' if self.order_info.is_coinm else 'usd')
            long_contracts = None
            short_contracts = None
            
            for pos in positions:
                if pos.side == "long":
                    long_contracts = pos.size
                elif pos.side == "short":
                    short_contracts = pos.size

            if self.order_info.is_close and self.order_info.is_buy:
                return short_contracts or 0
            elif self.order_info.is_close and self.order_info.is_sell:
                return long_contracts or 0
            return positions
        except (ApiException, GateApiException) as e:
            raise error.PositionNoneError()

    def get_balance(self, base: str):
        try:
            balance = self.spot_api.get_account_detail(account='spot')
            return getattr(balance, base.lower(), 0)
        except (ApiException, GateApiException) as e:
            raise error.FreeAmountNoneError()

    def get_amount(self, order_info: MarketOrder) -> float:
        # 기존 로직과 유사한 금액 계산 방식 적용
        if order_info.amount and order_info.percent:
            raise error.AmountPercentBothError()
        
        if order_info.amount:
            return order_info.amount
        
        # 퍼센트 기반 계산
        balance = self.get_balance(order_info.quote if order_info.is_buy else order_info.base)
        price = self.get_price(order_info.unified_symbol)
        return (balance * order_info.percent / 100) / (price if order_info.is_buy else 1)

    def set_leverage(self, leverage: int, symbol: str):
        if self.order_info.is_futures:
            self.unified_api.set_user_leverage_currency_setting({
                "currency": symbol.split('_')[0],
                "leverage": str(leverage)
            })

    def market_order(self, order_info: MarketOrder):
        from exchange.pexchange import retry
        params = {
            'account': 'cross_margin' if self.order_info.is_futures else 'spot',
            'reduceOnly': order_info.is_close
        }
        
        try:
            return retry(
                self.spot_api.create_order,
                order_info.unified_symbol,
                order_info.type.lower(),
                order_info.side,
                order_info.amount,
                params=params,
                max_attempts=5,
                delay=0.1
            )
        except (ApiException, GateApiException) as e:
            raise error.OrderError(e, self.order_info)

    def market_buy(self, order_info: MarketOrder):
        order_info.amount = self.get_amount(order_info)
        return self.market_order(order_info)

    def market_sell(self, order_info: MarketOrder):
        order_info.amount = self.get_amount(order_info)
        return self.market_order(order_info)

    def market_entry(self, order_info: MarketOrder):
        if self.order_info.is_futures:
            self.set_leverage(order_info.leverage, order_info.unified_symbol)
        return self.market_order(order_info)

    def market_close(self, order_info: MarketOrder):
        return self.market_order(order_info)

    # 포지션 모드 설정 메서드
    def set_position_mode(self, mode: str):
        if mode == "hedge":
            self.unified_api.set_unified_mode({"mode": "dual"})
            self.position_mode = "hedge"
        else:
            self.unified_api.set_unified_mode({"mode": "single"})
            self.position_mode = "one-way"
