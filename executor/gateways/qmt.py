"""QMT 接入，行情与交易分开：QmtMarketGateway 只订阅行情（xtdata），QmtTradeGateway 只负责账户（xttrader）。

纸面 = 行情网关 + 模拟券商，不登录账户；实盘 = 行情网关 + 交易网关。交易网关的编号映射在发送前登记，
恢复后按全部当日委托和成交核对。原生接口/IOPV 的券商版本差异仍须用只读探测确认。本版本实盘要求专用资金账户。
"""
from __future__ import annotations
import time as _time
from datetime import datetime, timedelta
from ..clock import BEIJING, beijing_now
from ..events import CorporateAction, CancelError, GatewayStatus, OrderStatus, OrderUpdate, Quote, Side, Trade
from .base import MarketGateway, TradeGateway

IOPV_KEYS=("iopv","IOPV","iopvPrice","fundIopv")
STATUS={48:OrderStatus.PENDING,49:OrderStatus.PENDING,50:OrderStatus.SUBMITTED,51:OrderStatus.CANCELLING,
        52:OrderStatus.CANCELLING,53:OrderStatus.CANCELLED,54:OrderStatus.CANCELLED,55:OrderStatus.PARTIAL,
        56:OrderStatus.FILLED,57:OrderStatus.REJECTED}

def _iopv(tick):
    for key in IOPV_KEYS:
        if tick.get(key): return float(tick[key])
    return None

def _action_date(index):
    """除权数据的日期索引：毫秒时间戳、YYYYMMDD 字符串或日期类型。"""
    text=str(index)
    if text.isdigit() and len(text) == 8:
        return datetime.strptime(text,"%Y%m%d").date()
    if text.replace(".","",1).isdigit():
        return datetime.fromtimestamp(float(text)/1000,BEIJING).date()
    return datetime.fromisoformat(text[:10]).date()

def _ts(value):
    v=float(value)
    if 0 <= v <= 235959:
        text=f"{int(v):06d}"
        return datetime.combine(beijing_now().date(),datetime.strptime(text,"%H%M%S").time())
    return datetime.fromtimestamp(v/1000 if v > 1e11 else v,BEIJING).replace(tzinfo=None)

class QmtMarketGateway(MarketGateway):
    """只用 xtdata 订阅行情，不登录交易账户：纸面模式只用它，账户上其他程序的交易不会影响纸面引擎。"""
    def __init__(self):
        self.sink=lambda event:None
        self._subscription=None
        self.symbols=[]
        self.last_error=""

    @property
    def connected(self):
        return self._subscription is not None

    def close(self):
        if self._subscription is not None:
            try:
                from xtquant import xtdata
                xtdata.unsubscribe_quote(self._subscription)
            except Exception:
                pass
            self._subscription=None

    def _callback(self,data):
        quotes=[]
        for code,tick in data.items():
            try:
                bid=(tick.get("bidPrice") or [0])[0]; ask=(tick.get("askPrice") or [0])[0]
                quotes.append(Quote(code,_ts(tick["time"]),float(tick.get("lastPrice",0)),float(bid),float(ask),_iopv(tick),
                    previous_close=float(tick["lastClose"]) if tick.get("lastClose") else None))
            except (KeyError,ValueError,TypeError):
                continue
        if quotes: self.sink(("quotes",beijing_now(),quotes))

    def subscribe(self,symbols):
        """QMT 未就绪时不报错退出：记下失败原因，由引擎定时重试（见 Engine.run_live）。"""
        self.symbols=list(symbols)
        return self.resubscribe()

    def resubscribe(self):
        self.close()
        try:
            from xtquant import xtdata
            sid=xtdata.subscribe_whole_quote(self.symbols,callback=self._callback)
            if sid is None or sid < 0:
                raise RuntimeError(f"订阅返回 {sid}")
            self._subscription=sid
            self.last_error=""
            return True
        except Exception as exc:
            self.last_error=str(exc)
            return False


    def corporate_actions(self,symbols,day):
        """只读 QMT 除权数据，返回 day 当日的现金分红和送转。字段不符时报错，不猜测格式。"""
        from xtquant import xtdata
        start=(day-timedelta(days=10)).strftime("%Y%m%d")
        result=[]
        for symbol in symbols:
            frame=xtdata.get_divid_factors(symbol,start,day.strftime("%Y%m%d"))
            if frame is None or len(frame)==0:
                continue
            missing={"interest","stockBonus","stockGift"}-set(frame.columns)
            if missing:
                raise ValueError(f"QMT 除权数据缺少字段 {sorted(missing)}，实际字段 {list(frame.columns)}")
            for index,row in frame.iterrows():
                if _action_date(index) != day:
                    continue
                if float(row.get("allotNum",0) or 0):
                    raise ValueError(f"{symbol} 当日含配股，引擎暂不支持")
                cash=float(row["interest"] or 0)
                split=1+float(row["stockBonus"] or 0)+float(row["stockGift"] or 0)
                if cash or split != 1:
                    result.append(CorporateAction(datetime.combine(day,datetime.min.time()),symbol,cash,split))
        return result


class QmtTradeGateway(TradeGateway):
    """xttrader 报单、撤单、回报与查询；只在实盘使用。专用账户上出现无法归属的委托或成交即暂停。"""
    def __init__(self,userdata_path,account_id,allow_orders=False):
        self.userdata_path,self.account_id,self.allow_orders=userdata_path,account_id,allow_orders
        self.sink=lambda event:None
        self.trader=None; self.account=None
        self._by_qmt_id={}; self._client_orders={}

    def connect(self):
        from xtquant import xtconstant
        from xtquant.xttrader import XtQuantTrader,XtQuantTraderCallback
        from xtquant.xttype import StockAccount
        gw=self; self._xtconstant=xtconstant
        class Callback(XtQuantTraderCallback):
            def on_disconnected(self): gw.sink(GatewayStatus(beijing_now(),False,"QMT 交易连接断开"))
            def on_stock_order(self,o): gw._on_order(o)
            def on_stock_trade(self,t): gw._on_trade(t)
            def on_order_error(self,err):
                cid=gw._cid(err)
                if cid:
                    gw.sink(OrderUpdate(cid,OrderStatus.REJECTED,0,0,beijing_now(),reason=str(getattr(err,"error_msg",err))))
                else:
                    gw.sink(GatewayStatus(beijing_now(),False,"QMT 报单错误无法关联，需查询核对"))
            def on_cancel_error(self,err):
                gw.sink(CancelError(gw._cid(err),beijing_now(),str(getattr(err,"error_msg",err))))
        self.trader=XtQuantTrader(self.userdata_path,int(_time.time()))
        self.trader.register_callback(Callback()); self.trader.start()
        if self.trader.connect()!=0: raise RuntimeError("连接 QMT 交易端失败")
        self.account=StockAccount(self.account_id)
        if self.trader.subscribe(self.account)!=0: raise RuntimeError("订阅资金账号失败")

    def close(self):
        if self.trader: self.trader.stop()

    def restore_orders(self,orders):
        self._client_orders={o.client_id:o for o in orders}
        self._by_qmt_id={int(o.broker_id):o.client_id for o in orders if o.broker_id}

    def _cid(self,obj):
        cid=self._by_qmt_id.get(getattr(obj,"order_id",-1))
        remark=str(getattr(obj,"order_remark","") or "")
        return cid or (remark if remark in self._client_orders else "")

    def send_order(self,o):
        if not self.allow_orders:
            self.sink(OrderUpdate(o.client_id,OrderStatus.REJECTED,0,0,beijing_now(),reason="网关未允许下单")); return
        if len(o.client_id.encode("ascii")) > 24: raise ValueError("客户端委托号超过24字节")
        self._client_orders[o.client_id]=o  # 同步报单尚未返回时也能接收按备注关联的成交。
        xc=self._xtconstant
        qid=self.trader.order_stock(self.account,o.symbol,xc.STOCK_BUY if o.side is Side.BUY else xc.STOCK_SELL,
            o.volume,xc.FIX_PRICE,o.price,o.strategy[:24],o.client_id)
        if qid is None or qid <= 0:
            self.sink(OrderUpdate(o.client_id,OrderStatus.REJECTED,0,0,beijing_now(),reason=f"下单失败 {qid}")); return
        self._by_qmt_id[int(qid)]=o.client_id
        self.sink(OrderUpdate(o.client_id,OrderStatus.SUBMITTED,0,0,beijing_now(),broker_id=str(qid)))

    def cancel_order(self,o):
        if not self.allow_orders or not o.broker_id:
            self.sink(CancelError(o.client_id,beijing_now(),"撤单未发送：缺少许可或券商委托号")); return
        result=self.trader.cancel_order_stock(self.account,int(o.broker_id))
        if result != 0:
            self.sink(CancelError(o.client_id,beijing_now(),f"撤单请求失败 {result}"))

    def _order_update(self,o):
        cid=self._cid(o)
        if not cid: return None
        status=STATUS.get(int(o.order_status))
        if status is None: raise ValueError("QMT 委托状态不支持，需核对")
        self._by_qmt_id[int(o.order_id)]=cid
        return OrderUpdate(cid,status,int(o.traded_volume),float(o.traded_price),beijing_now(),
            broker_id=str(o.order_id),reason=str(getattr(o,"status_msg","") or ""))

    def _trade(self,t):
        cid=self._cid(t)
        if not cid: return None
        o=self._client_orders[cid]
        if not str(t.traded_id):
            raise ValueError("QMT 成交编号为空")
        time=_ts(t.traded_time)
        trade_id=f"{time:%Y%m%d}:{t.order_id}:{t.traded_id}"
        return Trade(trade_id,cid,o.symbol,o.side,float(t.traded_price),int(t.traded_volume),time)

    def _on_order(self,o):
        try:
            u=self._order_update(o)
            if u: self.sink(u)
            elif STATUS.get(int(o.order_status),OrderStatus.UNKNOWN).active:
                self.sink(GatewayStatus(beijing_now(),False,"账户出现其他来源的活动委托"))
        except Exception as exc:
            self.sink(GatewayStatus(beijing_now(),False,str(exc)))

    def _on_trade(self,t):
        try:
            trade=self._trade(t)
            if trade: self.sink(trade)
            else: self.sink(GatewayStatus(beijing_now(),False,"账户出现无法归属的成交，需核对"))
        except Exception as exc:
            self.sink(GatewayStatus(beijing_now(),False,str(exc)))

    def query_positions(self):
        rows=self.trader.query_stock_positions(self.account)
        if rows is None: raise RuntimeError("持仓查询未确认成功")
        return {p.stock_code:int(p.volume) for p in rows if int(p.volume)>0}

    def query_sellable_positions(self):
        rows=self.trader.query_stock_positions(self.account)
        if rows is None: raise RuntimeError("可卖数量查询未确认成功")
        return {p.stock_code:int(p.can_use_volume) for p in rows if int(p.volume)>0}

    def query_cash(self):
        asset=self.trader.query_stock_asset(self.account)
        if asset is None: raise RuntimeError("资金查询失败")
        return float(asset.cash)

    def query_order_updates(self):
        rows=self.trader.query_stock_orders(self.account,False)
        if rows is None: raise RuntimeError("委托查询未确认成功")
        result=[]
        for o in rows:
            u=self._order_update(o)
            if u: result.append(u)
            elif STATUS.get(int(o.order_status),OrderStatus.UNKNOWN).active:
                raise RuntimeError("账户存在其他来源的活动委托；当前版本要求专用账户")
        return result

    def query_trades(self):
        rows=self.trader.query_stock_trades(self.account)
        if rows is None: raise RuntimeError("成交查询未确认成功")
        return [trade for t in rows if (trade:=self._trade(t)) is not None]

    def query_open_orders(self):
        return {u.client_id:{"status":u.status,"filled":u.filled,"avg_price":u.avg_price}
            for u in self.query_order_updates() if u.status.active}
